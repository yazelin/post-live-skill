#!/usr/bin/env python3
"""從整場的 whisper JSON 切出某一段的字幕，時間軸平移到那一段的 0 秒。

    python3 ~/post-live-skill/srt-slice.py 第1段.srt 0-5578
    python3 ~/post-live-skill/srt-slice.py 第2段.srt 5588-7021.8 7979-9454.5   # 多區間 = 中間剪掉

區間單位是秒，用「起-迄」寫，可以給多段（照順序拼接，等於中間那塊被剪掉）。
影片要用同一組數字切，字幕才對得上：
    ffmpeg -ss <起> -to <迄> -i 錄影.mp4 <編碼參數> 段.mp4
"""
import argparse, io, json

ap = argparse.ArgumentParser()
ap.add_argument('out')
ap.add_argument('ranges', nargs='+', help='起-迄（秒），可多組')
ap.add_argument('--json', default='work/audio.json')
a = ap.parse_args()

ranges = []
for r in a.ranges:
    lo, _, hi = r.partition('-')
    ranges.append((float(lo), float(hi)))

segs = json.load(open(a.json, encoding='utf-8'))['segments']


def ts(x):
    h, m, s = int(x // 3600), int(x % 3600 // 60), x % 60
    return f'{h:02d}:{m:02d}:{s:06.3f}'.replace('.', ',')


out, i, base = [], 0, 0.0
for lo, hi in ranges:
    for s in segs:
        # 整段落在區間內才收；跨界的那句寧可丟，也不要留半句對不上畫面
        if s['start'] >= lo and s['end'] <= hi and s['text'].strip():
            i += 1
            out.append(f'{i}\n{ts(s["start"]-lo+base)} --> {ts(s["end"]-lo+base)}\n{s["text"].strip()}\n')
    base += hi - lo
io.open(a.out, 'w', encoding='utf-8').write('\n'.join(out))
print(f'{a.out}　{i} 條字幕，總長 {base/60:.1f} 分')
