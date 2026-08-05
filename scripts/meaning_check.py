#!/usr/bin/env python3
"""Чекеры смысловых сценариев (Этап Б, 03.08). Замки конституции карты мостов.

Три проверки:
1. Прямолинейность: зритель-судья отмечает ПЕРВОЕ предложение, где почувствовал
   продажу. Порог: не раньше 80% текста (или продажи нет вообще).
2. Кивабельность: каждый смысловой переход проверяется «согласится ли скептик».
3. Стиль (код, без LLM): длинные тире, слово «директ», рубленость (средняя длина
   предложения), кодовое слово только при продуктовом финале.

Импортируемый модуль (без module-level asyncio.run) + CLI: --file text.txt
"""
import json
import re
import sys

sys.path.insert(0, "/home/MaksVideo/aiplus-content-factory/backend/src")

CHECK_MODEL = "sonnet"


def _parse_json(s: str):
    if "```" in s:
        s = s.split("```")[1]
        if s.startswith("json"):
            s = s[4:]
    i, j = s.find("{"), s.rfind("}")
    if i != -1 and j > i:
        s = s[i:j + 1]
    return json.loads(s)


async def check_directness(text: str) -> dict:
    """Порог: первое «продажное» предложение не раньше 80% текста."""
    from app.services.claude_svc import _run_claude

    prompt = f"""Ты обычный зритель коротких видео в Казахстане, листаешь ленту.
Читай текст озвучки по предложениям С НАЧАЛА. Твоя задача: отметить ПЕРВОЕ
предложение, на котором ты почувствовал, что тебе что-то продают или рекламируют
(центр, курсы, услугу). Если такого ощущения нет вообще — sell_idx = null.

ТЕКСТ:
{text}

Верни СТРОГО JSON: {{"total_sentences": N, "sell_idx": N|null,
"sell_quote": "первое продажное предложение или null", "feel": "1 фраза — общее ощущение"}}"""
    for attempt in range(2):
        raw = await _run_claude(prompt, model=CHECK_MODEL)
        try:
            d = _parse_json(raw)
            break
        except (json.JSONDecodeError, IndexError):
            d = None
    if d is None:
        return {"ok": False, "note": "судья не вернул JSON (fail-closed)"}
    total, idx = d.get("total_sentences") or 0, d.get("sell_idx")
    if idx is None:
        return {"ok": True, "note": "продажа не почувствована", "detail": d}
    pos = idx / total if total else 0
    return {"ok": pos >= 0.8, "note": f"продажа на {pos:.0%} текста ({d.get('sell_quote')})",
            "detail": d}


async def check_nod(text: str) -> dict:
    """Каждый переход между мыслями должен быть кивабельным для скептика."""
    from app.services.claude_svc import _run_claude

    prompt = f"""Вот текст озвучки видео. Он построен как цепочка смыслов (мостов).

ТЕКСТ:
{text}

Выпиши все смысловые ПЕРЕХОДЫ (где одна мысль передаёт слово следующей).
Для каждого ответь как обычный зритель: звучит ли переход естественно?

КАЛИБРОВКА (важно, не перегибай):
- Это публицистика, НЕ научная статья. Обобщения и афоризмы («планка заразна»,
  «голова кормит всю жизнь») — НОРМА, если звучат естественно. Требовать
  доказанности не нужно.
- nod=false СТРОГО только если переход манипулятивный: давление статусом
  («богатые поняли, и ты должен»), подмена понятий (большое решение выдаётся
  за маленькое), реклама, притянутая без связи.
- НАШ ПРИЁМ «перевёртыш» (nod=true, не путать с манипуляцией!): статусный
  контраст («богатые поняли, а бедные нет») ДОПУСТИМ, если сразу после него
  смысл ДЕМОКРАТИЗИРУЕТСЯ: «это доступно каждому по своим возможностям»,
  «у каждой семьи свой масштаб». Зрителя не оставляют в позиции отстающего,
  ему дают его собственный путь. Манипуляция — только если давят статусом
  БЕЗ демократизации («делай как богатые» и точка).
- Переход к ФИНАЛЬНОМУ призыву (последний абзац) НЕ размечай вообще — его
  проверяет отдельный чекер.

Верни СТРОГО JSON: {{"bridges": [{{"from": "мысль А (3-5 слов)",
"to": "мысль Б (3-5 слов)", "nod": true/false, "why": "1 фраза"}}]}}"""
    for attempt in range(2):
        raw = await _run_claude(prompt, model=CHECK_MODEL)
        try:
            d = _parse_json(raw)
            break
        except (json.JSONDecodeError, IndexError):
            d = None
    if d is None or not d.get("bridges"):
        return {"ok": False, "note": "судья не разметил мосты (fail-closed)"}
    bad = [b for b in d["bridges"] if not b.get("nod")]
    return {"ok": not bad, "note": (f"{len(bad)} некивабельных: " +
            "; ".join(f"{b['from']}→{b['to']}: {b['why']}" for b in bad)
            if bad else f"все {len(d['bridges'])} мостов кивабельны"), "detail": d}


def check_style(text: str, no_product: bool = False) -> dict:
    """Кодовые проверки стиля — конституция п.8-9."""
    issues = []
    if "—" in text or "–" in text:
        issues.append("длинное тире (запрещено, выдаёт ИИшность)")
    if re.search(r"директ", text, re.I):
        issues.append("слово «директ» (запрещено владельцем)")
    sents = [s.strip() for s in re.split(r"[.!?]+", text) if s.strip()]
    avg = sum(len(s.split()) for s in sents) / max(1, len(sents))
    # порог 6.5: панчи-списки («Книги дома. Секция рядом.») — авторский ритм,
    # владелец одобрил в пилоте v5 (avg 6.9); валим только тотальное стаккато
    if avg < 6.5:
        issues.append(f"рублено: средняя длина предложения {avg:.1f} слов (<6.5) — "
                      "владелец требует развёрнуто")
    has_codeword = bool(re.search(r"\b(ГРАНТ|ДИАГНОСТИКА)\b", text))
    if no_product and has_codeword:
        issues.append("ролик заявлен «без продукта», но есть кодовое слово")
    return {"ok": not issues, "note": "; ".join(issues) or
            f"стиль ок (ср. предложение {avg:.1f} слов)", "avg_sentence": round(avg, 1)}


async def run_all(text: str, no_product: bool = False) -> dict:
    style = check_style(text, no_product)
    direct = await check_directness(text)
    nod = await check_nod(text)
    return {"ok": style["ok"] and direct["ok"] and nod["ok"],
            "style": style, "directness": direct, "nod": nod}


if __name__ == "__main__":
    import argparse
    import asyncio

    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--no-product", action="store_true")
    a = ap.parse_args()
    res = asyncio.run(run_all(open(a.file, encoding="utf-8").read(), a.no_product))
    print(json.dumps({k: (v if isinstance(v, bool) else
                          {kk: vv for kk, vv in v.items() if kk != "detail"})
                      for k, v in res.items()}, ensure_ascii=False, indent=1))
