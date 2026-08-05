#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""НОЧНОЙ ЗАВОД смысловых видео (04.08): владелец днём апрувит тексты во вкладке
(status=voice), вечером крон прогоняет карточки до готового ролика (status=review).

Конвейер на карточку: TTS Сергей (акуты+паузы+1.08) → тайминги фраз (Gemini,
рамка длительности) → раскадровка (opus по нуар-формуле и словарю метафор) →
кадры (Higgsfield nano_banana, фолбэк gpt_image_2) → анимации (kling3_0_turbo,
фолбэк kling3_0) → сборка (вспышки на звеньях, нижние сабы, ГРАНТ золотом,
трек формата с дропа, 0.16) → joint_check → review.

Предохранители: hf_credits_ok, максимум 2 карточки/ночь, смета в лог,
real-футажей нет (полный нуар), постинга нет — только до review.
Запуск: cd ~/aiplus-content-factory && set -a; . ./.env; set +a && \
backend/.venv/bin/python ~/meaning_factory.py [--limit 2] [--card ID]
"""
import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, "/home/MaksVideo/aiplus-content-factory/backend/src")

H = Path.home()
PF = H / "aiplus-content-factory/public_frames"
WORK = H / "meaning_factory_work"
WORK.mkdir(exist_ok=True)
SERGEY = "XuEV9VY3VUASYgJVNBh0"
TRACK = H / "music_library/Blade_Runner_2049_-_Synthwave_Goose.mp3"
TRACK_SS = 50.9
VOL = 0.16
CTA_CARD = PF / "story_assets/cta_grant_card.png"
W, HGT, FPS = 1080, 1920, 30
MAX_CARDS = 2

# Стиль утверждён владельцем 05.08 (вместо нуара — «вышло мрачно»):
# пластилиновый стоп-моушен для сцен + песочная анимация для абстракций.
# Формула вставляется в КАЖДЫЙ промпт байт-в-байт — это весь механизм
# консистентности стиля (как раньше нуар-формула).
CLAY = ("Claymation stop-motion animation style, handmade plasticine characters "
        "and props with visible fingerprints and clay texture, miniature "
        "handcrafted set, warm soft studio lighting, rich natural colors, "
        "charming handmade film feel, no text, no watermarks")
SAND = ("Sand animation style: backlit golden sand on a glass surface, glowing "
        "warm amber monochrome, soft glow, expressive hand-drawn sand strokes, "
        "no text, no watermarks")
NOIR = CLAY  # легаси-алиас: старые вызовы получают новую формулу

SHOTLIST_PROMPT = """Ты арт-директор смысловых вертикальных видео Айплюс. Формат:
ПЛАСТИЛИНОВЫЙ СТОП-МОУШЕН (сцены с персонажами) + ПЕСОЧНАЯ АНИМАЦИЯ (абстракции).
Ниже фразы озвучки с таймингами. Разбей ролик на 14-20 планов.

ПРАВИЛА (нарушение = брак):
1. План живёт 2-6 секунд (границы планов = границы фраз, стык в стык).
2. Каждый план — ОДИН кадр: image_prompt на английском, конкретная сцена
   (композиция, свет). Персонажи — пластилиновые человечки с ВЫРАЗИТЕЛЬНЫМИ
   эмоциями (лица разрешены и нужны — это кукольный стиль, не реализм).
   Семья казахская, современный Казахстан 2026: никаких ковров на стенах
   и советской мебели. Стиль-формулу НЕ пиши — её добавит код.
3. motion_prompt: ОДИН жест + камера (одно движение или static), по-английски,
   движение лёгкое кукольное (стоп-моушен, не плавная камера-долли).
4. Приёмы: ~30% метафоры-абстракции — их помечай "sand": true (рендерятся
   ЗОЛОТЫМ ПЕСКОМ на стекле: расходящиеся дорожки=выбор, гора=цель, весы,
   растущее дерево=рост, песочные часы=время); ~40% прямые пластилиновые
   сцены; ~25% атмосфера (миниатюрные среды: класс, кухня, зал).
