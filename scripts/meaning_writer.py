#!/usr/bin/env python3
"""Сценарист смысловых видео (Этап Б, 03.08): вход → маршрут по карте мостов →
развёрнутый сценарий (opus) → чекеры → карточка во вкладку Сторивидео на апрув.

Поток: --topic "тема/текст тренда" [--route В1] [--no-product] [--card]
1. Загружает карту meaning_bridges.md + дуги кодбука + правила стиля.
2. Пишет сценарий творческим ядром (opus, как весь контент завода).
3. Гоняет чекеры (прямолинейность/кивабельность/стиль); 1 круг доработки по фидбеку.
4. Анти-повтор: маршруты из журнала ~/.aiplus-factory/meaning_journal.json
   за последние 5 роликов исключаются из выбора.
5. --card: карточка в story_videos со status='script' (⏸ на апрув владельцу).
"""
import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, "/home/MaksVideo/aiplus-content-factory/backend/src")
sys.path.insert(0, "/home/MaksVideo")

from meaning_check import run_all

BRIDGES = Path.home() / "aiplus-content-factory/backend/data/meaning_bridges.md"
CODEBOOK = Path.home() / "aiplus-content-factory/backend/data/viral_patterns_codebook.md"
JOURNAL = Path.home() / ".aiplus-factory" / "meaning_journal.json"

WRITER_PROMPT = """Ты сценарист смысловых вертикальных видео Айплюс (Казахстан,
подготовка к НИШ/РФМШ/БИЛ, аудитория — родители школьников). Пишешь на русском.

ГЛАВНЫЙ ЗАКОН ФОРМАТА — карта мостов (следовать буквально, особенно конституции):
{bridges}

ДУГИ РАЗВЁРТЫВАНИЯ (выбери подходящую маршруту, см. раздел 5 карты):
{arcs}

ЭТАЛОН РИТМА И СТИЛЯ — наш утверждённый пилот (копировать МАНЕРУ, не слова):
«Посмотрите, как это устроено. Ребёнка из обеспеченной семьи с детства записывают
на шахматы, на языки, отдают в сильную школу. Со стороны кажется, что ему покупают
знания. Но если спросить такого родителя, за что он платит на самом деле, ответ
будет неожиданным. Не за парты, не за учебники и даже не за преподавателей.
Он платит за тех, кто сидит за соседними партами.»

ЗАДАНИЕ:
- Вход (тема/материал): {topic}
- Маршрут по карте: {route}
- Финал: {final_rule}

ТРЕБОВАНИЯ:
1. РАЗВЁРНУТО: одна мысль раскрывается до конца, длинные дышащие предложения
   (в среднем 10+ слов). Хук может быть коротким и хлёстким, тело — нет.
2. Хронометраж 55-70 секунд озвучки (180-230 слов).
3. Каждый переход между абзацами = мост из маршрута, кивабельный сам по себе.
4. Никаких длинных тире. Никакого слова «директ». Никаких цифр, кроме канонических.
5. Продукт (если финал продуктовый) — только в последнем абзаце, мягко.

Верни СТРОГО JSON без markdown:
{{"hook": "первая фраза-хук", "segments": [{{"text": "абзац"}}, ...],
"route_used": "В# → П# → ... → Ф#", "arc": "дуга", "title": "короткое название"}}"""


def _parse_json(s: str):
    if "```" in s:
        s = s.split("```")[1]
        if s.startswith("json"):
            s = s[4:]
    i, j = s.find("{"), s.rfind("}")
    if i != -1 and j > i:
        s = s[i:j + 1]
    return json.loads(s)


def _load_journal() -> list:
    try:
        return json.loads(JOURNAL.read_text())
    except Exception:
        return []


def _arcs_section() -> str:
    text = CODEBOOK.read_text(encoding="utf-8")
    i, j = text.find("## 2. Дуги"), text.find("## 3.")
    return text[i:j] if i != -1 and j > i else ""


