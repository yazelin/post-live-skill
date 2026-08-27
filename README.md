# post-live

一場直播、一堂課辦完之後的整理線：歸檔錄影、產逐字稿並校正錯字、拿逐字稿回頭補講義與簡報、
把長錄影切成能單獨發的段落與字幕、上雲端、更新活動頁與回顧貼文。

剪重點段與金句短影音是另一條線，走 [livestream-cuts](https://github.com/yazelin/course-pipeline)。

## 安裝

```bash
git clone https://github.com/yazelin/post-live-skill ~/post-live-skill
ln -s ~/post-live-skill ~/.claude/skills/post-live
```

需要 `ffmpeg`、`openai-whisper`、`rclone`，語義覆核那步需要 [llmshare](https://github.com/yazelin/duotify-ollama-cloud-setup)
與 [course-pipeline](https://github.com/yazelin/course-pipeline) 的 `fix-terms.py`。

## 兩支腳本

```bash
# 把 terms.md（每行「錯 → 對」）套進 whisper 輸出，重產逐字稿與字幕
python3 ~/post-live-skill/apply-terms.py

# 從整場的 JSON 切某一段的字幕，時間軸平移到該段的 0 秒；多區間 = 中間那塊剪掉
python3 ~/post-live-skill/srt-slice.py 第2段.srt 5588-7021.8 7979-9454.5
```

完整流程與踩過的坑在 [SKILL.md](SKILL.md)。

## 三個最值錢的結論

- **校錯字用語義，不要用拼音。** 實測同一份 169 分鐘的逐字稿：拼音比對 77 條候選只有 1 條成立，
  語義比對 99 條成立 49 條，自己讀完再對講稿 73 條全部成立。
- **判斷候選要看前後三段。** 看 30 字窗口會把「各取所需」改成「大勢所趨」，兩個都通順，只有一個是原話。
- **切點要抽 8 秒重轉驗證。** 目視縮圖與「看起來對」擋不住任何一種切錯。

## 授權

MIT © 林亞澤

---

<p align="center">
  <a href="https://github.com/yazelin">GitHub</a> ·
  <a href="https://www.facebook.com/yaze.lin.gm">Facebook</a> ·
  <a href="https://buymeacoffee.com/yazelin">請亞澤喝咖啡</a>
</p>
