import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "run.py"


class RunIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="post-live-fake-", dir=ROOT)
        self.workspace = Path(self.temporary.name)
        self.session = self.workspace / "1112-fake-live"
        self.session.mkdir()
        inputs = self.workspace / "inputs"
        inputs.mkdir()
        self.recording = inputs / "recording.mp4"
        self.chat = inputs / "chat.sbv"
        self.notes = inputs / "notes.docx"
        self.recording.write_bytes(b"fake recording")
        self.chat.write_text("聊天測試\n", encoding="utf-8")
        self.notes.write_bytes(b"fake notes")
        (self.session / "會後記錄-1112.md").write_text("# 會後記錄 1112：假場次驗證\n", encoding="utf-8")
        (self.session / "terms.md").write_text("口語錯字 → 校正後用語\n", encoding="utf-8")
        (self.session / "切段計劃.tsv").write_text("第1段-測試\t0-1\n", encoding="utf-8")

        self.log = self.workspace / "commands.log"
        fake_ffmpeg = self.workspace / "fake_ffmpeg.py"
        fake_ffmpeg.write_text(
            "import os, pathlib, sys\n"
            "pathlib.Path(os.environ['FAKE_LOG']).open('a', encoding='utf-8').write('ffmpeg\\n')\n"
            "target = pathlib.Path(sys.argv[-1])\n"
            "target.parent.mkdir(parents=True, exist_ok=True)\n"
            "target.write_bytes(b'fake output')\n",
            encoding="utf-8",
        )
        fake_whisper = self.workspace / "fake_whisper.py"
        fake_whisper.write_text(
            "import json, os, pathlib, sys\n"
            "pathlib.Path(os.environ['FAKE_LOG']).open('a', encoding='utf-8').write('whisper\\n')\n"
            "out = pathlib.Path(sys.argv[sys.argv.index('--output_dir') + 1])\n"
            "out.mkdir(parents=True, exist_ok=True)\n"
            "data = {'segments': [{'start': 0.0, 'end': 1.0, 'text': '口語錯字', 'words': [{'word': '口語錯字', 'start': 0.0, 'end': 1.0}]}]}\n"
            "(out / 'audio.json').write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')\n"
            "(out / 'audio.txt').write_text('口語錯字', encoding='utf-8')\n"
            "(out / 'audio.srt').write_text('1\\n00:00:00,000 --> 00:00:01,000\\n口語錯字\\n', encoding='utf-8')\n",
            encoding="utf-8",
        )
        fake_normalize = self.workspace / "fake_normalize.py"
        fake_normalize.write_text(
            "import os, pathlib, sys\n"
            "pathlib.Path(os.environ['FAKE_LOG']).open('a', encoding='utf-8').write('normalize\\n')\n"
            "path = pathlib.Path('work/audio.json')\n"
            "if not path.is_file(): raise SystemExit('缺少測試音訊 JSON')\n",
            encoding="utf-8",
        )
        self.env = os.environ.copy()
        self.env.update(
            {
                "FAKE_LOG": str(self.log),
                "POST_LIVE_FFMPEG_CMD": f"{sys.executable} {fake_ffmpeg}",
                "POST_LIVE_WHISPER_CMD": f"{sys.executable} {fake_whisper}",
                "POST_LIVE_NORMALIZE_CMD": f"{sys.executable} {fake_normalize}",
                "POST_LIVE_APPLY_TERMS_CMD": f"{sys.executable} {ROOT / 'apply-terms.py'}",
                "POST_LIVE_SRT_SLICE_CMD": f"{sys.executable} {ROOT / 'srt-slice.py'}",
            }
        )

    def tearDown(self):
        self.temporary.cleanup()

    def invoke(self, *arguments):
        return subprocess.run(
            [sys.executable, str(RUNNER), str(self.session), *map(str, arguments)],
            cwd=ROOT,
            env=self.env,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_complete_run_markers_resume_and_drafts(self):
        first = self.invoke(
            "--recording", self.recording,
            "--chat", self.chat,
            "--notes", self.notes,
            "--online", "14",
            "--line", "205",
        )
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertIn("結束步驟：產生會後草稿包", first.stdout)
        archive = self.session / "直播存檔-1112"
        markers = self.session / ".post-live" / "steps"
        for name in ("archive", "transcribe", "normalize", "terms", "segments", "drafts"):
            self.assertTrue((markers / f"{name}.done").is_file(), name)
        corrected = (archive / "逐字稿-成品.txt").read_text(encoding="utf-8")
        self.assertIn("校正後用語", corrected)
        self.assertTrue((archive / "切段" / "第01段-第1段-測試.mp4").is_file())
        self.assertTrue((archive / "切段" / "第01段-第1段-測試.srt").is_file())
        self.assertEqual(
            sorted(path.name for path in (self.session / "會後草稿").iterdir()),
            sorted(["活動頁變更.md", "投票頁變更.md", "LINE記事本.md", "會後公告.md", "FB留言.md", "數字紀錄列.md"]),
        )
        number_row = (self.session / "會後草稿" / "數字紀錄列.md").read_text(encoding="utf-8")
        self.assertIn("| 1112 | 假場次驗證 | 205 | 未提供 | 未提供 | 14 |", number_row)
        self.assertIn("【待填：一句話摘要】", (self.session / "會後草稿" / "會後公告.md").read_text(encoding="utf-8"))

        log_before = self.log.read_text(encoding="utf-8").splitlines()
        archive_marker = (markers / "archive.done").read_text(encoding="utf-8")
        resumed = self.invoke("--from", "terms")
        self.assertEqual(resumed.returncode, 0, resumed.stdout + resumed.stderr)
        log_after = self.log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(log_after.count("whisper"), log_before.count("whisper"))
        self.assertEqual(log_after.count("normalize"), log_before.count("normalize"))
        self.assertEqual((markers / "archive.done").read_text(encoding="utf-8"), archive_marker)
        self.assertIn("略過較早步驟：歸檔", resumed.stdout)
        self.assertIn("開始步驟：套用用詞表", resumed.stdout)


if __name__ == "__main__":
    unittest.main()
