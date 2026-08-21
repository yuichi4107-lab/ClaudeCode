from __future__ import annotations

import json
import multiprocessing
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from src import drive_mirror, pipeline, post_lock, queue_lib, topic_store
from src.config import CONFIG, Config
from src.state_io import file_lock
import src.config as config_module
import scripts.mirror_to_drive as mirror_script


def _consume_in_child(topic: str, slug: str) -> None:
    topic_store.consume_topic(topic, slug, slug, "beginner")


def _select_and_consume_in_child(result_queue) -> None:
    with file_lock(CONFIG.state_dir / "locks" / "generator.lock"):
        entry, _remaining = topic_store.next_topic_entry("beginner")
        time.sleep(0.1)
        topic_store.consume_topic(entry["topic"], entry["topic"], entry["topic"], "beginner")
        result_queue.put(entry["topic"])


class LocalControlPlaneTest(unittest.TestCase):
    def test_config_keeps_hot_paths_under_runtime(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            runtime = root / "runtime"
            mirror_root = root / "CloudStorage" / "YNFactory-cc"
            with (
                patch.object(config_module, "RUNTIME_DIR", runtime),
                patch.object(config_module, "DEFAULT_REPO_ROOT", mirror_root),
                patch.dict("os.environ", {"SHORTS_FACTORY_ROOT": str(root / "app")}, clear=False),
            ):
                cfg = Config()
            for path in (
                cfg.factory_dir,
                cfg.queue_dir,
                cfg.topics_path,
                cfg.outputs_dir,
                cfg.work_dir,
                cfg.logs_dir,
                cfg.sns_env_path,
            ):
                self.assertNotIn("CloudStorage", path.parts)
            self.assertIn("CloudStorage", cfg.drive_marketing_dir.parts)

    def test_runtime_readiness_rejects_drive_hot_path_before_stat(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Config()
            cfg.queue_dir = Path("/Users/test/Library/CloudStorage/provider/queue")
            with (
                patch.dict("os.environ", {"SHORTS_ALLOW_UNMIGRATED": "1"}, clear=False),
                patch.object(Path, "is_file", side_effect=AssertionError("stat must not run")),
                self.assertRaisesRegex(RuntimeError, "Drive path configured"),
            ):
                cfg.assert_runtime_ready()

    def test_config_rejects_drive_runtime_before_loading_files(self):
        drive_runtime = Path("/Users/test/Library/CloudStorage/provider/runtime")
        with (
            patch.object(config_module, "RUNTIME_DIR", drive_runtime),
            patch.object(config_module, "_load_yaml", side_effect=AssertionError("must not read")),
            self.assertRaisesRegex(RuntimeError, "SHORTS_RUNTIME_DIR must be local"),
        ):
            Config()

    def test_stale_queue_snapshots_merge_without_regressing_platforms(self):
        with tempfile.TemporaryDirectory() as td:
            state = Path(td)
            qdir = state / "queue"
            with (
                patch.object(queue_lib.CONFIG, "state_dir", state),
                patch.object(queue_lib.CONFIG, "queue_dir", qdir),
            ):
                item = {
                    "id": "item-1",
                    "status": "approved",
                    "history": [],
                    "platforms": {
                        "x": {"enabled": True, "status": "pending"},
                        "youtube": {"enabled": True, "status": "pending"},
                    },
                }
                queue_lib.save_item(item)
                first = queue_lib.load_item("item-1")
                stale = queue_lib.load_item("item-1")
                first["platforms"]["x"]["status"] = "posted"
                first["history"].append({"ts": "1", "event": "x:posted"})
                queue_lib.save_item(first)
                stale["platforms"]["youtube"]["status"] = "failed"
                stale["history"].append({"ts": "2", "event": "youtube:failed"})
                queue_lib.save_item(stale)
                saved = queue_lib.load_item("item-1")
                self.assertEqual("posted", saved["platforms"]["x"]["status"])
                self.assertEqual("failed", saved["platforms"]["youtube"]["status"])
                self.assertEqual(2, len(saved["history"]))

    def test_stale_queue_does_not_erase_receipt_or_terminal_posted_state(self):
        with tempfile.TemporaryDirectory() as td:
            state = Path(td)
            with (
                patch.object(queue_lib.CONFIG, "state_dir", state),
                patch.object(queue_lib.CONFIG, "queue_dir", state / "queue"),
            ):
                item = {
                    "id": "item-receipt",
                    "status": "ready_for_review",
                    "telegram": {"message_id": None},
                    "platforms": {"x": {"enabled": True, "status": "pending"}},
                    "history": [],
                }
                queue_lib.save_item(item)
                posted = queue_lib.load_item(item["id"])
                stale = queue_lib.load_item(item["id"])
                posted["telegram"]["message_id"] = 42
                posted["platforms"]["x"].update(
                    {"status": "posted", "url": "https://x.example/42"}
                )
                posted["status"] = "posted"
                queue_lib.save_item(posted)
                stale["telegram"]["message_id"] = None
                stale["platforms"]["x"]["status"] = "pending"
                stale["status"] = "skipped"
                queue_lib.save_item(stale)
                saved = queue_lib.load_item(item["id"])
                self.assertEqual(42, saved["telegram"]["message_id"])
                self.assertEqual("posted", saved["platforms"]["x"]["status"])
                self.assertEqual("https://x.example/42", saved["platforms"]["x"]["url"])
                self.assertEqual("posted", saved["status"])

    def test_save_preserves_nested_reference_for_followup_receipt(self):
        with tempfile.TemporaryDirectory() as td:
            state = Path(td)
            with (
                patch.object(queue_lib.CONFIG, "state_dir", state),
                patch.object(queue_lib.CONFIG, "queue_dir", state / "queue"),
            ):
                item = {
                    "id": "item-nested",
                    "status": "ready_for_review",
                    "telegram": {"message_id": None},
                    "platforms": {},
                    "history": [],
                }
                queue_lib.save_item(item)
                telegram = item["telegram"]
                telegram["preview_send_attempts"] = 1
                queue_lib.save_item(item)
                self.assertIs(telegram, item["telegram"])
                telegram["message_id"] = 77
                queue_lib.save_item(item)
                self.assertEqual(77, queue_lib.load_item(item["id"])["telegram"]["message_id"])

    @unittest.skipUnless("fork" in multiprocessing.get_all_start_methods(), "fork required")
    def test_topic_transactions_are_process_safe(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            topics_path = root / "topics.json"
            cache_path = root / "cache.json"
            lock_path = root / "topics.lock"
            topics_path.write_text(
                json.dumps(
                    {
                        "backlog": [
                            {"topic": "topic-a", "difficulty": "beginner"},
                            {"topic": "topic-b", "difficulty": "beginner"},
                        ],
                        "used": [],
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch.object(topic_store.CONFIG, "topics_path", topics_path),
                patch.object(topic_store, "TOPICS_CACHE_PATH", cache_path),
                patch.object(topic_store, "TOPICS_LOCK_PATH", lock_path),
            ):
                ctx = multiprocessing.get_context("fork")
                processes = [
                    ctx.Process(target=_consume_in_child, args=("topic-a", "slug-a")),
                    ctx.Process(target=_consume_in_child, args=("topic-b", "slug-b")),
                ]
                for process in processes:
                    process.start()
                for process in processes:
                    process.join(5)
                    self.assertEqual(0, process.exitcode)
                data = json.loads(topics_path.read_text(encoding="utf-8"))
                self.assertEqual([], data["backlog"])
                self.assertEqual({"slug-a", "slug-b"}, {entry["slug"] for entry in data["used"]})

    @unittest.skipUnless("fork" in multiprocessing.get_all_start_methods(), "fork required")
    def test_generator_lock_prevents_parallel_topic_selection(self):
        with tempfile.TemporaryDirectory() as td:
            state = Path(td)
            topics_path = state / "topics.json"
            topics_path.write_text(
                json.dumps(
                    {
                        "backlog": [
                            {"topic": "顧客インタビューから改善案を作る方法", "difficulty": "beginner"},
                            {"topic": "経理の請求書入力を自動化する方法", "difficulty": "beginner"},
                        ],
                        "used": [],
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch.object(CONFIG, "state_dir", state),
                patch.object(topic_store.CONFIG, "topics_path", topics_path),
                patch.object(topic_store, "TOPICS_CACHE_PATH", state / "cache.json"),
                patch.object(topic_store, "TOPICS_LOCK_PATH", state / "topics.lock"),
            ):
                ctx = multiprocessing.get_context("fork")
                results = ctx.Queue()
                processes = [ctx.Process(target=_select_and_consume_in_child, args=(results,)) for _ in range(2)]
                for process in processes:
                    process.start()
                for process in processes:
                    process.join(5)
                    self.assertEqual(0, process.exitcode)
                self.assertEqual(
                    {"顧客インタビューから改善案を作る方法", "経理の請求書入力を自動化する方法"},
                    {results.get(timeout=1), results.get(timeout=1)},
                )

    def test_output_commit_is_complete_before_publication(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            work = root / "work"
            work.mkdir()
            for name, content in (
                ("final.mp4", b"video"),
                ("script.json", b"{}"),
                ("subtitles.ass", b"subs"),
                ("quality_report.json", b"{}"),
            ):
                (work / name).write_bytes(content)
            with patch.object(pipeline.CONFIG, "outputs_dir", root / "outputs"):
                result = pipeline.save_outputs(
                    "item-1",
                    work / "final.mp4",
                    work / "subtitles.ass",
                    work,
                    [],
                    [],
                    "title",
                    {"caption": "caption", "hashtags": ["#tag"]},
                )
            self.assertTrue((result / ".complete.json").is_file())
            self.assertEqual(b"video", (result / "final.mp4").read_bytes())
            self.assertFalse(any(path.name.startswith(".item-1.") for path in result.parent.iterdir()))

    def test_mirror_converges_local_state_and_maps_queue_paths(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            runtime = root / "runtime"
            state = runtime / "state"
            qdir = state / "queue"
            outputs = runtime / "outputs"
            out = outputs / "item-1"
            drive = root / "drive"
            qdir.mkdir(parents=True)
            out.mkdir(parents=True)
            (out / "final.mp4").write_bytes(b"video")
            (out / ".complete.json").write_text("{}", encoding="utf-8")
            (state / "topics.json").write_text('{"backlog": [], "used": []}', encoding="utf-8")
            marker = state / "migration-v2-local-control-plane.json"
            marker.write_text("{}", encoding="utf-8")
            queue = {
                "id": "item-1",
                "_revision": 3,
                "status": "ready_for_review",
                "video": {"path": str(out / "final.mp4"), "local_path": str(out / "final.mp4")},
                "output_dir": str(out),
                "quality": {"report_path": str(out / "quality_report.json")},
            }
            (qdir / "item-1.json").write_text(json.dumps(queue), encoding="utf-8")
            patches = (
                patch.object(CONFIG, "runtime_dir", runtime),
                patch.object(CONFIG, "factory_dir", root / "app"),
                patch.object(CONFIG, "state_dir", state),
                patch.object(CONFIG, "marketing_dir", state),
                patch.object(CONFIG, "queue_dir", qdir),
                patch.object(CONFIG, "topics_path", state / "topics.json"),
                patch.object(CONFIG, "outputs_dir", outputs),
                patch.object(CONFIG, "work_dir", runtime / "work"),
                patch.object(CONFIG, "drive_marketing_dir", drive / "state"),
                patch.object(CONFIG, "drive_outputs_dir", drive / "outputs"),
                patch.object(CONFIG, "mirror_dir", runtime / "drive_mirror"),
                patch.object(CONFIG, "mirror_manifest_path", runtime / "drive_mirror" / "manifest.json"),
                patch.object(CONFIG, "runtime_ready_marker", marker),
            )
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9], patches[10], patches[11], patches[12]:
                result = drive_mirror.mirror_once()
                second = drive_mirror.mirror_once()
            self.assertTrue(result["ok"])
            self.assertEqual(0, second["copied"])
            mirrored = json.loads((drive / "state" / "queue" / "item-1.json").read_text(encoding="utf-8"))
            self.assertEqual(str(drive / "outputs" / "item-1"), mirrored["output_dir"])
            self.assertNotIn("local_path", mirrored["video"])
            self.assertEqual(b"video", (drive / "outputs" / "item-1" / "final.mp4").read_bytes())

    def test_post_lock_is_kernel_owned_and_released_on_fd_close(self):
        with tempfile.TemporaryDirectory() as td, patch.object(CONFIG, "runtime_dir", Path(td)):
            fd, path = post_lock.acquire("item-1")
            self.assertIsNotNone(fd)
            self.assertTrue(post_lock.active("item-1"))
            second_fd, _ = post_lock.acquire("item-1")
            self.assertIsNone(second_fd)
            post_lock.release(fd, path)
            self.assertFalse(post_lock.active("item-1"))

    def test_mirror_supervisor_records_timeout_without_raising(self):
        with tempfile.TemporaryDirectory() as td:
            status_path = Path(td) / "status.json"
            with (
                patch.object(mirror_script, "STATUS_PATH", status_path),
                patch.object(
                    mirror_script.subprocess,
                    "run",
                    side_effect=subprocess.TimeoutExpired(cmd=["worker"], timeout=0.1),
                ),
            ):
                result = mirror_script.supervise(0.1)
            self.assertFalse(result["ok"])
            self.assertIn("TimeoutExpired", result["error"])
            self.assertTrue(status_path.is_file())

    def test_generate_and_approval_launchd_have_no_drive_path(self):
        root = Path(__file__).resolve().parents[1]
        self.assertNotIn("CloudStorage", (root / "scripts" / "run_generate.sh").read_text())
        for name in (
            "com.ynfactory.shorts-generate.plist",
            "com.ynfactory.shorts-approval.plist",
        ):
            self.assertNotIn("CloudStorage", (root / "launchd" / name).read_text())


if __name__ == "__main__":
    unittest.main()
