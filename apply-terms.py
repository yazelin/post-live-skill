#!/usr/bin/env python3
"""把 terms.md 的修正套進 whisper 的輸出，重產逐字稿與字幕。

    cd <場次資料夾> && python3 ~/post-live-skill/apply-terms.py [--json work/audio.json] [--out 逐字稿]

terms.md 每行一條 `錯 → 對`，長的規則先套（避免短規則先吃掉長片語）。
text 和 words[] 都會套，但跨 token 的片語只在 text 上生效——那是預期的，
course-pipeline 的 build.py 出字幕時會自己再讀一次 terms.md。
"""
import argparse, io, json, sys
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument('--json', default='work/audio.json')
ap.add_argument('--terms', default='terms.md')
ap.add_argument('--out', default=None, help='輸出檔名前綴，預設取資料夾名')
a = ap.parse_args()

rules = []
for line in io.open(a.terms, encoding='utf-8'):
    if '→' in line and not line.lstrip().startswith('#'):
        bad, good = [x.strip() for x in line.split('→')]
        if bad:
            rules.append((bad, good))
rules.sort(key=lambda r: -len(r[0]))

d = json.load(open(a.json, encoding='utf-8'))
hits = {}


def fix(t):
    for bad, good in rules:
        if bad in t:
            hits[bad] = hits.get(bad, 0) + t.count(bad)
            t = t.replace(bad, good)
    return t


for s in d['segments']:
    s['text'] = fix(s['text'])
    for w in s.get('words', []):
        w['word'] = fix(w['word'])
json.dump(d, open(a.json, 'w', encoding='utf-8'), ensure_ascii=False)


def ts(x):
    h, m, s = int(x // 3600), int(x % 3600 // 60), x % 60
    return f'{h:02d}:{m:02d}:{s:06.3f}'.replace('.', ',')


stem = a.out or Path.cwd().name
lines, srt = [], []
for i, s in enumerate(d['segments'], 1):
    t = s['text'].strip()
    lines.append(f'[{int(s["start"]//60):02d}:{int(s["start"]%60):02d}] {t}')
    srt.append(f'{i}\n{ts(s["start"])} --> {ts(s["end"])}\n{t}\n')
io.open(f'{stem}.txt', 'w', encoding='utf-8').write('\n'.join(lines))
io.open(f'{stem}.srt', 'w', encoding='utf-8').write('\n'.join(srt))

print(f'{len(rules)} 條規則，命中 {sum(hits.values())} 處 / {len(hits)} 條')
for bad, n in sorted(hits.items(), key=lambda x: -x[1])[:15]:
    print(f'{n:5d}  {bad} → {dict(rules)[bad]}')
miss = [b for b, _ in rules if b not in hits]
if miss:
    print(f'沒命中的 {len(miss)} 條：{"、".join(miss[:12])}')
