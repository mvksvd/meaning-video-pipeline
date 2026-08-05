#!/usr/bin/env python3
"""Автопроверка склеек (30.07, правка владельца «мимолётные кадры»): для каждого
стыка планов меряем YAVG кадров ±0.2с. Проблеск = кадры у стыка темнее/ярче ОБЕИХ
сторон (V-провал или пик) — фейд исходника или мусорный кадр. Запуск:
python3 joint_check.py <файл.mp4> → строки FLASH или CLEAN."""
import json
import subprocess
import sys


def yavg_seq(mp4, t0, dur):
    out = subprocess.run(
        ["ffmpeg", "-v", "info", "-ss", str(max(0, t0)), "-t", str(dur), "-i", mp4,
         "-vf", "signalstats,metadata=print:key=lavfi.signalstats.YAVG",
         "-f", "null", "-"],
        stderr=subprocess.PIPE, stdout=subprocess.PIPE, timeout=120)
    vals = []
    for line in out.stderr.decode("utf-8", "ignore").splitlines():
        if "YAVG" in line:
            try:
                vals.append(float(line.split("=")[-1]))
            except ValueError:
                pass
    return vals


def main(mp4):
    shots = json.load(open(mp4 + ".shots.json"))
    flashes = 0
    # РИТМ (правка владельца 31.07: микропланы 0.5с + лого 9.2с в v34 прошли
    # незамеченными): план <1.2с = брак, план >2.5x медианы = завис
    durs = sorted(s["dur"] for s in shots)
    med = durs[len(durs) // 2]
    for s in shots:
        if s["dur"] < 1.15:
            print(f"РИТМ: план {s['i']} ({s['src'].split('/')[-1]}) всего "
                  f"{s['dur']:.1f}с — микроплан")
            flashes += 1
        elif s["dur"] > 9.0 or (s["dur"] > med * 2.5 and s["dur"] > 6.0):
            print(f"РИТМ: план {s['i']} ({s['src'].split('/')[-1]}) висит "
                  f"{s['dur']:.1f}с при медиане {med:.1f}с")
            flashes += 1
    for k in range(1, len(shots)):
        t = shots[k]["start"]
        vals = yavg_seq(mp4, t - 0.2, 0.4)
        if len(vals) < 8:
            continue
        mid = len(vals) // 2
        left = sorted(vals[:mid])[len(vals[:mid]) // 2]
        right = sorted(vals[mid:])[len(vals[mid:]) // 2]
        # кадры непосредственно у стыка (центральная треть окна)
        core = vals[len(vals) // 3: 2 * len(vals) // 3]
        for v in core:
            if (v < left - 18 and v < right - 18) or (v > left + 30 and v > right + 30):
                print(f"FLASH стык {k} t={t:.2f}: кадр YAVG={v:.0f} при сторонах "
                      f"{left:.0f}/{right:.0f} ({shots[k-1]['src'].split('/')[-1]} → "
                      f"{shots[k]['src'].split('/')[-1]})")
                flashes += 1
                break
    print("CLEAN: все стыки без проблесков" if not flashes else f"ИТОГО проблесков: {flashes}")


if __name__ == "__main__":
    main(sys.argv[1])
