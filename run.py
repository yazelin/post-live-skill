#!/usr/bin/env python3
"""依序整理直播會後資料，保留需要人工判斷的步驟與外部閘門。"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
STEPS = [
    ("archive", "歸檔"),
    ("transcribe", "轉逐字稿"),
    ("normalize", "正體化"),
    ("terms", "套用用詞表"),
    ("segments", "切段與字幕"),
    ("drafts", "產生會後草稿包"),
]
ENCODER = [
    "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "30",
    "-b:v", "0", "-maxrate", "1500k", "-bufsize", "3000k",
    "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
]


class WorkflowError(Exception):
    """會後流程的可讀錯誤。"""


def say(text: str) -> None:
    print(text, flush=True)


def run_command(command: list[str], cwd: Path, dry_run: bool = False) -> None:
    say("  指令：" + shlex.join(command))
    if dry_run:
        return
    try:
        subprocess.run(command, cwd=cwd, check=True)
    except FileNotFoundError as exc:
        raise WorkflowError(f"找不到指令：{command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        raise WorkflowError(f"指令結束碼為 {exc.returncode}：{shlex.join(command)}") from exc


def command_prefix(env_name: str, default: list[str]) -> list[str]:
    value = os.environ.get(env_name)
    return shlex.split(value) if value else default


def date_code(session: Path) -> str:
    match = re.match(r"(\d{4})", session.name)
    return match.group(1) if match else session.name


def archive_dir(session: Path) -> Path:
    code = date_code(session)
    found = sorted(path for path in session.glob("直播存檔-*") if path.is_dir())
    matching = [path for path in found if path.name.endswith(code)]
    if matching:
        return matching[-1]
    if len(found) == 1:
        return found[0]
    return session / f"直播存檔-{code}"


def config_paths(session: Path) -> tuple[Path, Path]:
    state = session / ".post-live"
    return state / "run.json", state / "steps"


def load_config(session: Path) -> dict:
    config_file, _ = config_paths(session)
    if not config_file.exists():
        return {}
    try:
        return json.loads(config_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowError(f"無法讀取流程設定 {config_file}：{exc}") from exc


def input_config(args: argparse.Namespace, session: Path, saved: dict) -> dict:
    result = dict(saved)
    for key in ("recording", "chat", "notes"):
        value = getattr(args, key)
        if value:
            result[key] = str(value.expanduser().resolve())
    for key in ("online", "line"):
        value = getattr(args, key)
        if value is not None:
            result[key] = value
    if args.recording is None and not result.get("recording"):
        candidates = list(archive_dir(session).glob("錄影*.mp4"))
        if candidates:
            result["recording"] = str(candidates[0].resolve())
    if args.chat is None and not result.get("chat"):
        candidates = list(archive_dir(session).glob("聊天室.*")) + list(archive_dir(session).glob("聊天*.*"))
        if candidates:
            result["chat"] = str(candidates[0].resolve())
    if args.notes is None and not result.get("notes"):
        candidates = list(archive_dir(session).glob("Gemini筆記*"))
        if candidates:
            result["notes"] = str(candidates[0].resolve())
    return result


def save_config(session: Path, config: dict) -> None:
    config_file, _ = config_paths(session)
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def mark_path(session: Path, step: str) -> Path:
    _, markers = config_paths(session)
    return markers / f"{step}.done"


def mark_done(session: Path, step: str) -> None:
    path = mark_path(session, step)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(datetime.now().astimezone().isoformat(timespec="seconds") + "\n", encoding="utf-8")


def is_done(session: Path, step: str) -> bool:
    return mark_path(session, step).is_file()


def copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != destination.resolve():
        shutil.copy2(source, destination)


def session_materials(session: Path) -> list[Path]:
    items: dict[str, Path] = {}
    for pattern in ("簡報*.pdf", "簡報*.html", "講義*.pdf", "講義*.html", "deck.pdf", "deck.html"):
        for folder in (session, session / "下載"):
            for path in folder.glob(pattern):
                if path.is_file():
                    items.setdefault(path.name, path)
    return [items[name] for name in sorted(items)]


def stage_archive(session: Path, config: dict, dry_run: bool = False) -> None:
    destination = archive_dir(session)
    inputs = (("recording", "錄影"), ("chat", "聊天室"), ("notes", "Gemini筆記"))
    for key, stem in inputs:
        raw = config.get(key)
        if not raw:
            raise WorkflowError(f"缺少 --{key}，第一次執行歸檔需要錄影、聊天室與 Gemini 筆記檔")
        source = Path(raw).expanduser()
        if not source.is_file():
            raise WorkflowError(f"輸入檔不存在：{source}")
        target = destination / f"{stem}{source.suffix or '.txt'}"
        if source.resolve() == target.resolve():
            say(f"  已在存檔位置，略過：{target}")
            continue
        say(f"  指令：cp -p {shlex.quote(str(source))} {shlex.quote(str(target))}")
        if not dry_run:
            copy_file(source, target)
    for item in session_materials(session):
        target = destination / item.name
        if item.resolve() == target.resolve():
            say(f"  已在存檔位置，略過：{target}")
            continue
        say(f"  指令：cp -p {shlex.quote(str(item))} {shlex.quote(str(target))}")
        if not dry_run:
            copy_file(item, target)
    source_terms = session / "terms.md"
    target_terms = destination / "terms.md"
    if source_terms.is_file() and not target_terms.is_file():
        if source_terms.resolve() == target_terms.resolve():
            return
        say(f"  指令：cp -p {shlex.quote(str(source_terms))} {shlex.quote(str(target_terms))}")
        if not dry_run:
            copy_file(source_terms, target_terms)
    source_prompt = session / "initial_prompt.txt"
    target_prompt = destination / "initial_prompt.txt"
    if source_prompt.is_file() and not target_prompt.is_file():
        if source_prompt.resolve() == target_prompt.resolve():
            return
        say(f"  指令：cp -p {shlex.quote(str(source_prompt))} {shlex.quote(str(target_prompt))}")
        if not dry_run:
            copy_file(source_prompt, target_prompt)


def transcribe_commands(session: Path, config: dict) -> list[list[str]]:
    archive = archive_dir(session)
    recording = archive / f"錄影{Path(config['recording']).suffix or '.mp4'}"
    wav = archive / "work" / "audio.wav"
    ffmpeg = command_prefix("POST_LIVE_FFMPEG_CMD", ["ffmpeg"])
    whisper = command_prefix("POST_LIVE_WHISPER_CMD", ["python3", "-m", "whisper"])
    commands = [ffmpeg + ["-v", "error", "-y", "-i", str(recording), "-vn", "-ac", "1", "-ar", "16000", str(wav)]]
    whisper_args = [
        str(wav), "--model", "turbo", "--language", "zh", "--word_timestamps", "True",
        "--output_dir", str(archive / "work"), "--output_format", "all",
    ]
    prompt = archive / "initial_prompt.txt"
    if prompt.is_file():
        prompt_text = prompt.read_text(encoding="utf-8").strip()
        if prompt_text:
            whisper_args += ["--initial_prompt", prompt_text]
    commands.append(whisper + whisper_args)
    return commands


def render_srt_time(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int(seconds % 3600 // 60)
    remainder = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{remainder:06.3f}".replace(".", ",")


def render_plain_time(seconds: float) -> str:
    return f"[{int(seconds // 60):02d}:{int(seconds % 60):02d}]"


def render_transcript(json_path: Path, archive: Path) -> None:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    lines: list[str] = []
    srt: list[str] = []
    for index, segment in enumerate(data.get("segments", []), 1):
        text = str(segment.get("text", "")).strip()
        if not text:
            continue
        lines.append(f"{render_plain_time(float(segment['start']))} {text}")
        srt.append(
            f"{index}\n{render_srt_time(float(segment['start']))} --> "
            f"{render_srt_time(float(segment['end']))}\n{text}\n"
        )
    (archive / "逐字稿.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (archive / "逐字稿.srt").write_text("\n".join(srt), encoding="utf-8")


def stage_transcribe(session: Path, config: dict, dry_run: bool = False) -> None:
    archive = archive_dir(session)
    for command in transcribe_commands(session, config):
        run_command(command, archive, dry_run)
    if not dry_run and not (archive / "work" / "audio.json").is_file():
        raise WorkflowError("Whisper 沒有產生 work/audio.json")


def stage_normalize(session: Path, dry_run: bool = False) -> None:
    archive = archive_dir(session)
    audio_json = archive / "work" / "audio.json"
    if not audio_json.is_file() and not dry_run:
        raise WorkflowError("找不到 work/audio.json，請先完成逐字稿轉錄，或執行 --from transcribe")
    command = command_prefix(
        "POST_LIVE_NORMALIZE_CMD",
        ["python3", str(Path.home() / "course-pipeline" / "normalize.py")],
    )
    run_command(command, archive, dry_run)
    if dry_run:
        say(f"  預期檔案：{audio_json}、{archive / 'work/audio.normalized.json'}、{archive / '逐字稿.txt'}、{archive / '逐字稿.srt'}")
        return
    if not audio_json.is_file():
        raise WorkflowError("正體化指令結束後 work/audio.json 不存在")
    normalized = archive / "work" / "audio.normalized.json"
    shutil.copy2(audio_json, normalized)
    render_transcript(normalized, archive)


def stage_terms(session: Path, dry_run: bool = False) -> None:
    archive = archive_dir(session)
    terms = archive / "terms.md"
    if not terms.is_file() and (session / "terms.md").is_file():
        terms = session / "terms.md"
    if not terms.is_file() and not dry_run:
        raise WorkflowError("找不到 terms.md；請先對照講稿與講義整理錯字 → 正字，再用 --from terms 接續")
    normalized = archive / "work" / "audio.normalized.json"
    audio_json = archive / "work" / "audio.json"
    if not normalized.is_file() and not dry_run:
        raise WorkflowError("找不到正體化後的 work/audio.normalized.json，請先執行 --from normalize")
    if not dry_run:
        shutil.copy2(normalized, audio_json)
    command = command_prefix("POST_LIVE_APPLY_TERMS_CMD", ["python3", str(ROOT / "apply-terms.py")])
    command += ["--json", "work/audio.json", "--terms", str(terms), "--out", "逐字稿-成品"]
    run_command(command, archive, dry_run)
    if dry_run:
        say(f"  預期檔案：{archive / '逐字稿-成品.txt'}、{archive / '逐字稿-成品.srt'}")
        return
    for name in ("逐字稿-成品.txt", "逐字稿-成品.srt"):
        if not (archive / name).is_file():
            raise WorkflowError(f"用詞表校正後缺少 {name}")


def parse_cut_plan(plan: Path) -> list[tuple[str, list[tuple[float, float]]]]:
    result: list[tuple[str, list[tuple[float, float]]]] = []
    for number, line in enumerate(plan.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        fields = line.split("\t", 1)
        if len(fields) != 2:
            raise WorkflowError(f"切段計劃第 {number} 行需為「名稱<TAB>起訖秒數」")
        title, raw_ranges = fields[0].strip(), fields[1].strip()
        ranges: list[tuple[float, float]] = []
        for raw_range in raw_ranges.split(","):
            start, separator, end = raw_range.strip().partition("-")
            if not separator:
                raise WorkflowError(f"切段計劃第 {number} 行的區間格式錯誤：{raw_range}")
            try:
                lo, hi = float(start), float(end)
            except ValueError as exc:
                raise WorkflowError(f"切段計劃第 {number} 行的秒數不是數字：{raw_range}") from exc
            if lo < 0 or hi <= lo:
                raise WorkflowError(f"切段計劃第 {number} 行的區間需大於零：{raw_range}")
            ranges.append((lo, hi))
        if not title or not ranges:
            raise WorkflowError(f"切段計劃第 {number} 行缺少名稱或區間")
        if Path(title).name != title or title in {".", ".."}:
            raise WorkflowError(f"切段計劃第 {number} 行的名稱不可包含路徑：{title}")
        result.append((title, ranges))
    if not result:
        raise WorkflowError("切段計劃沒有任何有效項目")
    return result


def cut_plan_path(session: Path) -> Path | None:
    archive = archive_dir(session)
    for candidate in (archive / "切段計劃.tsv", session / "切段計劃.tsv"):
        if candidate.is_file():
            return candidate
    return None


def ffmpeg_part_command(ffmpeg: list[str], source: Path, start: float, end: float, output: Path) -> list[str]:
    return ffmpeg + [
        "-v", "error", "-y", "-ss", str(start), "-to", str(end), "-i", str(source),
        *ENCODER, str(output),
    ]


def concat_command(ffmpeg: list[str], concat_file: Path, output: Path) -> list[str]:
    return ffmpeg + ["-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file), "-c", "copy", str(output)]


def stage_segments(session: Path, dry_run: bool = False) -> bool:
    archive = archive_dir(session)
    plan = cut_plan_path(session)
    if plan is None:
        say("  略過：尚無切段計劃.tsv；逐字稿需由人挑選句子邊界與區間")
        say(f"  預期檔案：{archive / '切段/第NN段-名稱.mp4'}、{archive / '切段/第NN段-名稱.srt'}")
        say("  指令範本：ffmpeg -v error -y -ss <起點> -to <終點> -i 錄影.mp4 <編碼參數> 切段/<段名>.mp4")
        say("  字幕範本：python3 srt-slice.py 切段/<段名>.srt <起點>-<終點> --json work/audio.json")
        say(f"  接續方式：建立 {archive / '切段計劃.tsv'}，再執行 python3 {ROOT / 'run.py'} {session} --from segments")
        return False
    audio_json = archive / "work" / "audio.json"
    transcript = archive / "逐字稿-成品.txt"
    if not dry_run and (not audio_json.is_file() or not transcript.is_file()):
        say("  略過：尚無校正後逐字稿，請先完成用詞表，再執行 --from segments")
        return False
    recording_candidates = list(archive.glob("錄影*.mp4"))
    if not recording_candidates:
        raise WorkflowError("存檔資料夾沒有錄影*.mp4")
    source = recording_candidates[0]
    cuts = parse_cut_plan(plan)
    output_dir = archive / "切段"
    ffmpeg = command_prefix("POST_LIVE_FFMPEG_CMD", ["ffmpeg"])
    srt_slice = command_prefix("POST_LIVE_SRT_SLICE_CMD", ["python3", str(ROOT / "srt-slice.py")])
    for index, (title, ranges) in enumerate(cuts, 1):
        stem = f"第{index:02d}段-{title}"
        output_video = output_dir / f"{stem}.mp4"
        output_srt = output_dir / f"{stem}.srt"
        if len(ranges) == 1:
            lo, hi = ranges[0]
            run_command(ffmpeg_part_command(ffmpeg, source, lo, hi, output_video), archive, dry_run)
        else:
            parts_dir = output_dir / ".parts"
            parts = [parts_dir / f"{stem}-{part:02d}.mp4" for part in range(1, len(ranges) + 1)]
            for (lo, hi), part_path in zip(ranges, parts):
                run_command(ffmpeg_part_command(ffmpeg, source, lo, hi, part_path), archive, dry_run)
            concat_file = parts_dir / f"{stem}.txt"
            say(f"  檔案：{concat_file}（ffmpeg concat 清單）")
            if not dry_run:
                concat_file.parent.mkdir(parents=True, exist_ok=True)
                lines = ["file '" + str(part.resolve()).replace("'", "'\\''") + "'" for part in parts]
                concat_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
            run_command(concat_command(ffmpeg, concat_file, output_video), archive, dry_run)
        range_args = [f"{lo}-{hi}" for lo, hi in ranges]
        run_command(srt_slice + [str(output_srt), *range_args, "--json", "work/audio.json"], archive, dry_run)
        say(f"  預期檔案：{output_video}、{output_srt}")
        if not dry_run and (not output_video.is_file() or not output_srt.is_file()):
            raise WorkflowError(f"第 {index} 段缺少影片或字幕輸出")
    return True


def read_session_title(session: Path) -> str:
    for pattern in ("會後記錄*.md", "籌備記錄*.md", "公告文*.md"):
        for path in sorted(session.glob(pattern)):
            text = path.read_text(encoding="utf-8")
            for line in text.splitlines():
                if not line.startswith("# "):
                    continue
                heading = line[2:].strip()
                match = re.match(r"(?:會後記錄\s*)?\d{4}[：:]\s*(.+)", heading)
                if match:
                    return match.group(1).strip()
                match = re.match(r"\d{4}\s+會後記錄\s*[：:]\s*(.+)", heading)
                if match:
                    return match.group(1).strip()
                if heading:
                    return heading
    return "【待填：場次主題】"


def clean_title(title: str) -> str:
    return title.replace("\n", " ").strip()


def draft_files(session: Path, config: dict) -> dict[str, str]:
    code = date_code(session)
    date = f"{code[:2]}/{code[2:]}" if re.fullmatch(r"\d{4}", code) else "【待填：日期】"
    title = clean_title(read_session_title(session))
    summary = "【待填：一句話摘要】"
    highlight = "【待填：亮點】"
    recording_link = "【待填：錄影連結】"
    drive_link = "【待填：雲端資料夾連結】"
    line_value = config.get("line", "未提供")
    online_value = config.get("online", "未提供")

    event_page = f"""# 活動頁變更

