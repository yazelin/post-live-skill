---
name: post-live
description: 直播與課程辦完之後的整理線：歸檔錄影、產逐字稿並用語義校正錯字、拿逐字稿回頭補講義與簡報漏掉的內容、把長錄影切成能單獨發的段落與字幕、上雲端、更新活動頁與回顧貼文。當使用者說「直播結束了幫我整理」「轉逐字稿」「錄影切段」「回頭更新講義／簡報」「錄影上 Drive」「活動頁補錄影連結」時使用。剪重點段與短影音走 livestream-cuts，那是另一條線。
---

# post-live — 一場直播辦完之後要做的事

一場兩、三小時的錄影，價值不在檔案本身，在於**它能不能變成別人搜得到、讀得完、拿得走的東西**。
這條線把錄影變成：逐字稿、分段影片與字幕、補齊過的講義與簡報、雲端資料夾、更新過的活動頁與回顧貼文。

工具一份、每場一個資料夾：腳本在這個 repo，資料放你 `cd` 進去的那個 `直播存檔-<日期>/`。

## 順序（每一步都可以單獨跑）

### 0. 歸檔

錄影放 `yaze-journal/projects/wednesday-live/<場次>/直播存檔-<日期>/`（gitignore 已擋大檔），
簡報與講義 PDF 複製一份進去，日後這個資料夾就是整包上雲端的內容。

### 1. 轉逐字稿

```bash
ffmpeg -v error -i 錄影.mp4 -vn -ac 1 -ar 16000 work/audio.wav
python3 -m whisper work/audio.wav --model turbo --language zh --word_timestamps True \
  --initial_prompt "這場的專有名詞，逗號分隔，約 224 token" --output_dir work --output_format all
python3 ~/course-pipeline/normalize.py     # opencc 正體化 + 清結尾幻覺
```

`initial_prompt` 從簡報標題與講稿抓詞。RTX 4060 上 turbo 帶 word timestamps 約 **13 倍速**，
169 分鐘的錄影 13 分鐘轉完。

### 2. 校錯字：語義，不要拼音

三輪，**判準是語義**：

1. **自己讀完整份**，對著簡報講稿與講義的用字寫 `terms.md`（每行 `錯 → 對`）。
2. **`fix-terms.py` 換家族覆核**：`SMOOTH_MODEL=<model> python3 ~/course-pipeline/fix-terms.py`，
   它走 llmshare，把逐字稿切塊連同詞彙表送出去。跑兩輪不同家族（deepseek / glm / kimi），取交集與差集。
3. 候選逐條看過再採用。**判斷時把該處前後各三段撈出來看**，不要只看工具印的那 30 字窗口。

```bash
python3 ~/post-live-skill/apply-terms.py     # 套 terms.md → 重產 逐字稿.txt / .srt
```

### 3. 拿逐字稿回頭補講義與簡報

現場一定會講到文件裡沒有的東西，那是這場最貴的部分，也是最容易蒸發的部分。
做法是拿逐字稿跟講稿比，只收「**現場真的講了、而文件沒寫**」的，補進講義（可以長）與簡報（要短）。
簡報別加頁，`PACE` 陣列綁著頁數；補在既有頁的 `code-note` 或講稿備註裡。
補完跑 `speak-tw --public` 與該場的渲染檢查，PDF 重產。

### 4. 切段

切點抓在**句子邊界**，用逐字稿的 segment 起訖秒數決定，不要抓整數分鐘。休息、播音樂、閒聊整段拿掉。

```bash
enc="-c:v h264_nvenc -preset p5 -rc vbr -cq 30 -b:v 0 -maxrate 1500k -bufsize 3000k -c:a aac -b:a 128k -movflags +faststart"
ffmpeg -v error -y -ss 0 -to 5578 -i 錄影.mp4 $enc 第1段.mp4
# 中間要剪掉一塊：切兩段再 concat（兩段編碼參數一樣才能 -c copy 接）
python3 ~/post-live-skill/srt-slice.py 第2段.srt 5588-7021.8 7979-9454.5
```

**每個切點抽 8 秒音訊重轉一次，確認聽到的就是預期那句**，這是唯一算數的驗收。

### 5. 上雲端

```bash
rclone copy . gdrive: --drive-root-folder-id <資料夾 ID> \
  --include '*.pdf' --include '逐字稿*' --include '錄影*.mp4' --include '切段/*' -P
```

Drive 資料夾命名照 `<活動名><MMDD>`。

### 6. 收尾文件

活動頁改成「已結束、錄影開放」並掛資料夾連結（`event_access`、`form_closed_message`、
`share-description` 三個欄位一起改，不要只改內文）。回顧貼文連結放第一則留言。
對外文字一律 `speak-tw --public`。

## GOTCHAS：每次照這份檢查

- **拼音比對不要用。** 2026-08-26 那場實測：`terms-suggest.py`（拼音）77 條候選只有 1 條成立；
  llmshare 語義比對 99 條成立 49 條；自己讀完再對講稿 73 條全部成立。同音撞出來的雜訊
  （「一般→一版」「心態→型態」「舉例→拘泥」）看起來很像，但都是錯的。
- **候選要看上下文再判。** 我把「各去所趨」按讀音改成「大勢所趨」，講者原話是「各取所需」，他前一句在講「有人提供想法、有人實作」。看 30 字窗口不夠，撈前後三段。
- **`text` 改了 `words[]` 不會跟著改。** 跨 token 的片語只在 `text` 生效。逐字稿與 srt 是從 `text` 產的所以沒事；
  之後要用 `build.py` 出燒字幕的版本，它會自己再讀一次 `terms.md`。
- **`rclone --include '*.txt'` 會遞迴撈到 `work/`。** 中間檔會一起上雲端，指名檔案或用 `--include '逐字稿*'`。
- **休息與音樂段會生出整排「嗯」。** whisper 對無語音段會硬湊字，切段時整段拿掉就好，不用去修那些字。
- **講者口誤照留。** 逐字稿是紀錄不是校正稿；口誤（例如把「每日 200 次」講成「200 字」）寫進會後記錄，
  簡報與講義維持正確版本。
- **`--model tiny` 只拿來驗切點。** 它認不出專有名詞，拿它轉正式逐字稿會白做一輪。
- **時長會超。** 2026-08-26 排 90 分鐘、實際講 169 分鐘，第 93 分鐘才進技術段。
  會後記錄要寫下實際分段時間，下一場排議程時才有依據。

## 驗收清單

- [ ] 每個切點抽 8 秒重轉，聽到的是預期那句
- [ ] 分段字幕條數與該段長度對得起來，接點前後兩句連得起來
- [ ] 講義與簡報補完跑過 `speak-tw --public`，PDF 重產
- [ ] 雲端資料夾裡沒有 `work/` 的中間檔
- [ ] 活動頁三個 front matter 欄位都改了，不是只改內文
- [ ] 會後記錄寫下實際時長、分段時間、現場補講了什麼

## 相關

- 剪重點段、金句短影音、出燒字幕的課程版：`livestream-cuts`（`~/course-pipeline`）
- 對外文字檢查：`speak-tw`
- 換模型覆核：`llmshare`
