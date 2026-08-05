#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Сборщик смыслового пилота «Богатые и бедные» v1 (04.08).

Раскладка планов по фразовым таймингам утверждённой озвучки, вспышки-инверсии
на стыках звеньев (0.12с negate), нуар-сабы фразами (ass), трек 0.40.
Выход: public_frames/meaning_pilot_noir_v1.mp4 (1080x1920).
"""
import json
import subprocess
from pathlib import Path

H = Path.home()
A = H / "meaning_pilot_assets"
PF = H / "aiplus-content-factory/public_frames"
VOICE = PF / "mv_voice_sergey_fix_108.mp3"
TRACK = H / "music_library/sh1_Memory_Reboot.mp3"
TRACK_SS = 26  # старт с дропа, без долгого вступления (правка владельца)
CTA = PF / "story_assets/cta_grant_card.png"
AW = PF / "story_assets"
OUT = PF / "meaning_pilot_noir_v1.mp4"
W, HGT, FPS = 1080, 1920, 30

# (start, end, файл, kind, flash_после)
PLAN = [
    (0.0, 2.2, A / "anim_p1_jar.mp4", "v", False),
    (2.2, 5.9, A / "anim_p2_window.mp4", "v", False),
    (5.9, 9.3, A / "anim_p3_chess.mp4", "v", False),
    (9.3, 11.2, A / "anim_school.mp4", "v", False),
    (11.2, 13.2, A / "anim_p5_books.mp4", "v", False),
    (13.2, 16.5, A / "anim_parent.mp4", "v", False),
    (16.5, 21.2, A / "anim_p9_desks.mp4", "v", True),
    (21.2, 28.3, A / "anim_p8_phones.mp4", "v", False),
    (28.3, 33.8, A / "anim_class.mp4", "v", False),
    (33.8, 38.2, A / "anim_birds_noir.mp4", "v", True),
    (38.2, 41.3, A / "anim_p11_stairs.mp4", "v", False),
    (41.3, 44.2, A / "anim_burn.mp4", "v", False),
    (44.2, 47.2, A / "anim_p12_notebook.mp4", "v", True),
    (47.2, 52.1, A / "anim_p14_office.mp4", "v", False),
    (52.1, 54.7, A / "anim_p17_shelf.mp4", "v", False),
    (54.7, 56.7, A / "anim_kidsrobot.mp4", "v", False),
    (56.7, 60.6, A / "anim_p15_fork.mp4", "v", True),
    (60.6, 64.1, A / "anim_p16_jarbook.mp4", "v", False),
    (64.1, 68.4, A / "anim_pawn.mp4", "v", False),
    (68.4, 73.0, CTA, "img", False),
]

TMP = H / "meaning_build_tmp"
TMP.mkdir(exist_ok=True)


def run(cmd):
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       universal_newlines=True)
    if r.returncode != 0:
        raise RuntimeError(f"CMD FAIL: {' '.join(cmd)}\n{r.stderr[-1500:]}")


def dur_of(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(path)], stdout=subprocess.PIPE,
                       universal_newlines=True)
    return float(r.stdout.strip() or 0)


VF_FIT = (f"scale={W}:{HGT}:force_original_aspect_ratio=increase,"
          f"crop={W}:{HGT},fps={FPS},format=yuv420p")

pieces = []
for i, (s, e, src, kind, flash) in enumerate(PLAN):
    need = round(e - s, 2)
    out = TMP / f"seg{i:02d}.mp4"
    if kind == "typo":
        run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
             "-i", f"color=c=0x0a1418:s={W}x{HGT}:d={need}:r={FPS}",
             "-vf", ("drawtext=text='НЕ ОТНЯТЬ':fontcolor=white:fontsize=150:"
                     "fontfile=/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf:"
                     "x=(w-text_w)/2:y=(h-text_h)/2,format=yuv420p"),
             "-an", str(out)])
    elif kind == "img":
        run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-t", str(need),
             "-i", str(src), "-vf", VF_FIT, "-r", str(FPS), "-an", str(out)])
    else:
        d = dur_of(src)
        vf = VF_FIT
        if d < need:
            if kind == "vr":  # ЗАМОК: реальные футажи не замедлять (25fps, канон 04.08)
                raise RuntimeError(f"real-футаж {src} короче плана: {d:.2f} < {need}")
            factor = need / d + 0.02  # ИИ-почти-статика тянется чисто
            vf = f"setpts={factor:.3f}*PTS," + VF_FIT
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
             "-vf", vf, "-t", str(need), "-an", str(out)])
    if flash:  # вспышка-инверсия: последние 0.12с плана — negate
        d2 = dur_of(out)
        fl = TMP / f"seg{i:02d}f.mp4"
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(out),
             "-vf", f"negate=enable='gte(t,{max(0, d2 - 0.12):.2f})',format=yuv420p",
             "-an", str(fl)])
        out = fl
    pieces.append(out)
    print(f"seg{i:02d}: {need}с {'⚡' if flash else ''} {Path(str(src)).name if src else 'typo'}",
          flush=True)

# конкат видео
lst = TMP / "list.txt"
lst.write_text("".join(f"file '{p}'\n" for p in pieces))
noaudio = TMP / "video_nosub.mp4"
run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
     "-i", str(lst), "-c:v", "libx264", "-preset", "medium", "-crf", "19",
     "-pix_fmt", "yuv420p", str(noaudio)])

# сабы фразами (ass): нуар-стиль — белый с чёрной подложкой, ГРАНТ золотым
ph = json.loads((A / "phrase_times_sergey.json").read_text())["phrases"]


def ts(t):
    hh, rem = divmod(t, 3600)
    mm, ss = divmod(rem, 60)
    return f"{int(hh)}:{int(mm):02d}:{ss:05.2f}"


ass = [
    "[Script Info]", f"PlayResX: {W}", f"PlayResY: {HGT}", "",
    "[V4+ Styles]",
    "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, "
    "Bold, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, BorderStyle",
    "Style: sub,DejaVu Sans,72,&H00FFFFFF,&H00000000,&H90000000,-1,3,0,2,60,60,260,1",
    "Style: hook,DejaVu Sans,110,&H00FFFFFF,&H00000000,&H00000000,-1,6,0,5,40,40,0,1",
    "", "[Events]",
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
]
GOLD = "{\\c&H00D6FF&}"
WHITE = "{\\c&HFFFFFF&}"
for p in ph:
    txt = p["text"].replace("A+", "Айплюс").replace("I+", "Айплюс")
    txt = txt.replace("Грант", "ГРАНТ").replace("грант", "ГРАНТ")
    txt = txt.replace("ГРАНТ", GOLD + "ГРАНТ" + WHITE)
    ass.append(f"Dialogue: 0,{ts(p['start'])},{ts(p['end'])},sub,,0,0,0,,{txt}")
(TMP / "subs.ass").write_text("\n".join(ass))

withsubs = TMP / "video_subs.mp4"
run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(noaudio),
     "-vf", f"ass={TMP}/subs.ass", "-c:v", "libx264", "-preset", "medium",
     "-crf", "19", str(withsubs)])

# аудио: голос + трек 0.40, финальный микс
total = dur_of(withsubs)
run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(withsubs), "-i", str(VOICE),
     "-stream_loop", "-1", "-ss", str(TRACK_SS), "-i", str(TRACK),
     "-filter_complex",
     f"[2:a]volume=0.12,atrim=0:{total},afade=t=out:st={total - 2:.1f}:d=2[m];"
     f"[1:a][m]amix=inputs=2:duration=first:dropout_transition=0[a]",
     "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
     "-t", str(total), str(OUT)])
print(f"ГОТОВО: {OUT} ({dur_of(OUT):.1f}с)")
