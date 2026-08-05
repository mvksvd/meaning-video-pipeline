#!/usr/bin/env python3
"""Ядро детекта сторивидео-кандидатов (Фаза 2 вкладки, 03.08).

Общее для story_scout.py (свежие тренды) и archive_hunter.py (вечнозелёные):
классификатор «герой + школьный мостик + пересказываемый факт» и заведение
карточки-идеи во вкладку Сторивидео. БЕЗ module-level asyncio.run — модуль
только импортируется (урок 05.07 про дубли публикаций).
"""
import json
import sys

sys.path.insert(0, "/home/MaksVideo/aiplus-content-factory/backend/src")

import os

STORY_SCOUT_MODEL = os.environ.get("STORY_SCOUT_MODEL", "sonnet")
MAX_CARDS_PER_RUN = int(os.environ.get("STORY_SCOUT_MAX_CARDS", "3"))

# Ядро виральности — из разбора Яндекса (273К) и A/B Higgsfield (×15):
# наши герои + школьный мостик + пересказываемый факт + есть о чём спорить.
_CLASSIFY_PROMPT = """Ты отбираешь темы для вертикальных сторивидео образовательного центра Айплюс
(Казахстан, подготовка к НИШ/РФМШ/БИЛ/КТЛ). Формат — история героя на 45-60 секунд.

Эталоны уже вышедших роликов (наш золотой стандарт):
- Волож и Сегалович создали Яндекс — познакомились в РФМШ (273К просмотров)
- Школьник Алматы взял золото мировой олимпиады по физике
- Основатель Kaspi Вячеслав Ким учился в РФМШ
- Школьницы из НИШ создали браслет, спасающий тонущих
- Девушка из Актау поступила в Оксфорд

ЧЕК-ЯДРО (все 4 обязательны для candidate=true):
1. ГЕРОЙ — конкретный человек или маленькая команда (НЕ компания, НЕ министерство).
2. ШКОЛЬНЫЙ МОСТИК — герой школьник СЕЙЧАС или связан с казахстанской школой:
   НИШ/РФМШ/БИЛ/КТЛ/НЗМ/лицей/обычная школа. Мостик к теме «школа дала старт».
   Без мостика (взрослый бизнесмен без школьной истории) — candidate=false.
3. ПЕРЕСКАЗЫВАЕМЫЙ ФАКТ — цифра/рекорд/«первый», который зритель перескажет
   за ужином («стартап дороже миллиарда», «золото мировой олимпиады»).
4. «НАШИ» — казахстанец/казахстанка, повод для гордости.

Плюс (не обязательно, повышает confidence): есть о чём спорить в комментах.

СПИСОК УЖЕ СДЕЛАННЫХ/ВЗЯТЫХ ТЕМ (если герой совпадает — duplicate=true):
{existing}

КОНТЕНТ ДЛЯ ОЦЕНКИ:
{content}

Верни СТРОГО JSON без markdown:
{{"candidate": true/false, "duplicate": true/false, "confidence": 0-10,
"hero": "имя героя", "school": "школа/мостик", "fact": "пересказываемый факт",
"title": "короткое название карточки (герой + суть)", "why": "1 фраза почему да/нет"}}"""


def _parse_json(s: str):
    """Снять markdown-обёртку и вытащить JSON-объект (паттерн claude_svc)."""
    if "```" in s:
        s = s.split("```")[1]
        if s.startswith("json"):
            s = s[4:]
    i, j = s.find("{"), s.rfind("}")
    if i != -1 and j > i:
        s = s[i:j + 1]
    return json.loads(s)


async def classify_story(content: str, existing_titles: list[str]) -> dict | None:
    """Классификатор кандидата. None = не удалось распарсить (fail-closed)."""
    from app.services.claude_svc import _run_claude

    prompt = _CLASSIFY_PROMPT.format(
        existing="\n".join(f"- {t}" for t in existing_titles) or "- (пусто)",
        content=content[:3000])
    for attempt in range(2):
        raw = await _run_claude(
            prompt if attempt == 0 else prompt + "\n\nВАЖНО: СТРОГО валидный JSON.",
            model=STORY_SCOUT_MODEL)
        try:
            return _parse_json(raw)
        except (json.JSONDecodeError, IndexError):
            continue
    return None


async def existing_story_titles(db) -> list[str]:
    """Заголовки всех карточек вкладки — для дедупа по герою."""
    from sqlalchemy import select

    from app.models.story_video import StoryVideo
    rows = (await db.execute(select(StoryVideo.title))).scalars().all()
    return list(rows)


async def create_idea_card(db, verdict: dict, source_note: str) -> int:
    """Заводит карточку-идею (status=idea). Возвращает id."""
    from app.models.story_video import StoryVideo

    facts = (f"**Идея от автопилота** (детектор «герой + школьный мостик»)\n\n"
             f"- Герой: {verdict.get('hero', '?')}\n"
             f"- Школьный мостик: {verdict.get('school', '?')}\n"
             f"- Пересказываемый факт: {verdict.get('fact', '?')}\n"
             f"- Уверенность: {verdict.get('confidence', '?')}/10 — {verdict.get('why', '')}\n"
             f"- Источник: {source_note}\n")
    sv = StoryVideo(title=f"Идея: {verdict.get('title', 'без названия')}",
                    brand="kz", status="idea", facts_md=facts)
    db.add(sv)
    await db.flush()
    return sv.id
