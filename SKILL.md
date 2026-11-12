---
name: post-live
description: 直播與課程辦完之後的整理線：歸檔錄影、產逐字稿並用語義校正錯字、拿逐字稿回頭補講義與簡報漏掉的內容、把長錄影切成能單獨發的段落與字幕、上雲端、更新活動頁與回顧貼文。當使用者說「直播結束了幫我整理」「轉逐字稿」「錄影切段」「回頭更新講義／簡報」「錄影上 Drive」「活動頁補錄影連結」時使用。剪重點段與短影音走 livestream-cuts，那是另一條線。
---

# post-live — 一場直播辦完之後要做的事

一場兩、三小時的錄影，價值不在檔案本身，在於**它能不能變成別人搜得到、讀得完、拿得走的東西**。
這條線把錄影變成：逐字稿、分段影片與字幕、補齊過的講義與簡報、雲端資料夾、更新過的活動頁與回顧貼文。

工具一份、每場一個資料夾：腳本在這個 repo，資料放你 `cd` 進去的那個 `直播存檔-<日期>/`。

## 先跑總控，再處理三個閘門

會後先用 `run.py` 跑可重複的整理步驟。腳本會歸檔錄影、聊天室、Gemini 筆記與現有講義／簡報，抽音訊、呼叫 Whisper、正體化、套用已整理好的 `terms.md`，並在有切段計劃時產生段落影片與字幕。完成後會產生 `會後草稿/`。

```bash
python3 ~/post-live-skill/run.py <場次資料夾> \
  --recording <錄影檔> --chat <聊天室檔> --notes <Gemini筆記檔> \
  --online <在線峰值> --line <LINE社群人數>
```

數字可以省略，未提供的欄位會寫成「未提供」。第一次執行會把來源位置與數字存在場次資料夾的 `.post-live/run.json`，續跑時不必重打。每個完成步驟在 `.post-live/steps/` 留標記；重跑會跳過標記存在的步驟。`--from terms` 會強制重跑用詞表校正及後續步驟；可用 `archive`、`transcribe`、`normalize`、`terms`、`segments`、`drafts` 指定起點。

```bash
python3 ~/post-live-skill/run.py <場次資料夾> --dry-run
python3 ~/post-live-skill/run.py <場次資料夾> --check
```

`--dry-run` 只列指令與預期檔案，不執行指令、不寫設定或標記。`--check` 唯讀檢查固定產物與收尾項目，缺項時回傳非零。腳本不會自動上傳 YouTube、Drive，不會部署直播記錄站，也不會發布 LINE 或 FB 內容。

用詞表需要人對照講稿與講義判斷。若沒有 `terms.md`，腳本會在該步失敗、仍產生不依賴逐字稿的草稿包，補好詞表後用 `--from terms` 接續。切段需要人先挑句子邊界，計劃檔放在場次資料夾或存檔資料夾的 `切段計劃.tsv`，每行格式為 `段名<TAB>起點-終點`，多區間以逗號分隔。缺少計劃時腳本不會猜切點；補好後用 `--from segments` 接續。

自動步驟完成後，先人工核對逐字稿、補講義與簡報、驗聽切點，接著處理三個閘門：

1. **上傳**：將成品影片與字幕上傳 YouTube，設為不公開；用 `rclone copy` 上傳雲端資料夾。
2. **部署**：準備直播記錄站的章節、影片與字幕資料，再執行 `cd ~/ai-workshop-backend && npm run deploy`。
3. **對外貼文**：核對並發布會後草稿包裡的 LINE 公告與 FB 留言。對外文字先跑 `speak-tw --public`。

草稿只會帶入資料夾可讀到的主題、`--online` 與 `--line` 數字；摘要、亮點及尚未取得的連結會保留為 `【待填：…】`。程式不呼叫語言模型。

## 單獨指令（除錯用）

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

總控腳本會在存檔資料夾找到 `initial_prompt.txt` 時帶入 Whisper；檔案可先由人從簡報標題與講稿整理，最多約 224 token。沒有這個檔案時，指令不加 `--initial_prompt`。

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
  --include '*.pdf' --include '逐字稿*' --include '錄影*.mp4' --include '成品.mp4' \
  --include '成品.srt' --include '切段/*' -P