async def write_script(topic: str, route: str, no_product: bool) -> tuple[dict, dict]:
    from app.services.claude_svc import _run_claude

    journal = _load_journal()
    recent = [e["route"] for e in journal[-5:]]
    final_rule = ("БЕЗ продукта вообще: финал Ф1 или Ф7, ни намёка на Айплюс и кодовые слова"
                  if no_product else
                  "мягкий продуктовый финал из палитры (Ф2-Ф6), кодовое слово ГРАНТ в самом конце")
    route_rule = route or ("выбери сам подходящий маршрут из раздела 4 карты, "
                           f"НО НЕ эти недавние: {', '.join(recent) or 'нет'}")
    prompt = WRITER_PROMPT.format(bridges=BRIDGES.read_text(encoding="utf-8"),
                                  arcs=_arcs_section(), topic=topic,
                                  route=route_rule, final_rule=final_rule)
    script, checks = None, None
    feedback = ""
    for rnd in range(2):
        raw = await _run_claude(prompt + feedback)  # творческое ядро = opus (дефолт)
        try:
            script = _parse_json(raw)
        except (json.JSONDecodeError, IndexError):
            feedback = "\n\nВАЖНО: верни СТРОГО валидный JSON."
            continue
        full = script.get("hook", "") + "\n\n" + "\n\n".join(
            s.get("text", "") for s in script.get("segments", []))
        checks = await run_all(full, no_product)
        if checks["ok"]:
            break
        fails = "; ".join(f"{k}: {v['note']}" for k, v in checks.items()
                          if isinstance(v, dict) and not v["ok"])
        feedback = (f"\n\nПРОШЛЫЙ ВАРИАНТ НЕ ПРОШЁЛ ЧЕКЕРЫ: {fails}\n"
                    f"Перепиши с учётом этого.")
        print(f"[writer] круг {rnd + 1}: чекеры не прошли ({fails}), доработка…")
    return script, checks


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", required=True)
    ap.add_argument("--route", default="")
    ap.add_argument("--no-product", action="store_true")
    ap.add_argument("--card", action="store_true")
    args = ap.parse_args()

    script, checks = await write_script(args.topic, args.route, args.no_product)
    if not script:
        print("[writer] СБОЙ: сценарий не сгенерирован")
        sys.exit(1)
    print("=" * 60)
    print("ХУК:", script.get("hook"))
    for s in script.get("segments", []):
        print("\n" + s.get("text", ""))
    print("=" * 60)
    print("Маршрут:", script.get("route_used"), "| Дуга:", script.get("arc"))
    print("Чекеры:", json.dumps({k: v["note"] for k, v in checks.items()
                                 if isinstance(v, dict)}, ensure_ascii=False, indent=1))
    if not checks["ok"]:
        print("[writer] ВНИМАНИЕ: чекеры не прошли после 2 кругов — карточку не создаю")
        sys.exit(2)

    # журнал анти-повтора
    journal = _load_journal()
    journal.append({"ts": datetime.utcnow().isoformat()[:16],
                    "route": script.get("route_used", ""),
                    "title": script.get("title", ""), "topic": args.topic[:100]})
    JOURNAL.parent.mkdir(exist_ok=True)
    tmp = JOURNAL.with_suffix(".tmp")
    tmp.write_text(json.dumps(journal, ensure_ascii=False, indent=1))
    tmp.replace(JOURNAL)

    if args.card:
        from app.db import AsyncSessionLocal
        from app.models.story_video import StoryVideo
        async with AsyncSessionLocal() as db:
            sv = StoryVideo(
                title=f"Смысловое: {script.get('title', args.topic[:50])}",
                brand="kz", status="script",
                script_json={"type": "meaning", "hook": script.get("hook"),
                             "segments": script.get("segments"),
                             "route": script.get("route_used"),
                             "no_product": args.no_product},
                facts_md=("**Смысловое видео** (карта мостов)\n\n"
                          f"- Маршрут: {script.get('route_used')}\n"
                          f"- Дуга: {script.get('arc')}\n"
                          f"- Чекеры: прямолинейность {checks['directness']['note']}; "
                          f"кивабельность {checks['nod']['note']}; "
                          f"стиль {checks['style']['note']}\n"))
            db.add(sv)
            await db.commit()
            await db.refresh(sv)
            print(f"[writer] карточка #{sv.id} создана (⏸ на твоём апруве)")


asyncio.run(main())
