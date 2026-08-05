#!/usr/bin/env python3
"""Скаут трендов: парсинг пула источников → судья-классификатор → карточки-идеи.

Автономная версия слоя поиска тем (в проде у нас он живёт внутри автопилота
с Postgres; здесь всё на файлах, чтобы система работала из коробки).

Флоу одного прогона:
  1. sources.json — твой пул Instagram-аккаунтов (собираешь один раз под нишу).
  2. Apify (actor apify/instagram-scraper) забирает свежие посты аккаунтов.
     Ключи — пулом APIFY_API_TOKENS=k1,k2,... с ротацией: упёрся в месячный
     лимит — ключ помечается exhausted, берём следующий.
  3. Дедуп: seen.json по url поста — один пост классифицируем один раз.
  4. Судья: Claude CLI оценивает каждый пост по чек-ядру виральности
     (герой + мостик к твоей теме + пересказываемый факт + «наши»).
  5. Кандидаты → карточки-идеи: ideas/idea_*.json + сводка ideas/INBOX.md.
     Дальше человек выбирает карточку и запускает производство:
     python scripts/meaning_writer.py --topic "<тема из карточки>"

Запуск:  python scripts/trend_scout.py [--limit-posts 10] [--max-cost 0.5]
         [--accounts acc1,acc2] [--dry-run]
Крон (ежедневно утром):  45 8 * * *  cd <репо> && .venv/bin/python scripts/trend_scout.py

Судья по умолчанию заточен под Айплюс (образование, Казахстан) — это рабочий
пример. Под свою нишу перепиши docs/brand_profile.md (см. docs/trend_scouting.md).
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.environ.get("TREND_SCOUT_STATE", str(Path.home() / ".trend-scout")))
IDEAS_DIR = REPO / "ideas"
SOURCES_PATH = REPO / "sources.json"
BRAND_PROFILE_PATH = REPO / "docs" / "brand_profile.md"

APIFY_BASE = "https://api.apify.com/v2"
APIFY_ACTOR = os.environ.get("APIFY_IG_ACTOR", "apify/instagram-scraper")
COST_PER_POST = 0.0027          # $ за пост у instagram-scraper (Pay per result)
CLAUDE_MODEL = os.environ.get("TREND_SCOUT_MODEL", "sonnet")
MAX_CLASSIFY_PER_RUN = int(os.environ.get("TREND_SCOUT_MAX_CLASSIFY", "40"))
MIN_CONFIDENCE = int(os.environ.get("TREND_SCOUT_MIN_CONFIDENCE", "6"))

# ── Судья: чек-ядро виральности. {brand_profile} подставляется из
# docs/brand_profile.md — там описание ТВОЕГО бренда, аудитории и эталонов. ──
CLASSIFY_PROMPT = """Ты отбираешь темы для коротких вертикальных видео бренда.

{brand_profile}

ЧЕК-ЯДРО (все 4 пункта обязательны для candidate=true):
1. ГЕРОЙ — конкретный человек или маленькая команда (НЕ компания, НЕ министерство).
2. МОСТИК К БРЕНДУ — героя можно честно связать с темой бренда (см. профиль выше).
   Нет мостика — candidate=false, каким бы вирусным ни был пост.
3. ПЕРЕСКАЗЫВАЕМЫЙ ФАКТ — цифра/рекорд/«первый», который зритель перескажет
   за ужином («стартап дороже миллиарда», «золото мировой олимпиады»).
4. «НАШИ» — герой свой для аудитории (земляк, ровесник ребёнка, «такой же как мы»),
   повод для гордости или узнавания.

Плюс (не обязательно, повышает confidence): есть о чём спорить в комментариях.

СПИСОК УЖЕ ВЗЯТЫХ ТЕМ (если герой совпадает — duplicate=true):
{existing}

КОНТЕНТ ДЛЯ ОЦЕНКИ:
{content}