```

Drive 資料夾命名照 `<活動名><MMDD>`。

### 6. 收尾文件

活動頁改成「已結束、錄影開放」並掛資料夾連結（`event_access`、`form_closed_message`、
`share-description` 三個欄位一起改，不要只改內文）。回顧貼文連結放第一則留言。
對外文字一律 `speak-tw --public`。

## GOTCHAS：每次照這份檢查

- **開頭無聲會讓整份逐字稿變成同一句。** whisper 的第一個視窗如果聽不到人聲（試音、等開播、
  背景音樂），會吐出「感谢观看」「字幕志願者 ○○○」這類訓練資料裡的收尾字幕（此處簡體是實際輸出，speak-tw-ok），接著
  `condition_on_previous_text` 把它當前文一路帶下去，**72 分鐘全變同一句，退出碼 0、不報錯**。
  偵測條件三個：輸出檔小得離譜（72 分鐘只有 2 KB）、同一句重複上百次、時間軸卻完整。
  解法 `--condition_on_previous_text False`，音量小的再加 `dynaudnorm`（見下一條）。
- **音量太小要先正規化再轉。** 2026-09-10 那支官方影片整體 -36.8 LUFS（自己錄的那場是 -19.7），
  安靜的段落直接被略過。做兩段式 loudnorm 到 -16，再串 `highpass=f=80,dynaudnorm=f=200:g=15`。
  量法：`ffmpeg -i x.wav -af loudnorm=print_format=summary -f null -`。
  順帶：**「空白很多」的抱怨常常是「太小聲」**，用 silencedetect 量之前先看整體響度，
  門檻壓在平均值上是量不到東西的。
- **`normalize.py` 的 opencc 會誤轉。** 實測會把「只」轉成「隻」（只要／只想／只有）、
  平台→平臺、權限→許可權、帳號→賬號、舞台→舞臺、了→瞭。每場都會中，
  直接寫進 `terms.md` 的常備區。`opencc` 的 `s2twp` 同樣會踩，要用 `s2tw` 再自己補台灣用語。

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

## `run.py --check` 判定方式

判定規則對照最近三場 `1021-mori-desktop/`、`1028-artifact-rpg/`、`1111-larch-3d/` 的實際結構。檢查只讀本機場次資料夾與其上層記事本、數字紀錄，不連網確認遠端狀態。

| 項目 | 存在條件 |
|---|---|
| 錄影歸檔 | `直播存檔-*/` 內有 `錄影*.mp4`。 |
| 逐字稿 | `直播存檔-*/` 內有 `逐字稿*.txt`。 |
| 校正後逐字稿 | 有 `逐字稿-成品.txt`，或同時有 `逐字稿*.txt` 與 `terms.md`。最近場次有以 `terms.md` 校正後覆寫 `逐字稿.txt` 的型態。 |
| 講義 | 場次根目錄或存檔內有 `講義*.pdf` 或 `講義*.html`。 |
| 簡報 | 場次根目錄或存檔內有 `簡報*.pdf`、`簡報*.html` 或 `deck.pdf`。 |
| 切段 | 存檔內有 `切段/*.mp4`，或有非空的 `章節.txt`／`chapters.md`。近期場次有以章節清單提供單段觀看位置的型態。 |
| 字幕 | 存檔內有 `.srt` 或 `.sbv`。 |
| 縮圖 | 有 `assets/film-thumb.*` 或 `assets/thumbs/t*.*`。 |
| 雲端資料夾連結已填 | 場次根目錄 Markdown 或存檔文字內有 Google Drive 資料夾網址。 |
| 活動頁已改 | 場次根目錄有 `活動頁-*.md` 快照，含 `event_access`、`event_materials_url`、`form_closed_message`、`share-description`，且有「已結束」與 Drive 資料夾網址。 |
| 投票頁已改 | `會後記錄*.md` 明載本場主題已從 `OPEN` 搬到 `DONE`。 |
| LINE 記事本已更新 | 場次上層的 `*月記事本.md` 含本場 `MM/DD` 日期。 |
| 數字紀錄已有這一場 | 場次上層 `數字紀錄.md` 有以本場 `MMDD` 開頭的資料列。 |
| YouTube 連結已填 | 場次根目錄 Markdown 或存檔文字內有 `youtu.be` 或 `youtube.com/watch` 網址。 |

這些條件只代表本機檔案有對應證據。例如，活動頁快照不存在時會列缺少；雲端文字裡有 Drive 網址，不代表活動頁欄位已更新。遠端部署與貼文仍由三個閘門人工確認。

## 測試替身

整合測試可以用環境變數替換外部指令，不需 GPU、網路或真的上傳：`POST_LIVE_FFMPEG_CMD`、`POST_LIVE_WHISPER_CMD`、`POST_LIVE_NORMALIZE_CMD`、`POST_LIVE_APPLY_TERMS_CMD`、`POST_LIVE_SRT_SLICE_CMD`。值是可執行指令與固定參數，會以空白分詞後呼叫，不經 shell。

## 相關

- 剪重點段、金句短影音、出燒字幕的課程版：`livestream-cuts`（`~/course-pipeline`）
- 對外文字檢查：`speak-tw`
- 換模型覆核：`llmshare`