請更新這場活動頁的以下欄位：

```yaml
event_access: 已結束。錄影與會後資料開放取用
event_materials_url: 【待填：雲端資料夾連結】
form_closed_message: 這場已經結束。錄影連結：【待填：錄影連結】。會後資料放在雲端資料夾：【待填：雲端資料夾連結】。免費，不用留資料。
share-description: 【待填：一句話摘要】
```

活動標題：{title}
主題摘要：{summary}
亮點：{highlight}
"""
    vote_page = f"""# 投票頁變更

在投票頁的 `topics.js`（或目前使用的 `topics.mjs`）找到「{title}」：

`OPEN`：刪除【待填：本場現有主題項目】。

`DONE`：貼入同一個項目，保留原欄位，並補上 `feedback: true` 與錄影連結 `{recording_link}`。

不要重寫主題或其他欄位。
"""
    line_note = f"""{date}　{title}（已結束，錄影開放）
{summary}
亮點：{highlight}
錄影連結：{recording_link}
雲端資料夾：{drive_link}
"""
    line_post = f"""# LINE 會後公告

貼到 LINE 社群。

---

{date} 的「{title}」直播結束了，謝謝來的朋友。

錄影和會後資料放在雲端資料夾，免費，不用留資料：
{drive_link}

錄影連結：{recording_link}
這場分享：{summary}
會中亮點：{highlight}
"""
    fb_post = f"""# FB 會後追加留言