Верни СТРОГО JSON без markdown:
{{"candidate": true/false, "duplicate": true/false, "confidence": 0-10,
"hero": "имя героя", "bridge": "мостик к бренду", "fact": "пересказываемый факт",
"title": "короткое название карточки (герой + суть)", "why": "1 фраза почему да/нет"}}"""

DEFAULT_BRAND_PROFILE = """ПРОФИЛЬ БРЕНДА (пример — Айплюс, образовательный центр, Казахстан):
Готовим школьников 4-6 классов к поступлению в сильные школы (НИШ/РФМШ/БИЛ/КТЛ).
Аудитория — родители. Мостик к бренду = «школа/образование дали герою старт».
Эталоны вышедших роликов: «Волож и Сегалович познакомились в РФМШ и создали
Яндекс» (273К просмотров), «школьницы из НИШ создали браслет, спасающий тонущих»,
«школьник Алматы взял золото мировой олимпиады по физике»."""


# ═══════════════════ Apify: пул ключей с ротацией ═══════════════════

def _all_keys():
    keys = []
    for k in os.environ.get("APIFY_API_TOKENS", "").split(","):
        k = k.strip()
        if k and k not in keys:
            keys.append(k)
    single = os.environ.get("APIFY_API_TOKEN", "").strip()
    if single and single not in keys:
        keys.append(single)
    return keys


def _keys_state():
    p = STATE_DIR / "apify_state.json"
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def _mark_exhausted(key):
    st = _keys_state()
    st[key[:16]] = {"exhausted_at": time.strftime("%Y-%m-%d")}
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    (STATE_DIR / "apify_state.json").write_text(json.dumps(st, indent=1))


def _ordered_keys():
    """Живые ключи вперёд; помеченные exhausted в этом месяце — в хвост
    (лимиты Apify месячные, с новым месяцем ключ оживает)."""
    st = _keys_state()
    month = time.strftime("%Y-%m")
    alive, dead = [], []
    for k in _all_keys():
        mark = st.get(k[:16], {}).get("exhausted_at", "")
        (dead if mark.startswith(month) else alive).append(k)
    return alive + dead


def _is_limit_error(status, text):
    """Месячный лимит/кредит кончился (ключ выжигаем). 429 — просто троттл."""
    if status in (402, 403):
        return True
    t = (text or "").lower()
    return any(m in t for m in (
        "monthly usage", "usage limit", "monthly limit", "hard limit", "exceeded the"))


def run_actor(payload, timeout=240):
    """Запуск актора с ротацией ключей. Возвращает список item'ов или None."""
    keys = _ordered_keys()
    if not keys:
        print("Apify: нет ключей — заполни APIFY_API_TOKENS в .env")
        return None
    actor = APIFY_ACTOR.replace("/", "~")
    last_err = ""
    for key in keys:
        try:
            r = requests.post(
                f"{APIFY_BASE}/acts/{actor}/run-sync-get-dataset-items",
                params={"token": key}, json=payload, timeout=timeout)
        except requests.RequestException as e:
            last_err = str(e)
            continue
        if r.status_code == 429:
            last_err = "429 rate-limit"
            continue                      # троттл — ключ не выжигаем, пробуем другой
        if _is_limit_error(r.status_code, r.text):
            _mark_exhausted(key)
            last_err = f"{r.status_code} limit"
            continue
        if r.ok:
            try:
                return r.json()
            except ValueError:
                last_err = "bad json"
                continue
        last_err = f"{r.status_code}"
    print(f"Apify: все ключи исчерпаны/недоступны (последняя ошибка: {last_err})")
    return None


def scrape_account(username, limit):
    """Свежие посты одного аккаунта → [{url, caption, likes, comments, account}]."""
    payload = {
        "directUrls": [f"https://www.instagram.com/{username}/"],
        "resultsType": "posts",
        "resultsLimit": max(1, min(limit, 30)),
        "addParentData": False,
    }
    items = run_actor(payload)
    posts = []
    for it in items or []:
        url = it.get("url") or ""
        cap = (it.get("caption") or "").strip()
        if not url or not cap:
            continue
        posts.append({
            "url": url, "caption": cap, "account": username,
            "likes": it.get("likesCount") or 0,
            "comments": it.get("commentsCount") or 0,
            "ts": it.get("timestamp") or "",
        })
    return posts


# ═══════════════════ Судья (Claude CLI) ═══════════════════

def _parse_json(s):
    if "```" in s:
        s = s.split("```")[1]
        if s.startswith("json"):
            s = s[4:]
    i, j = s.find("{"), s.rfind("}")
    if i != -1 and j > i:
        s = s[i:j + 1]
    return json.loads(s)


def classify(content, existing_titles, brand_profile):
    """Вердикт судьи по посту. None = не удалось распарсить (fail-closed)."""
    prompt = CLASSIFY_PROMPT.format(
        brand_profile=brand_profile,
        existing="\n".join(f"- {t}" for t in existing_titles) or "- (пусто)",
        content=content[:3000])
    for attempt in range(2):
        p = prompt if attempt == 0 else prompt + "\n\nВАЖНО: СТРОГО валидный JSON."
        try:
            out = subprocess.run(
                ["claude", "-p", p, "--model", CLAUDE_MODEL],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                universal_newlines=True, timeout=180)
        except (OSError, subprocess.TimeoutExpired) as e:
            print(f"  судья: claude CLI недоступен ({e})")
            return None
        try:
            return _parse_json(out.stdout)
        except (json.JSONDecodeError, IndexError):
            continue
    return None


# ═══════════════════ Карточки-идеи ═══════════════════