5. flash=true на планах, ЗАВЕРШАЮЩИХ смысловое звено (3-5 вспышек на ролик).
6. Сквозной объект: предмет из хука возвращается ближе к финалу (закольцовка).
7. Последний план = CTA (кадры не нужны): "cta": true, без промптов.
8. Соседние планы — разная крупность (крупный/средний/общий чередуй).

ФРАЗЫ:
{phrases}

Верни СТРОГО JSON:
{{"shots": [{{"from": 0, "to": 1, "image_prompt": "...", "motion_prompt": "...",
"flash": false, "sand": false, "cta": false}}]}}
where from/to — индексы первой и последней фразы плана."""


def run(cmd, timeout=1800):
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       universal_newlines=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"CMD FAIL: {' '.join(map(str, cmd))}\n{r.stderr[-800:]}")
    return r.stdout


def dur_of(p):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                          "format=duration", "-of", "csv=p=0", str(p)],
                         stdout=subprocess.PIPE, universal_newlines=True).stdout
    return float(out.strip() or 0)


def strip_md(t):
    t = (t or "").strip()
    if t.startswith("```"):
        t = t.split("```")[1]
        if t.startswith("json"):
            t = t[4:]
    i, j = t.find("{"), t.rfind("}")
    return t[i:j + 1] if i != -1 and j > i else t


# ── 1. Озвучка Сергеем ────────────────────────────────────────────────────────
def apply_pronun(text):
    try:
        d = json.loads((H / ".aiplus-factory/tts_pronun.json").read_text())
    except Exception:
        d = {}
    for k, v in d.items():
        text = text.replace(k, v)
    text = text.replace("где все в телефонах", "где все́ в телефонах")
    return text


def tts_sergey(card_id, script):
    segs = [script.get("hook", "")] + [s.get("text", "") for s in
                                       script.get("segments", [])]
    br = ' <break time="0.6s" /> '
    text = apply_pronun(br.join(s.strip() for s in segs if s.strip()))
    body = json.dumps({"text": text, "model_id": "eleven_multilingual_v2",
                       "voice_settings": {"stability": 0.75, "similarity_boost": 0.75,
                                          "style": 0.0, "use_speaker_boost": True}}
                      ).encode()
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{SERGEY}?output_format=mp3_44100_128",
        data=body, headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"],
                            "Content-Type": "application/json"})
    raw = WORK / f"card{card_id}_voice_raw.mp3"
    with urllib.request.urlopen(req, timeout=300) as r:
        raw.write_bytes(r.read())
    voice = WORK / f"card{card_id}_voice.mp3"
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw),
         "-filter:a", "atempo=1.08", str(voice)])
    return voice


# ── 2. Тайминги фраз (Gemini с рамкой) ────────────────────────────────────────
async def phrase_times(voice):
    from app.services import gemini_svc
    from google.genai import types

    dur = dur_of(voice)
    prompt = (f"Аудио длится РОВНО {dur:.1f} секунды. Транскрибируй дословно русскую "
              f"озвучку с таймингами по фразам (2-8 слов). НИ ОДИН тайминг не может "
              f"превышать {dur:.1f}. Последняя фраза заканчивается около {dur - 1:.0f}. "
              'Верни СТРОГО JSON: {"phrases":[{"start":0.0,"end":2.0,"text":"..."}]}')
    parts = [types.Part.from_bytes(data=Path(voice).read_bytes(), mime_type="audio/mp3"),
             types.Part.from_text(text=prompt)]
    for _ in range(3):
        resp = await gemini_svc._generate_with_retry(
            model="gemini-2.5-pro",
            contents=types.Content(parts=parts, role="user"),
            config=types.GenerateContentConfig(response_mime_type="application/json",
                                               temperature=0))
        try:
            ph = json.loads(strip_md(resp.text))["phrases"]
        except Exception:
            continue
        if ph and dur - 6 <= ph[-1]["end"] <= dur + 0.6:
            return ph
    raise RuntimeError("тайминги фраз: Gemini не уложился в рамку за 3 попытки")


# ── 3. Раскадровка (opus) ─────────────────────────────────────────────────────
async def shotlist(phrases):
    from app.services.claude_svc import _run_claude

    ptxt = "\n".join(f"{i}: [{p['start']:.1f}-{p['end']:.1f}] {p['text']}"
                     for i, p in enumerate(phrases))
    for attempt in range(2):
        raw = await _run_claude(SHOTLIST_PROMPT.format(phrases=ptxt))
        try:
            shots = json.loads(strip_md(raw))["shots"]
        except Exception:
            continue
        if 8 <= len(shots) <= 24 and shots[-1].get("cta"):
            return shots
    raise RuntimeError("раскадровка: opus не дал валидный shot-list")


# ── 4. Higgsfield: кадр + анимация ────────────────────────────────────────────
def _hf(args, timeout):
    bin_path = os.environ.get("HIGGSFIELD_BIN",
                              str(H / ".nvm/versions/node/v20.20.2/bin/higgsfield"))
    env = {**os.environ,
           "PATH": f"{H}/.nvm/versions/node/v20.20.2/bin:" + os.environ.get("PATH", "")}
    out = subprocess.run([bin_path, *args, "--wait", "--json"], stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, universal_newlines=True,
                         timeout=timeout, env=env)
    if out.returncode != 0:
        print(f"  hf rc={out.returncode}: {(out.stderr or '')[:150]}", flush=True)
        return None
    try:
        data = json.loads(out.stdout)
        return (data[0] if isinstance(data, list) else data).get("result_url")
    except Exception:
        return None


def dl(url, dst):
    with urllib.request.urlopen(url, timeout=180) as r:
        Path(dst).write_bytes(r.read())


def gen_shot(card_id, i, shot, need):
    img = WORK / f"card{card_id}_s{i:02d}.png"
    vid = WORK / f"card{card_id}_s{i:02d}.mp4"
    if vid.exists() and vid.stat().st_size > 200_000:
        return vid  # кеш пересборки
    prompt = shot["image_prompt"].rstrip(". ") + ". " + (
        SAND if shot.get("sand") else CLAY)
    url = None
    for model, extra in (("nano_banana", []),
                         ("gpt_image_2", ["--resolution", "1k", "--quality", "medium"])):
        url = _hf(["generate", "create", model, "--prompt", prompt,
                   "--aspect_ratio", "9:16", *extra], 600)
        if url:
            break
    if not url:
        raise RuntimeError(f"план {i}: кадр не сгенерился")
    dl(url, img)
    d = str(min(6, max(3, int(need) + 1)))
    if shot.get("sand"):
        motion = ("Keep the exact sand animation style of the image, golden backlit "
                  "sand on glass, the sand slowly flows and redraws itself. "
                  + shot["motion_prompt"])
    else:
        motion = ("Keep the exact claymation stop-motion style of the image, same "
                  "clay textures and colors, slightly jerky handmade stop-motion "
                  "movement. " + shot["motion_prompt"])
    vurl = None
    # Схемы моделей РАЗОШЛИСЬ (05.08): kling3_0_turbo больше НЕ принимает
    # mode/sound (падал "Unknown params" → молчаливый фолбэк на дорогой
    # kling3_0, 9 кр вместо 4.5-7.5). У kling3_0 sound/mode остались —
    # там sound=off обязателен (звук = лишние кредиты).
    for model in ("kling3_0_turbo", "kling3_0"):
        args = ["generate", "create", model, "--prompt", motion,
                "--aspect_ratio", "9:16", "--duration", d,
                "--start-image", str(img)]
        if model == "kling3_0":
            args += ["--mode", "std", "--sound", "off"]
        vurl = _hf(args, 1200)
        if vurl:
            break
    if not vurl:
        raise RuntimeError(f"план {i}: анимация не сгенерилась")
    dl(vurl, vid)
    return vid


# ── 5. Сборка ─────────────────────────────────────────────────────────────────
VF_FIT = (f"scale={W}:{HGT}:force_original_aspect_ratio=increase,"
          f"crop={W}:{HGT},fps={FPS},format=yuv420p")


def ts(t):
    mm, ss = divmod(t, 60)
    return f"0:{int(mm):02d}:{ss:05.2f}"


def assemble(card_id, shots, phrases, clips, voice, out_path):
    tmp = WORK / f"card{card_id}_build"
    tmp.mkdir(exist_ok=True)
    total_end = phrases[-1]["end"] + 0.7
    bounds, plan = [], []
    for i, sh in enumerate(shots):
        s = phrases[sh["from"]]["start"] if i else 0.0
        nxt = shots[i + 1] if i + 1 < len(shots) else None
        e = phrases[nxt["from"]]["start"] if nxt else total_end
        plan.append((round(s, 2), round(e, 2), sh))
    pieces = []
    for i, (s, e, sh) in enumerate(plan):
        need = round(e - s, 2)
        seg = tmp / f"seg{i:02d}.mp4"
        if sh.get("cta"):
            run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-t", str(need),
                 "-i", str(CTA_CARD), "-vf", VF_FIT, "-r", str(FPS), "-an", str(seg)])
        else:
            src = clips[i]
            d = dur_of(src)
            vf = VF_FIT
            if d < need:  # ИИ-анимация: тянуть можно (почти статика)
                vf = f"setpts={need / d + 0.02:.3f}*PTS," + VF_FIT
            run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
                 "-vf", vf, "-t", str(need), "-an", str(seg)])
        if sh.get("flash"):
            d2 = dur_of(seg)
            fl = tmp / f"seg{i:02d}f.mp4"
            run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(seg), "-vf",
                 f"negate=enable='gte(t,{max(0, d2 - 0.12):.2f})',format=yuv420p",
                 "-an", str(fl)])
            seg = fl
        pieces.append(seg)
    lst = tmp / "list.txt"
    lst.write_text("".join(f"file '{p}'\n" for p in pieces))
    nosub = tmp / "nosub.mp4"
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
         "-i", str(lst), "-c:v", "libx264", "-preset", "medium", "-crf", "19",
         "-pix_fmt", "yuv420p", str(nosub)])
    ass = ["[Script Info]", f"PlayResX: {W}", f"PlayResY: {HGT}", "", "[V4+ Styles]",
           "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, "
           "BackColour, Bold, Outline, Shadow, Alignment, MarginL, MarginR, "
           "MarginV, BorderStyle",
           "Style: sub,DejaVu Sans,72,&H00FFFFFF,&H00000000,&H90000000,-1,3,0,2,"
           "60,60,260,1", "", "[Events]",
           "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
           "Effect, Text"]
    for p in phrases:
        txt = p["text"].replace("A+", "Айплюс").replace("I+", "Айплюс")
        txt = re.sub(r"грант", "ГРАНТ", txt, flags=re.I)
        txt = txt.replace("ГРАНТ", "{\\c&H00D6FF&}ГРАНТ{\\c&HFFFFFF&}")
        ass.append(f"Dialogue: 0,{ts(p['start'])},{ts(p['end'])},sub,,0,0,0,,{txt}")
    (tmp / "subs.ass").write_text("\n".join(ass))
    withsubs = tmp / "subs.mp4"
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(nosub),
         "-vf", f"ass={tmp}/subs.ass", "-c:v", "libx264", "-preset", "medium",
         "-crf", "19", str(withsubs)])
    total = dur_of(withsubs)
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(withsubs), "-i", str(voice),
         "-stream_loop", "-1", "-ss", str(TRACK_SS), "-i", str(TRACK),
         "-filter_complex",
         f"[2:a]volume={VOL},atrim=0:{total},afade=t=out:st={total - 2:.1f}:d=2[m];"
         f"[1:a][m]amix=inputs=2:duration=first:dropout_transition=0[a]",
         "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
         "-t", str(total), str(out_path)])
    json.dump([{"i": i, "src": f"shot{i}", "start": s, "end": e,
                "dur": round(e - s, 2)} for i, (s, e, _) in enumerate(plan)],
              open(str(out_path) + ".shots.json", "w"))
    return plan


# ── 6. Главный цикл ───────────────────────────────────────────────────────────
async def process_card(db, sv):
    from sqlalchemy import text as _t
    cid = sv["id"]
    script = sv["script_json"]
    print(f"=== карточка #{cid}: {sv['title']} ===", flush=True)
    voice = tts_sergey(cid, script)
    print(f"  озвучка {dur_of(voice):.0f}с", flush=True)
    phrases = await phrase_times(voice)
    print(f"  фраз: {len(phrases)}", flush=True)
    shots = await shotlist(phrases)
    gen_shots = [s for s in shots if not s.get("cta")]
    est = len(gen_shots) * (1 + 6)
    print(f"  планов: {len(shots)} (генераций {len(gen_shots)}, ~{est} кр)", flush=True)
    clips = {}
    from concurrent.futures import ThreadPoolExecutor
    tasks = []
    for i, sh in enumerate(shots):
        if sh.get("cta"):
            continue
        e = (phrases[shots[i + 1]["from"]]["start"] if i + 1 < len(shots)
             else phrases[-1]["end"])
        st = phrases[sh["from"]]["start"] if i else 0.0
        tasks.append((i, sh, e - st))
    with ThreadPoolExecutor(max_workers=4) as ex:  # параллельный монтаж (правка 04.08)
        futs = {ex.submit(gen_shot, cid, i, sh, need): i for i, sh, need in tasks}
        for f, i in futs.items():
            clips[i] = f.result()
            print(f"  план {i}: ok", flush=True)
    out = PF / f"meaning_card{cid}.mp4"
    assemble(cid, shots, phrases, clips, voice, out)
    chk = subprocess.run(
        [str(H / "aiplus-content-factory/backend/.venv/bin/python"),
         str(H / "joint_check.py"), str(out)], stdout=subprocess.PIPE,
        universal_newlines=True).stdout.strip().splitlines()
    note = chk[-1] if chk else "?"
    print(f"  сборка: {out.name} ({dur_of(out):.0f}с); joint: {note}", flush=True)
    await db.execute(_t(
        "UPDATE story_videos SET status='review', video_path=:v, "
        "checks_json=:c WHERE id=:i"),
        {"v": str(out), "c": json.dumps({"joint": note, "shots": len(shots)}),
         "i": cid})
    await db.commit()


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=MAX_CARDS)
    ap.add_argument("--card", type=int, default=0)
    args = ap.parse_args()

    from sqlalchemy import text as _t

    from app.db import AsyncSessionLocal
    from app.services.image_gen import hf_credits_ok
    if not hf_credits_ok("ночной завод смысловых"):
        print("СТОП: мало кредитов Higgsfield")
        return
    async with AsyncSessionLocal() as db:
        q = ("SELECT id, title, script_json FROM story_videos WHERE "
             "script_json::text LIKE '%\"type\": \"meaning\"%' AND status='voice'")
        if args.card:
            q = f"SELECT id, title, script_json FROM story_videos WHERE id={args.card}"
        rows = (await db.execute(_t(q))).mappings().all()
        rows = list(rows)[:args.limit]
        if not rows:
            print("нет карточек в статусе voice — нечего собирать")
            return
        async def one(sv):
            try:
                await process_card(db, dict(sv))
            except Exception as e:
                print(f"  ОШИБКА #{sv['id']}: {e}", flush=True)
                await db.execute(_t(
                    "UPDATE story_videos SET status='error', error=:e WHERE id=:i"),
                    {"e": str(e)[:400], "i": sv["id"]})
                await db.commit()
        await asyncio.gather(*(one(sv) for sv in rows))

asyncio.run(main())