貼在本場 FB 預告貼文底下。

---

直播結束了，謝謝昨晚來的朋友。

錄影和會後資料放在雲端資料夾，免費，不用留資料：
{drive_link}

錄影連結：{recording_link}
這場分享：{summary}
會中亮點：{highlight}
"""
    numbers_row = f"| {code} | {title} | {line_value} | 未提供 | 未提供 | {online_value} |"
    numbers = f"# 數字紀錄列\n\n請追加到 `數字紀錄.md`：\n\n| 場次 | 主題 | LINE 社群人數 | 活動頁瀏覽 | FB 貼文觸及 | 在線峰值 |\n|---|---|---|---|---|---|\n{numbers_row}\n"
    return {
        "活動頁變更.md": event_page,
        "投票頁變更.md": vote_page,
        "LINE記事本.md": line_note,
        "會後公告.md": line_post,
        "FB留言.md": fb_post,
        "數字紀錄列.md": numbers,
    }


def stage_drafts(session: Path, config: dict, dry_run: bool = False) -> None:
    destination = session / "會後草稿"
    say("  指令：執行內建純程式草稿產生器，不呼叫語言模型")
    for name in draft_files(session, config):
        target = destination / name
        say(f"  預期檔案：{target}")
    if dry_run:
        return
    destination.mkdir(parents=True, exist_ok=True)
    for name, content in draft_files(session, config).items():
        (destination / name).write_text(content.rstrip() + "\n", encoding="utf-8")


def print_gates(session: Path) -> None:
    archive = archive_dir(session)
    finished_video = archive / "成品.mp4"
    if not finished_video.is_file():
        finished_video = archive / "【待完成：剪輯後影片】"
    subtitle = next(
        (candidate for candidate in (archive / "逐字稿-成品.srt", archive / "成品.srt", archive / "逐字稿.srt") if candidate.is_file()),
        archive / "【待完成：字幕檔】",
    )
    say("\n三個閘門，請人工接手：")
    say("1. 上傳（YouTube、雲端硬碟）")
    say(f"   YouTube Studio：選取 {finished_video}，設為不公開，匯入 {subtitle}，完成後把連結填進會後草稿。")
    say(f"   rclone copy {shlex.quote(str(archive))} 'gdrive:<資料夾名稱>{date_code(session)}' --include '*.pdf' --include '逐字稿*' --include '錄影*.mp4' --include '成品.mp4' --include '成品.srt' --include '切段/*' -P")
    say("2. 部署（直播記錄站）")
    say("   完成 YouTube 連結、章節與逐段字幕資料後，執行：cd ~/ai-workshop-backend && npm run deploy")
    say("3. 對外貼文")
    say(f"   LINE 社群貼上 {session / '會後草稿' / '會後公告.md'}；FB 預告貼文留言貼上 {session / '會後草稿' / 'FB留言.md'}。貼出前先跑 speak-tw --public。")


def dry_run(session: Path, config: dict, from_step: str | None) -> int:
    start_index = next((i for i, (step, _) in enumerate(STEPS) if step == from_step), 0)
    archive = archive_dir(session)
    stages = {
        "archive": lambda: stage_archive(session, config, True),
        "transcribe": lambda: dry_transcribe(session, config),
        "normalize": lambda: stage_normalize(session, True),
        "terms": lambda: stage_terms(session, True),
        "segments": lambda: stage_segments(session, True),
        "drafts": lambda: stage_drafts(session, config, True),
    }
    for index, (step, label) in enumerate(STEPS):
        if index < start_index:
            say(f"略過已完成步驟：{label}")
            continue
        if from_step is None and is_done(session, step):
            say(f"略過已完成步驟：{label}（標記存在）")
            continue
        say(f"開始預覽步驟：{label}")
        try:
            result = stages[step]()
            if step == "segments" and result is False:
                say(f"等待輸入：{label}")
            else:
                say(f"預覽完成：{label}")
        except WorkflowError as exc:
            say(f"預覽受阻：{label}：{exc}")
    print_gates(session)
    return 0


def dry_transcribe(session: Path, config: dict) -> None:
    archive = archive_dir(session)
    for command in transcribe_commands(session, config):
        run_command(command, archive, True)
    say(f"  預期檔案：{archive / 'work/audio.wav'}、{archive / 'work/audio.json'}、{archive / 'work/audio.txt'}、{archive / 'work/audio.srt'}")


def check_files(session: Path) -> list[tuple[str, bool, str]]:
    # 判定依據取自最近三場 1021、1028、1111 的場次資料夾。
    # 錄影看存檔內的錄影 MP4；逐字稿看逐字稿 TXT；校正看成品 TXT，或 TXT 與 terms.md 同在。
    # 講義與簡報看根目錄或存檔的 PDF／HTML；切段看 MP4 或章節清單；字幕看 SRT／SBV。
    # 縮圖看 film-thumb 或 thumbs/t*；Drive 與 YouTube 看本機文字網址。
    # 活動頁看根目錄快照及四個欄位；投票看會後記錄中的 OPEN 到 DONE；記事本與數字看上層檔案。
    # 不連網檢查遠端頁面，所以本機缺少活動頁快照時必須列為缺少。
    archives = sorted(path for path in session.glob("直播存檔-*") if path.is_dir())
    root_files = [path for path in session.iterdir() if path.is_file()]
    archive_files = [path for archive in archives for path in archive.iterdir() if path.is_file()]
    recording = any(path.name.startswith("錄影") and path.suffix.lower() == ".mp4" for path in archive_files)
    transcript_files = [path for path in archive_files if path.name.startswith("逐字稿") and path.suffix.lower() == ".txt"]
    transcript = bool(transcript_files)
    corrected = any(path.name == "逐字稿-成品.txt" for path in transcript_files) or (
        transcript and any(path.name == "terms.md" for path in archive_files)
    )
    handout = any(re.match(r"講義.*\.(pdf|html)$", path.name, re.IGNORECASE) for path in root_files + archive_files)
    slides = any(
        path.name == "deck.pdf" or re.match(r"簡報.*\.(pdf|html)$", path.name, re.IGNORECASE)
        for path in root_files + archive_files
    )
    cut_files = [path for archive in archives for path in archive.iterdir() if path.is_dir() and path.name == "切段" for path in path.glob("*.mp4")]
    chapters = any(path.name in {"章節.txt", "chapters.md"} and path.stat().st_size > 0 for path in archive_files)
    cuts = bool(cut_files) or chapters
    captions = any(path.suffix.lower() in {".srt", ".sbv"} for path in archive_files)
    thumbs_dir = session / "assets"
    thumbnail = any(thumbs_dir.glob("film-thumb.*")) or any((thumbs_dir / "thumbs").glob("t*.*"))

    markdown_files = list(session.glob("*.md"))
    archive_text_files = [path for path in archive_files if path.suffix.lower() in {".md", ".txt"}]
    searchable = markdown_files + archive_text_files
    cloud_link = any("drive.google.com/drive/folders/" in path.read_text(encoding="utf-8", errors="ignore") for path in searchable)
    event_pages = [path for path in root_files if path.name.startswith("活動頁-") and path.suffix.lower() == ".md"]
    event_page = any(
        all(key in path.read_text(encoding="utf-8", errors="ignore") for key in ("event_access:", "event_materials_url:", "form_closed_message:", "share-description:"))
        and "已結束" in path.read_text(encoding="utf-8", errors="ignore")
        and "drive.google.com/drive/folders/" in path.read_text(encoding="utf-8", errors="ignore")
        for path in event_pages
    )
    records = list(session.glob("會後記錄*.md"))
    record_text = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in records)
    vote_page = bool(re.search(r"從\s*`?OPEN`?\s*搬到\s*`?DONE`?", record_text))
    code = date_code(session)
    month_note = any(
        re.search(rf"(?<!\d){re.escape(code[:2])}[/-]{re.escape(code[2:])}(?!\d)", path.read_text(encoding="utf-8", errors="ignore"))
        for path in session.parent.glob("*月記事本.md")
    )
    number_file = session.parent / "數字紀錄.md"
    number_row = number_file.is_file() and bool(re.search(rf"^\|\s*{re.escape(code)}\s*\|", number_file.read_text(encoding="utf-8", errors="ignore"), re.MULTILINE))
    youtube = any(
        re.search(r"https?://(?:www\.)?(?:youtu\.be/|youtube\.com/watch)", path.read_text(encoding="utf-8", errors="ignore"))
        for path in searchable
    )
    return [
        ("錄影歸檔", recording, "直播存檔-* 內有錄影*.mp4"),
        ("逐字稿", transcript, "直播存檔-* 內有逐字稿*.txt"),
        ("校正後逐字稿", corrected, "有逐字稿-成品.txt，或逐字稿*.txt 與 terms.md"),
        ("講義", handout, "場次根目錄或存檔內有講義*.pdf／講義*.html"),
        ("簡報", slides, "場次根目錄或存檔內有簡報*.pdf／簡報*.html／deck.pdf"),
        ("切段", cuts, "有切段/*.mp4，或存檔內有章節.txt／chapters.md"),
        ("字幕", captions, "存檔內有 .srt 或 .sbv"),
        ("縮圖", thumbnail, "assets/film-thumb.* 或 assets/thumbs/t*.*"),
        ("雲端資料夾連結已填", cloud_link, "場次 Markdown 或存檔文字內有 Google Drive 資料夾網址"),
        ("活動頁已改", event_page, "場次內有活動頁快照，含四個欄位、已結束與 Drive 網址"),
        ("投票頁已改", vote_page, "會後記錄寫明主題已從 OPEN 搬到 DONE"),
        ("LINE 記事本已更新", month_note, "上層月份記事本內有 MM/DD 場次日期"),
        ("數字紀錄已有這一場", number_row, "上層數字紀錄.md 有本場場次代碼列"),
        ("YouTube 連結已填", youtube, "場次 Markdown 或存檔文字內有 YouTube 網址"),
    ]


def run_check(session: Path) -> int:
    results = check_files(session)
    say(f"驗收：{session}")
    missing = 0
    for label, passed, rule in results:
        if passed:
            say(f"打勾：{label}（判定：{rule}）")
        else:
            missing += 1
            say(f"缺少：{label}（判定：{rule}）")
    if missing:
        say(f"缺少 {missing} 項；補齊後重跑 python3 {ROOT / 'run.py'} {session} --check。")
        return 1
    say("固定產物與收尾項目齊全。")
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="直播會後自動整理與驗收")
    result.add_argument("session", type=Path, help="場次資料夾")
    result.add_argument("--recording", type=Path, help="錄影檔")
    result.add_argument("--chat", type=Path, help="聊天室檔")
    result.add_argument("--notes", type=Path, help="Gemini 筆記檔")
    result.add_argument("--online", help="在線峰值")
    result.add_argument("--line", help="LINE 社群人數")
    result.add_argument("--from", dest="from_step", choices=[step for step, _ in STEPS], help="強制從指定步驟重跑，並重跑後續步驟")
    modes = result.add_mutually_exclusive_group()
    modes.add_argument("--dry-run", action="store_true", help="只列出指令與預期檔案，不執行")
    modes.add_argument("--check", action="store_true", help="唯讀驗收固定產物")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    session = args.session.expanduser().resolve()
    if not session.is_dir():
        say(f"錯誤：場次資料夾不存在：{session}")
        return 2
    if args.check:
        return run_check(session)
    try:
        saved = load_config(session)
        config = input_config(args, session, saved)
        if args.dry_run:
            return dry_run(session, config, args.from_step)
        if not config.get("recording") or not config.get("chat") or not config.get("notes"):
            say("錯誤：第一次執行需要 --recording、--chat、--notes；續跑可沿用 .post-live/run.json")
            return 2
        save_config(session, config)
        forced_index = next((i for i, (step, _) in enumerate(STEPS) if step == args.from_step), None)
        if forced_index is not None:
            for step, _ in STEPS[forced_index:]:
                marker = mark_path(session, step)
                if marker.exists():
                    marker.unlink()
        failures: list[tuple[str, str]] = []
        for step_index, (step, label) in enumerate(STEPS):
            if forced_index is not None and step_index < forced_index:
                say(f"略過較早步驟：{label}")
                continue
            if args.from_step is None and is_done(session, step):
                say(f"略過已完成步驟：{label}（標記存在）")
                continue
            say(f"開始步驟：{label}")
            try:
                if step == "archive":
                    stage_archive(session, config)
                elif step == "transcribe":
                    stage_transcribe(session, config)
                elif step == "normalize":
                    stage_normalize(session)
                elif step == "terms":
                    stage_terms(session)
                elif step == "segments":
                    completed = stage_segments(session)
                    if not completed:
                        say(f"步驟尚未完成：{label}；準備完成輸入後執行 --from segments")
                        say(f"結束步驟：{label}（等待人工切段計劃）")
                        continue
                elif step == "drafts":
                    stage_drafts(session, config)
                mark_done(session, step)
                say(f"結束步驟：{label}（完成標記已寫入）")
            except (WorkflowError, OSError, json.JSONDecodeError) as exc:
                message = str(exc)
                failures.append((step, message))
                say(f"失敗步驟：{label}；原因：{message}")
                say(f"接續方式：修正原因後執行 python3 {ROOT / 'run.py'} {session} --from {step}")
                say(f"結束步驟：{label}（未寫完成標記）")
        print_gates(session)
        if failures:
            say(f"流程有 {len(failures)} 個步驟失敗；已嘗試執行不依賴失敗步驟的草稿產生。")
            return 1
        return 0
    except WorkflowError as exc:
        say(f"錯誤：{exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