def existing_titles():
    titles = []
    for p in sorted(IDEAS_DIR.glob("idea_*.json")):
        try:
            titles.append(json.loads(p.read_text())["title"])
        except Exception:
            pass
    return titles


def save_card(verdict, post):
    IDEAS_DIR.mkdir(exist_ok=True)
    n = len(list(IDEAS_DIR.glob("idea_*.json"))) + 1
    card = {
        "title": verdict.get("title", "без названия"),
        "hero": verdict.get("hero", ""),
        "bridge": verdict.get("bridge", ""),
        "fact": verdict.get("fact", ""),
        "confidence": verdict.get("confidence", 0),
        "why": verdict.get("why", ""),
        "source_url": post["url"],
        "source_account": post["account"],
        "source_caption": post["caption"][:1500],
        "status": "idea",
    }
    (IDEAS_DIR / f"idea_{n:03d}.json").write_text(
        json.dumps(card, ensure_ascii=False, indent=2))
    with open(IDEAS_DIR / "INBOX.md", "a") as f:
        f.write(f"\n## {n:03d}. {card['title']} (уверенность {card['confidence']}/10)\n"
                f"- Герой: {card['hero']}\n- Мостик: {card['bridge']}\n"
                f"- Факт: {card['fact']}\n- Источник: {card['source_url']}\n")
    return n


# ═══════════════════ Прогон ═══════════════════

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit-posts", type=int, default=10,
                    help="постов с одного аккаунта за прогон (1-30)")
    ap.add_argument("--accounts", type=str, default="",
                    help="только эти аккаунты (через запятую)")
    ap.add_argument("--max-cost", type=float, default=1.0,
                    help="потолок стоимости прогона в $ (защита от лавины)")
    ap.add_argument("--dry-run", action="store_true",
                    help="скрейп и судья без записи карточек")
    args = ap.parse_args()

    try:
        sources = json.loads(SOURCES_PATH.read_text())
    except FileNotFoundError:
        print("Нет sources.json — скопируй sources.example.json и заполни свой пул")
        sys.exit(1)
    ig = sources.get("instagram") or []
    accounts = [a["username"] if isinstance(a, dict) else a for a in ig]
    if args.accounts:
        want = {x.strip() for x in args.accounts.split(",") if x.strip()}
        accounts = [a for a in accounts if a in want]
    if not accounts:
        print("Пул instagram-аккаунтов пуст")
        sys.exit(1)

    # ЦЕНА ДО ЗАПУСКА (правило: сначала посчитай, потом жги)
    planned = len(accounts) * args.limit_posts
    cost = planned * COST_PER_POST
    print(f"План: {len(accounts)} аккаунтов × {args.limit_posts} постов = "
          f"{planned} постов ≈ ${cost:.2f}")
    if cost > args.max_cost:
        print(f"Стоп: дороже потолка --max-cost {args.max_cost}. "
              f"Уменьши пул/лимит или подними потолок.")
        sys.exit(1)

    brand_profile = DEFAULT_BRAND_PROFILE
    if BRAND_PROFILE_PATH.exists():
        brand_profile = BRAND_PROFILE_PATH.read_text().strip()

    seen_path = STATE_DIR / "seen.json"
    try:
        seen = json.loads(seen_path.read_text())
    except Exception:
        seen = {}

    titles = existing_titles()
    classified = created = 0
    for acc in accounts:
        posts = scrape_account(acc, args.limit_posts)
        print(f"@{acc}: {len(posts)} постов")
        for post in posts:
            if post["url"] in seen:
                continue
            seen[post["url"]] = time.strftime("%Y-%m-%d")
            if classified >= MAX_CLASSIFY_PER_RUN:
                continue
            classified += 1
            v = classify(f"{post['caption']}\n\n(лайки {post['likes']}, "
                         f"комменты {post['comments']}, @{post['account']})",
                         titles, brand_profile)
            if not v:
                continue
            mark = "✅" if v.get("candidate") else "—"
            if v.get("duplicate"):
                mark = "♻️ dupl"
            print(f"  {mark} {v.get('title','?')} ({v.get('confidence',0)}/10): "
                  f"{v.get('why','')}")
            if (v.get("candidate") and not v.get("duplicate")
                    and int(v.get("confidence") or 0) >= MIN_CONFIDENCE
                    and not args.dry_run):
                save_card(v, post)
                titles.append(v.get("title", ""))
                created += 1

    if not args.dry_run:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = seen_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(seen, ensure_ascii=False, indent=0))
        tmp.replace(seen_path)
    print(f"\nИтог: просмотрено {classified} новых постов, карточек создано: {created}"
          f"{' (dry-run)' if args.dry_run else ''}. Смотри ideas/INBOX.md")


if __name__ == "__main__":
    main()
