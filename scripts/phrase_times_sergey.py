#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Тайминги фраз озвучки Сергея с жёсткой рамкой длительности + валидация:
если Gemini выйдет за реальную длительность — ретрай, затем фолбэк на
silencedetect (границы блоков по break-паузам) с пропорциональной раскладкой."""
import asyncio
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, "/home/MaksVideo/aiplus-content-factory/backend/src")

AUDIO = Path.home() / "aiplus-content-factory/public_frames/mv_voice_sergey_fix_108.mp3"
OUT = Path.home() / "meaning_pilot_assets/phrase_times_sergey.json"


def real_dur():
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(AUDIO)], stdout=subprocess.PIPE,
                       universal_newlines=True)
    return float(r.stdout.strip())


def strip_md(t):
    t = t.strip()
    if t.startswith("```"):
        t = t.split("```")[1]
        if t.startswith("json"):
            t = t[4:]
    return t


async def main():
    from app.services import gemini_svc
    from google.genai import types

    dur = real_dur()
    prompt = (f"Аудио длится РОВНО {dur:.1f} секунды. Транскрибируй дословно русскую "
              f"озвучку с таймингами по фразам (фраза = 2-8 слов). НИ ОДИН тайминг "
              f"не может превышать {dur:.1f}. Последняя фраза заканчивается около "
              f"{dur - 1:.0f}-{dur:.0f} сек. Верни СТРОГО JSON: "
              '{"phrases":[{"start":0.0,"end":2.0,"text":"..."}]}')
    parts = [types.Part.from_bytes(data=AUDIO.read_bytes(), mime_type="audio/mp3"),
             types.Part.from_text(text=prompt)]
    for attempt in range(3):
        resp = await gemini_svc._generate_with_retry(
            model="gemini-2.5-pro",
            contents=types.Content(parts=parts, role="user"),
            config=types.GenerateContentConfig(response_mime_type="application/json",
                                               temperature=0))
        try:
            d = json.loads(strip_md(resp.text or ""))
            ph = d["phrases"]
        except Exception as e:
            print("парс-фейл:", e)
            continue
        last = ph[-1]["end"]
        if last <= dur + 0.6 and last >= dur - 6:
            OUT.write_text(json.dumps(d, ensure_ascii=False, indent=1))
            print(f"OK попытка {attempt + 1}: фраз {len(ph)}, конец {last}")
            for p in ph:
                print(f"{p['start']:6.1f}-{p['end']:6.1f}  {p['text'][:55]}")
            return
        print(f"попытка {attempt + 1}: конец {last} вне рамки {dur:.1f} — ретрай")
    print("GEMINI НЕ СПРАВИЛСЯ — нужен фолбэк silencedetect")
    sys.exit(2)

asyncio.run(main())
