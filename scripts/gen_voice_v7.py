#!/usr/bin/env python3
"""Два варианта озвучки пилота: Сергей с фиксом интонаций (стабильность выше,
паузы break-тегами) и голос сторителов. Правка владельца 04.08: «интонации
пляшут, пауз не хватает, звучит как недошкольник»."""
import json
import os
import subprocess
import urllib.request

HOME = os.path.expanduser("~")
PF = f"{HOME}/aiplus-content-factory/public_frames"
KEY = os.environ["ELEVENLABS_API_KEY"]
SERGEY = "XuEV9VY3VUASYgJVNBh0"
STORY = os.environ.get("ELEVENLABS_VOICE_ID", "").strip() or "JBFqnCBsd6RMkjVDRZzb"

raw = open(f"{HOME}/pilot_text_v6.txt").read()
raw = raw.replace("где все в телефонах", "где все́ в телефонах")
raw = raw.replace("Айплюс", "Айплю́с")
paras = [p.strip().replace("\n", " ") for p in raw.split("\n\n") if p.strip()]
BR6, BR4, BR3 = '<break time="0.6s" />', '<break time="0.4s" />', '<break time="0.3s" />'
text = f" {BR6} ".join(paras)
text = text.replace("Кажется, покупают знания. Нет.",
                    f"Кажется, покупают знания. {BR4} Нет. {BR3}")
text = text.replace("за соседними партами. За", f"за соседними партами. {BR4} За")
text = text.replace("Дети не слушают, что мы говорим.",
                    f"{BR3} Дети не слушают, что мы говорим.")
text = text.replace("Теперь главное.", f"Теперь главное. {BR3}")


def tts(voice: str, settings: dict, out: str) -> None:
    body = json.dumps({"text": text, "model_id": "eleven_multilingual_v2",
                       "voice_settings": settings}).encode()
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format=mp3_44100_128",
        data=body, headers={"xi-api-key": KEY, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        open(out, "wb").write(r.read())
    fast = out.replace(".mp3", "_108.mp3")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", out,
                    "-filter:a", "atempo=1.08", fast], check=True)
    d = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", fast], stdout=subprocess.PIPE,
                       universal_newlines=True).stdout
    print(os.path.basename(fast), f"{float(d):.0f}с")


tts(SERGEY, {"stability": 0.75, "similarity_boost": 0.75, "style": 0.0,
             "use_speaker_boost": True}, f"{PF}/mv_voice_sergey_fix.mp3")
tts(STORY, {"stability": 0.6, "similarity_boost": 0.75}, f"{PF}/mv_voice_story.mp3")
print("голос сторителов:", STORY)
