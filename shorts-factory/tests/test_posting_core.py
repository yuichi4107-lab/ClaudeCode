from __future__ import annotations

import errno
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from src.logging_utils import redact_secrets
from src.fs_retry import retry_io
from src import approval_bot, drive_guard, jp_text, notify, pipeline, platform_copy, queue_lib, script_gen, topic_store
from src.pipeline import result_summary, scheduled_difficulty
from src.platforms import poster


def make_item() -> dict:
    return {
        "id": "item-1",
        "title": "title",
        "caption": (
            "AI導入で成果を出すには、ツール名よりも最初に任せる業務を決めることが大事です。"
            "小さく試して、結果を見て、社内に広げる順番を作ります。"
        ),
        "hashtags": ["#AI活用", "#生成AI", "#ChatGPT", "#業務効率化"],
        "video": {"path": "/tmp/final.mp4"},
        "platforms": {
            "x": {"enabled": True, "status": "pending", "url": None, "error": None},
            "youtube": {"enabled": True, "status": "pending", "url": None, "error": None},
            "instagram": {"enabled": False, "status": "pending", "url": None, "error": None},
            "tiktok": {"enabled": False, "status": "pending", "url": None, "error": None},
        },
        "history": [],
    }


class FakeQueue:
    @staticmethod
    def save_item(item):
        return item

    @staticmethod
    def mark_platform(item, platform, status, url=None, error=None):
        info = item["platforms"][platform]
        info["status"] = status
        if url:
            info["url"] = url
        if status == "posted":
            info["error"] = None
        elif error:
            info["error"] = error
        return item

    @staticmethod
    def transition(item, status, event=None):
        item["status"] = status
        item.setdefault("history", []).append({"event": event or status})
        return item


class FakeNotify:
    messages: list[str] = []

    @classmethod
    def send_message(cls, text):
        cls.messages.append(text)


class PostingCoreTest(unittest.TestCase):
    def setUp(self):
        FakeNotify.messages = []
        self._runtime_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._runtime_tmp.cleanup)
        runtime_patch = patch.object(poster.CONFIG, "runtime_dir", Path(self._runtime_tmp.name))
        runtime_patch.start()
        self.addCleanup(runtime_patch.stop)

    def test_redacts_telegram_tokens(self):
        raw = "https://api.telegram.org/bot123456789:ABCdef_012345678901234567890/getUpdates"
        self.assertNotIn("ABCdef", redact_secrets(raw))
        self.assertIn("[REDACTED]", redact_secrets(raw))
        relative = "/bot123456789:ABCdef_012345678901234567890/getUpdates"
        self.assertNotIn("ABCdef", redact_secrets(relative))

    def test_partial_unknown_failure_requires_reconciliation(self):
        item = make_item()
        posters = {
            "x": lambda item: "https://x.example/post/1",
            "youtube": lambda item: (_ for _ in ()).throw(RuntimeError("boom 123456789:ABCdef_012345678901234567890")),
        }
        with (
            patch.object(poster, "POSTERS", posters),
            patch.object(poster, "_retry_settings", return_value=(0, 0.0)),
        ):
            updated = poster.post_item(item, FakeQueue, FakeNotify)
        self.assertEqual(updated["status"], "partial_failed")
        self.assertEqual(updated["platforms"]["x"]["status"], "posted")
        self.assertEqual(updated["platforms"]["youtube"]["status"], "failed")
        self.assertTrue(updated["platforms"]["youtube"]["non_retryable"])
        self.assertTrue(updated["platforms"]["youtube"]["reconcile_required"])
        self.assertNotIn("ABCdef", updated["platforms"]["youtube"]["error"])
        self.assertNotIn("ABCdef", FakeNotify.messages[-1])

    def test_retry_skips_already_posted_platforms(self):
        item = make_item()
        item["platforms"]["x"]["status"] = "posted"
        item["platforms"]["x"]["url"] = "https://x.example/post/1"
        calls: list[str] = []

        def x_post(_item):
            calls.append("x")
            return "duplicate"

        def yt_post(_item):
            calls.append("youtube")
            return "https://youtube.example/short/1"

        with (
            patch.object(poster, "POSTERS", {"x": x_post, "youtube": yt_post}),
            patch.object(poster, "_retry_settings", return_value=(0, 0.0)),
        ):
            updated = poster.post_item(item, FakeQueue, FakeNotify)
        self.assertEqual(calls, ["youtube"])
        self.assertEqual(updated["status"], "posted")

    def test_auto_retry_only_failed_platforms(self):
        item = make_item()
        calls: list[str] = []
        youtube_attempts = {"count": 0}

        def x_post(_item):
            calls.append("x")
            return "https://x.example/post/1"

        def yt_post(_item):
            calls.append("youtube")
            youtube_attempts["count"] += 1
            if youtube_attempts["count"] == 1:
                raise RuntimeError("local media file not found")
            return "https://youtube.example/short/1"

        with (
            patch.object(poster, "POSTERS", {"x": x_post, "youtube": yt_post}),
            patch.object(poster, "_retry_settings", return_value=(2, 0.0)),
        ):
            updated = poster.post_item(item, FakeQueue, FakeNotify)

        self.assertEqual(calls, ["x", "youtube", "youtube"])
        self.assertEqual(updated["status"], "posted")
        self.assertEqual(updated["platforms"]["x"]["attempts"], 1)
        self.assertEqual(updated["platforms"]["youtube"]["attempts"], 2)
        self.assertIn("自動再投稿 1/2", FakeNotify.messages[-1])

    def test_ledger_intent_exists_before_external_submit(self):
        item = make_item()
        item["platforms"]["youtube"]["enabled"] = False
        seen: list[str] = []

        def x_post(_item):
            seen.append(poster._ledger_platform_entry(item["id"], "x").get("status"))
            return "https://x.example/post/intent"

        with (
            patch.object(poster, "POSTERS", {"x": x_post}),
            patch.object(poster, "_retry_settings", return_value=(0, 0.0)),
        ):
            updated = poster.post_item(item, FakeQueue, FakeNotify)

        self.assertEqual(["attempting"], seen)
        self.assertEqual("posted", poster._ledger_platform_entry(item["id"], "x")["status"])
        self.assertEqual("posted", updated["status"])

    def test_uncertain_submit_failure_stops_without_automatic_repost(self):
        item = make_item()
        item["platforms"]["youtube"]["enabled"] = False
        calls: list[str] = []

        def x_post(_item):
            calls.append("x")
            raise TimeoutError("timed out after submit")

        with (
            patch.object(poster, "POSTERS", {"x": x_post}),
            patch.object(poster, "_retry_settings", return_value=(2, 0.0)),
        ):
            updated = poster.post_item(item, FakeQueue, FakeNotify)

        self.assertEqual(["x"], calls)
        self.assertTrue(updated["platforms"]["x"]["non_retryable"])
        self.assertTrue(updated["platforms"]["x"]["reconcile_required"])
        self.assertEqual(
            "reconcile_required",
            poster._ledger_platform_entry(item["id"], "x")["status"],
        )
        self.assertIn("自動再投稿停止", FakeNotify.messages[-1])

    def test_attempting_ledger_blocks_blind_repost_after_worker_crash(self):
        item = make_item()
        item["platforms"]["youtube"]["enabled"] = False
        calls: list[str] = []
        poster._record_ledger_intent(item["id"], "x")

        with (
            patch.object(poster, "POSTERS", {"x": lambda _item: calls.append("x") or "duplicate"}),
            patch.object(poster, "_retry_settings", return_value=(2, 0.0)),
        ):
            updated = poster.post_item(item, FakeQueue, FakeNotify)

        self.assertEqual([], calls)
        self.assertTrue(updated["platforms"]["x"]["reconcile_required"])
        self.assertEqual("failed", updated["status"])

    def test_corrupt_posting_ledger_fails_closed_before_external_submit(self):
        item = make_item()
        item["platforms"]["youtube"]["enabled"] = False
        poster._posting_ledger_path(item["id"]).write_text("{", encoding="utf-8")
        calls: list[str] = []
        with (
            patch.object(poster, "POSTERS", {"x": lambda _item: calls.append("x") or "duplicate"}),
            self.assertRaises(poster.PostingLedgerError),
        ):
            poster.post_item(item, FakeQueue, FakeNotify, retry_attempts=0, retry_delay_sec=0)
        self.assertEqual([], calls)

    def test_posting_video_rejects_drive_path_before_stat(self):
        item = make_item()
        item["video"] = {
            "path": "/Users/test/Library/CloudStorage/provider/final.mp4",
            "upload_path": "/Users/test/Library/CloudStorage/provider/upload.mp4",
        }
        with (
            patch.object(Path, "exists", side_effect=AssertionError("stat must not run")),
            self.assertRaises(drive_guard.DriveHotPathError),
        ):
            poster.posting_video_path(item)

    def test_retry_override_disables_inner_retries(self):
        item = make_item()
        item["platforms"]["x"]["enabled"] = False
        calls: list[str] = []

        def yt_post(_item):
            calls.append("youtube")
            raise RuntimeError("temporary upload error")

        with patch.object(poster, "POSTERS", {"youtube": yt_post}):
            updated = poster.post_item(
                item,
                FakeQueue,
                FakeNotify,
                retry_attempts=0,
                retry_delay_sec=0,
            )

        self.assertEqual(calls, ["youtube"])
        self.assertEqual(updated["status"], "failed")

    def test_auto_recovery_runs_after_two_retries_and_adds_retry(self):
        item = make_item()
        item["platforms"]["x"]["enabled"] = False
        calls: list[str | None] = []
        recovered: list[list[str]] = []

        def yt_post(_item):
            calls.append(_item.get("video", {}).get("upload_path"))
            if len(calls) <= 3:
                raise RuntimeError("Resource deadlock avoided")
            return "https://youtube.example/short/recovered"

        def fake_recover(_item, platforms, _queue_lib):
            recovered.append(list(platforms))
            _item.setdefault("video", {})["upload_path"] = "/tmp/cache/final.mp4"
            return [
                {
                    "platform": platforms[0],
                    "cause": "media_io",
                    "actions": ["local_media:/tmp/cache/final.mp4"],
                    "recovered": True,
                }
            ]

        with (
            patch.object(poster, "POSTERS", {"youtube": yt_post}),
            patch.object(poster, "_retry_settings", return_value=(2, 0.0)),
            patch.object(poster, "_recovery_settings", return_value=(True, 2, 1, 2)),
            patch.object(poster, "recover_failed_platforms", side_effect=fake_recover),
        ):
            updated = poster.post_item(item, FakeQueue, FakeNotify)

        self.assertEqual(len(calls), 4)
        self.assertEqual(calls[-1], "/tmp/cache/final.mp4")
        self.assertEqual(recovered, [["youtube"]])
        self.assertEqual(updated["status"], "posted")
        self.assertIn("自動原因確認", FakeNotify.messages[-1])
        self.assertIn("自動再投稿 3/3", FakeNotify.messages[-1])

    def test_deferred_retry_runs_recovery_when_attempts_already_high(self):
        item = make_item()
        item["platforms"]["x"]["enabled"] = False
        item["platforms"]["youtube"]["status"] = "failed"
        item["platforms"]["youtube"]["attempts"] = 3
        item["platforms"]["youtube"]["error"] = "Resource deadlock avoided"
        recovered = {"ran": False}
        calls: list[str | None] = []

        def yt_post(_item):
            calls.append(_item.get("video", {}).get("upload_path"))
            return "https://youtube.example/short/deferred"

        def fake_recover(_item, platforms, _queue_lib):
            recovered["ran"] = True
            self.assertEqual(platforms, ["youtube"])
            _item.setdefault("video", {})["upload_path"] = "/tmp/cache/deferred.mp4"
            return [
                {
                    "platform": "youtube",
                    "cause": "media_io",
                    "actions": ["local_media:/tmp/cache/deferred.mp4"],
                    "recovered": True,
                }
            ]

        with (
            patch.object(poster, "POSTERS", {"youtube": yt_post}),
            patch.object(poster, "_recovery_settings", return_value=(True, 2, 1, 2)),
            patch.object(poster, "recover_failed_platforms", side_effect=fake_recover),
        ):
            updated = poster.post_item(
                item,
                FakeQueue,
                FakeNotify,
                retry_attempts=0,
                retry_delay_sec=0,
            )

        self.assertTrue(recovered["ran"])
        self.assertEqual(calls, ["/tmp/cache/deferred.mp4"])
        self.assertEqual(updated["status"], "posted")
        self.assertNotIn("自動再投稿", FakeNotify.messages[-1])

    def test_diagnose_posting_error_classifies_common_causes(self):
        self.assertEqual(
            poster.diagnose_posting_error("instagram", "OSError: Resource deadlock avoided"),
            "media_io",
        )
        self.assertEqual(
            poster.diagnose_posting_error("x", "dotenv/parser.py: Resource deadlock avoided"),
            "credential_io",
        )
        self.assertEqual(
            poster.diagnose_posting_error("youtube", "accounts.google.com ログインが必要です"),
            "session_expired",
        )
        self.assertEqual(
            poster.diagnose_posting_error("tiktok", "Timeout while waiting for selector"),
            "browser_ui_stuck",
        )
        self.assertEqual(
            poster.diagnose_posting_error("instagram", "connection aborted by peer"),
            "network_transient",
        )

    def test_platform_copy_is_platform_specific(self):
        item = make_item()
        copies = platform_copy.build_platform_copy_set(item)

        self.assertIn("最初の1業務", copies["x"]["text"])
        self.assertNotIn("utm_source=youtube", copies["x"]["text"])
        self.assertIn("保存して", copies["instagram"]["caption"])
        self.assertIn("プロフィールの無料診断", copies["tiktok"]["caption"])
        self.assertIn("utm_source=youtube", copies["youtube"]["description"])
        self.assertIn("音声・映像はAIで自動生成しています", copies["youtube"]["description"])

    def test_queue_item_can_limit_enabled_platforms(self):
        script = {
            "title": "title",
            "caption": "AI導入の実務向けテストです。小さく試して、結果を見て、社内に広げます。",
            "hashtags": ["#AI活用", "#生成AI", "#業務効率化"],
            "target_platform": "instagram",
        }
        with tempfile.TemporaryDirectory() as td:
            with patch.object(queue_lib.CONFIG, "queue_dir", Path(td)):
                item = queue_lib.new_item(
                    "item-platform-only",
                    "topic",
                    script,
                    Path("/tmp/final.mp4"),
                    42.0,
                    4.2,
                    Path("/tmp/quality.json"),
                    True,
                    0.02,
                    Path("/tmp/out"),
                    enabled_platforms=["instagram"],
                    variant_group_id="group-1",
                )

        self.assertEqual(item["variant_group_id"], "group-1")
        self.assertTrue(item["platforms"]["instagram"]["enabled"])
        self.assertFalse(item["platforms"]["x"]["enabled"])
        self.assertFalse(item["platforms"]["youtube"]["enabled"])
        self.assertFalse(item["platforms"]["tiktok"]["enabled"])

    def test_produce_platform_variants_queues_one_item_per_enabled_platform(self):
        old_platforms = pipeline.CONFIG.cfg["queue"].get("platforms")
        pipeline.CONFIG.cfg["queue"]["platforms"] = ["x", "instagram"]
        candidates: list[dict] = []
        queued: list[tuple[str, list[str] | None, str | None]] = []
        transitions: list[tuple[str, str]] = []

        def fake_candidate(topic_entry, difficulty, attempt, target_platform, item_suffix=None):
            candidate = {
                "item_id": f"{target_platform}-item",
                "out_dir": Path("/tmp") / f"{target_platform}-item",
                "report": {
                    "pass": True,
                    "duration": 42.0,
                    "size_mb": 4.2,
                    "accuracy": {"avg_cer": 0.02, "failed_indices": []},
                    "checks": [],
                },
                "title": f"{target_platform} title",
                "topic": topic_entry["topic"],
                "script": {
                    "title": f"{target_platform} title",
                    "caption": "AI導入の実務向けテストです。小さく試して、結果を見て、社内に広げます。",
                    "hashtags": ["#AI活用", "#生成AI", "#業務効率化"],
                    "target_platform": target_platform,
                    "difficulty": difficulty,
                },
                "attempt": attempt,
            }
            candidates.append(candidate)
            return candidate

        def fake_new_item(item_id, *_args, **kwargs):
            queued.append((item_id, kwargs.get("enabled_platforms"), kwargs.get("variant_group_id")))
            return {
                "id": item_id,
                "title": item_id,
                "quality": {"pass": True, "avg_cer": 0.02},
                "review": {},
                "telegram": {},
                "platforms": {
                    "x": {"enabled": item_id.startswith("x")},
                    "instagram": {"enabled": item_id.startswith("instagram")},
                },
                "history": [],
            }

        def fake_transition(item, status, event=None):
            transitions.append((item["id"], status))
            item["status"] = status
            return item

        try:
            with (
                patch.object(pipeline, "_build_candidate", side_effect=fake_candidate),
                patch.object(pipeline.topic_store, "next_topic_entry", return_value=({"topic": "topic", "difficulty": "intermediate"}, 99)),
                patch.object(pipeline.topic_store, "consume_topic", return_value=98),
                patch.object(pipeline.queue_lib, "new_item", side_effect=fake_new_item),
                patch.object(pipeline.queue_lib, "save_item"),
                patch.object(pipeline.queue_lib, "transition", side_effect=fake_transition),
            ):
                result = pipeline.produce_platform_variants(difficulty="intermediate")
        finally:
            pipeline.CONFIG.cfg["queue"]["platforms"] = old_platforms

        self.assertEqual([c["script"]["target_platform"] for c in candidates], ["x", "instagram"])
        self.assertEqual([q[0] for q in queued], ["x-item", "instagram-item"])
        self.assertEqual(queued[0][1], ["x"])
        self.assertEqual(queued[1][1], ["instagram"])
        self.assertTrue(queued[0][2])
        self.assertEqual(queued[0][2], queued[1][2])
        self.assertEqual(transitions, [("x-item", "ready_for_review"), ("instagram-item", "ready_for_review")])
        self.assertTrue(result["platform_variants"])
        self.assertEqual([item["platform"] for item in result["items"]], ["x", "instagram"])

    def test_produce_platform_variants_retries_failed_platform_generation(self):
        old_platforms = pipeline.CONFIG.cfg["queue"].get("platforms")
        old_retry_attempts = pipeline.CONFIG.cfg.setdefault("content", {}).get("platform_generation_retry_attempts")
        pipeline.CONFIG.cfg["queue"]["platforms"] = ["x", "instagram"]
        pipeline.CONFIG.cfg["content"]["platform_generation_retry_attempts"] = 2
        calls: list[str] = []
        queued: list[str] = []

        def fake_candidate(platform: str) -> dict:
            return {
                "item_id": f"{platform}-item",
                "out_dir": Path("/tmp") / f"{platform}-item",
                "report": {
                    "pass": True,
                    "duration": 42.0,
                    "size_mb": 4.2,
                    "accuracy": {"avg_cer": 0.02, "failed_indices": []},
                    "checks": [],
                },
                "title": f"{platform} title",
                "topic": "topic",
                "script": {
                    "title": f"{platform} title",
                    "caption": "AI導入の実務向けテストです。小さく試して、結果を見て、社内に広げます。",
                    "hashtags": ["#AI活用", "#生成AI", "#業務効率化"],
                    "target_platform": platform,
                    "difficulty": "intermediate",
                },
                "attempt": 1,
            }

        def fake_generate(_topic_entry, _difficulty, target_platform, item_suffix=None):
            calls.append(target_platform)
            if target_platform == "instagram" and calls.count("instagram") == 1:
                raise RuntimeError("temporary script validation failure")
            return fake_candidate(target_platform), 0

        def fake_new_item(item_id, *_args, **_kwargs):
            queued.append(item_id)
            return {
                "id": item_id,
                "title": item_id,
                "quality": {"pass": True, "avg_cer": 0.02},
                "review": {},
                "telegram": {},
                "platforms": {},
                "history": [],
            }

        try:
            with (
                patch.object(pipeline, "_generate_passable_candidate", side_effect=fake_generate),
                patch.object(pipeline.topic_store, "next_topic_entry", return_value=({"topic": "topic", "difficulty": "intermediate"}, 99)),
                patch.object(pipeline.topic_store, "consume_topic", return_value=98),
                patch.object(pipeline.queue_lib, "new_item", side_effect=fake_new_item),
                patch.object(pipeline.queue_lib, "save_item"),
                patch.object(pipeline.queue_lib, "transition", side_effect=FakeQueue.transition),
            ):
                result = pipeline.produce_platform_variants(difficulty="intermediate")
        finally:
            pipeline.CONFIG.cfg["queue"]["platforms"] = old_platforms
            if old_retry_attempts is None:
                pipeline.CONFIG.cfg["content"].pop("platform_generation_retry_attempts", None)
            else:
                pipeline.CONFIG.cfg["content"]["platform_generation_retry_attempts"] = old_retry_attempts

        self.assertEqual(calls, ["x", "instagram", "instagram"])
        self.assertEqual(queued, ["x-item", "instagram-item"])
        self.assertEqual([item["platform"] for item in result["items"]], ["x", "instagram"])

    def test_post_x_uses_platform_specific_copy(self):
        item = make_item()
        seen = {"text": None, "video_path": None}

        def fake_post(text, video_path):
            seen["text"] = text
            seen["video_path"] = video_path
            return "https://x.example/post/1"

        with patch.object(poster, "_post_x_direct", side_effect=fake_post):
            url = poster.post_x(item)

        self.assertEqual(url, "https://x.example/post/1")
        self.assertIn("最初の1業務", seen["text"])
        self.assertNotIn("保存して", seen["text"])
        self.assertEqual(seen["video_path"], Path("/tmp/final.mp4"))

    def test_posting_prefers_runtime_video_copy(self):
        item = make_item()
        with tempfile.TemporaryDirectory() as td:
            runtime = Path(td)
            local_video = runtime / "out-1" / "final.mp4"
            local_video.parent.mkdir()
            local_video.write_bytes(b"video")
            item["video"]["path"] = "/Drive/out/out-1/final.mp4"
            item["output_dir"] = "/Drive/out/out-1"

            with patch.object(poster.CONFIG, "work_dir", runtime):
                self.assertEqual(poster.posting_video_path(item), local_video)

    def test_posting_prefers_upload_cache_path(self):
        item = make_item()
        with tempfile.TemporaryDirectory() as td:
            cache_video = Path(td) / "upload.mp4"
            cache_video.write_bytes(b"video")
            item["video"]["upload_path"] = str(cache_video)

            self.assertEqual(poster.posting_video_path(item), cache_video)

    def test_instagram_reuses_recent_matching_post(self):
        item = make_item()
        calls = {"post": 0}

        def fake_graph_get(_path, _token, _params):
            return {
                "data": [
                    {
                        "id": "media-1",
                        "permalink": "https://instagram.example/reel/existing",
                        "caption": platform_copy.copy_for_platform(item, "instagram")["caption"],
                        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S%z"),
                    }
                ]
            }

        def fake_post(*_args):
            calls["post"] += 1
            return {"status": "posted", "permalink": "https://instagram.example/reel/new"}

        with (
            patch.object(
                poster,
                "_load_sns_env",
                return_value={"META_IG_USER_ID": "ig-1", "META_ACCESS_TOKEN": "token"},
            ),
            patch.object(poster, "_meta_graph_get", side_effect=fake_graph_get),
            patch.object(poster, "_post_instagram_reels", side_effect=fake_post),
        ):
            self.assertEqual(
                poster.post_instagram(item),
                "https://instagram.example/reel/existing",
            )
        self.assertEqual(calls["post"], 0)

    def test_instagram_posts_through_direct_meta_api(self):
        item = make_item()
        calls = {"post": 0}
        seen = {"video_path": None}

        def fake_post(_caption, _video_path, _env):
            calls["post"] += 1
            seen["video_path"] = _video_path
            return {"status": "posted", "permalink": "https://instagram.example/reel/1"}

        with (
            patch.object(poster, "posting_video_path", return_value=Path("/tmp/runtime/final.mp4")),
            patch.object(poster, "_find_recent_instagram_post", return_value=None),
            patch.object(
                poster,
                "_load_sns_env",
                return_value={"META_IG_USER_ID": "ig-1", "META_ACCESS_TOKEN": "token"},
            ),
            patch.object(poster, "_post_instagram_reels", side_effect=fake_post),
        ):
            self.assertEqual(poster.post_instagram(item), "https://instagram.example/reel/1")
        self.assertEqual(calls["post"], 1)
        self.assertEqual(seen["video_path"], Path("/tmp/runtime/final.mp4"))

    def test_tiktok_session_expired_is_not_retried(self):
        item = make_item()
        for platform in item["platforms"].values():
            platform["enabled"] = False
        item["platforms"]["tiktok"]["enabled"] = True
        calls = []

        def tiktok_post(_item):
            calls.append("tiktok")
            raise RuntimeError("TikTokセッション失効。scripts/login_tiktok.sh で専用Chromeに再ログインしてください")

        with (
            patch.object(poster, "POSTERS", {"tiktok": tiktok_post}),
            patch.object(poster, "_retry_settings", return_value=(2, 0.0)),
        ):
            updated = poster.post_item(item, FakeQueue, FakeNotify)

        self.assertEqual(calls, ["tiktok"])
        self.assertEqual(updated["platforms"]["tiktok"]["attempts"], 1)
        self.assertTrue(updated["platforms"]["tiktok"]["non_retryable"])
        self.assertEqual(updated["status"], "failed")

    def test_scheduled_difficulty_slots(self):
        from datetime import datetime

        self.assertEqual(scheduled_difficulty(datetime(2026, 6, 16, 9, 0)), "beginner")
        self.assertEqual(scheduled_difficulty(datetime(2026, 6, 16, 14, 0)), "intermediate")
        self.assertEqual(scheduled_difficulty(datetime(2026, 6, 16, 19, 0)), "intermediate")

    def test_result_summary_accepts_scheduled_quality_shape(self):
        summary = result_summary(
            {
                "id": "scheduled-1",
                "output_dir": "/tmp/out",
                "report": {"pass": True, "avg_cer": 0.0123},
                "scheduled": True,
            }
        )

        self.assertEqual(summary["id"], "scheduled-1")
        self.assertTrue(summary["pass"])
        self.assertEqual(summary["avg_cer"], 0.0123)
        self.assertTrue(summary["scheduled"])

    def test_produce_remakes_quality_failed_candidate_before_queue(self):
        script = {
            "title": "title",
            "caption": "caption",
            "hashtags": ["#AI活用"],
            "cues": [],
        }
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bad_dir = root / "bad"
            good_dir = root / "good"
            bad_dir.mkdir()
            good_dir.mkdir()
            bad_report = {
                "pass": False,
                "duration": 42.0,
                "size_mb": 4.2,
                "accuracy": {"avg_cer": 0.24, "failed_indices": [1]},
                "checks": [{"name": "subtitle_accuracy_lines", "pass": False}],
            }
            good_report = {
                "pass": True,
                "duration": 43.0,
                "size_mb": 4.1,
                "accuracy": {"avg_cer": 0.03, "failed_indices": []},
                "checks": [{"name": "subtitle_accuracy_lines", "pass": True}],
            }
            candidates = [
                {
                    "item_id": "bad-candidate",
                    "out_dir": bad_dir,
                    "output_dir": str(bad_dir),
                    "report": bad_report,
                    "title": "bad",
                    "topic": "topic",
                    "script": script,
                    "attempt": 1,
                },
                {
                    "item_id": "good-candidate",
                    "out_dir": good_dir,
                    "output_dir": str(good_dir),
                    "report": good_report,
                    "title": "good",
                    "topic": "topic",
                    "script": script,
                    "attempt": 2,
                },
            ]
            queued: list[str] = []
            transitions: list[tuple[str, str]] = []

            def fake_new_item(item_id, *_args):
                queued.append(item_id)
                return {
                    "id": item_id,
                    "title": "good",
                    "quality": {"pass": True, "avg_cer": 0.03},
                    "review": {},
                    "telegram": {},
                    "platforms": {},
                }

            def fake_transition(item, status, event=None):
                transitions.append((item["id"], status))
                item["status"] = status
                return item

            with (
                # is_seedance_slot は実行時刻依存のため、テストの決定論性を保つために
                # 常にFalse固定する（実運用configのseedance.slotsが実行時刻を含む
                # 状態だと、このテストが静止画版フローだけを検証しているつもりでも
                # 意図せずSeedance分岐に入り、実際にLLM呼び出しが発生してしまう）
                patch.object(pipeline, "is_seedance_slot", return_value=False),
                patch.object(pipeline, "_quality_remake_settings", return_value=(True, 2)),
                patch.object(pipeline, "_build_candidate", side_effect=candidates),
                patch.object(pipeline.topic_store, "next_topic_entry", return_value=({"topic": "topic", "difficulty": "beginner"}, 99)),
                patch.object(pipeline.topic_store, "consume_topic", return_value=99),
                patch.object(pipeline.queue_lib, "new_item", side_effect=fake_new_item),
                patch.object(pipeline.queue_lib, "transition", side_effect=fake_transition),
            ):
                result = pipeline.produce(send_queue=True, difficulty="beginner")

            self.assertEqual(queued, ["good-candidate"])
            self.assertEqual(transitions, [("good-candidate", "ready_for_review")])
            self.assertEqual(result["id"], "good-candidate")
            self.assertEqual(result["discarded_quality_failures"], 1)
            self.assertTrue((bad_dir / "remake_status.json").exists())

    def test_approval_preview_prefers_runtime_video_copy(self):
        with tempfile.TemporaryDirectory() as td:
            runtime = Path(td)
            local_video = runtime / "item-1" / "final.mp4"
            local_video.parent.mkdir()
            local_video.write_bytes(b"video")
            item = {
                "video": {"path": "/Drive/out/item-1/final.mp4"},
                "output_dir": "/Drive/out/item-1",
            }

            with patch.object(approval_bot.CONFIG, "work_dir", runtime):
                self.assertEqual(approval_bot._preview_video_path(item), local_video)

    def test_approval_preview_lock_blocks_parallel_sender(self):
        with tempfile.TemporaryDirectory() as td:
            runtime = Path(td)
            with patch.object(approval_bot.CONFIG, "runtime_dir", runtime):
                self.assertTrue(approval_bot._acquire_preview_lock("item-1"))
                self.assertFalse(approval_bot._acquire_preview_lock("item-1"))
                approval_bot._release_preview_lock("item-1")
                self.assertTrue(approval_bot._acquire_preview_lock("item-1"))
                approval_bot._release_preview_lock("item-1")

    def test_retry_io_retries_resource_deadlock(self):
        calls = []

        def flaky():
            calls.append(1)
            if len(calls) == 1:
                raise OSError(errno.EDEADLK, "Resource deadlock avoided")
            return "ok"

        self.assertEqual(retry_io(flaky, attempts=2, delay_sec=0), "ok")
        self.assertEqual(len(calls), 2)

    def test_retry_io_retries_operation_timed_out(self):
        calls = []

        def flaky():
            calls.append(1)
            if len(calls) == 1:
                raise OSError(errno.ETIMEDOUT, "Operation timed out")
            return "ok"

        self.assertEqual(retry_io(flaky, attempts=2, delay_sec=0), "ok")
        self.assertEqual(len(calls), 2)

    def test_script_generation_normalizes_unstable_terms(self):
        data = {
            "cues": [
                {
                    "display": ["PDFをAPIで", "AI確認する"],
                    "tts_text": "PDFをAPIでAI確認します。",
                    "reading_kana": "PDFヲAPIデAIカクニンシマス。",
                }
            ]
        }

        script_gen.normalize_generated_script(data)

        display_joined = "\n".join(data["cues"][0]["display"])
        voice_joined = data["cues"][0]["tts_text"] + data["cues"][0]["reading_kana"]
        self.assertIn("PDF", display_joined)
        self.assertIn("API", display_joined)
        self.assertIn("AI確認", display_joined)
        self.assertNotIn("ピーディーエフ", display_joined)
        self.assertNotIn("エーピーアイ", display_joined)
        self.assertNotIn("PDF", voice_joined)
        self.assertNotIn("API", voice_joined)
        self.assertIn("ピーディーエフ", voice_joined)
        self.assertIn("エーピーアイ", voice_joined)
        self.assertNotIn("AI確認", voice_joined)
        self.assertIn("エーアイ確認", voice_joined)

    def test_generic_fallback_script_is_valid(self):
        data = script_gen._fallback_script("ChatGPTで資料を要約する方法", "beginner", ["err"])
        errs = script_gen.validate_script(data, image_count=4)

        self.assertEqual(errs, [])
        self.assertIn("二案を並べます", data["cues"][4]["display"])

    def test_find_due_scheduled_draft(self):
        now = datetime(2026, 6, 25, 9, 0, tzinfo=timezone(timedelta(hours=9)))
        items = [
            {
                "id": "future",
                "status": "draft",
                "difficulty": "beginner",
                "scheduled_for": "2026-06-25T14:00:00+09:00",
            },
            {
                "id": "due",
                "status": "draft",
                "difficulty": "beginner",
                "scheduled_for": "2026-06-25T09:00:00+09:00",
            },
            {
                "id": "intermediate-due",
                "status": "draft",
                "difficulty": "intermediate",
                "scheduled_for": "2026-06-25T09:00:00+09:00",
            },
        ]

        with patch.object(queue_lib, "list_items", return_value=items):
            self.assertEqual(queue_lib.find_due_scheduled_draft(now, "beginner")["id"], "due")
            self.assertEqual(
                queue_lib.find_due_scheduled_draft(now, "intermediate")["id"],
                "intermediate-due",
            )
            self.assertIsNone(
                queue_lib.find_due_scheduled_draft(now + timedelta(hours=3), "beginner")
            )

    def test_deferred_retry_requires_approval_and_cooldown(self):
        now = datetime(2026, 6, 24, 20, 0, tzinfo=timezone(timedelta(hours=9)))
        item = make_item()
        item["status"] = "partial_failed"
        item["created_at"] = "2026-06-24T19:00:00+09:00"
        item["review"] = {"owner_approved": True}
        item["platforms"]["x"]["status"] = "posted"
        item["platforms"]["instagram"]["enabled"] = True
        item["platforms"]["instagram"]["status"] = "failed"
        item["platforms"]["instagram"]["last_attempt_at"] = "2026-06-24T19:40:00+09:00"

        with patch.object(
            approval_bot,
            "_deferred_retry_settings",
            return_value=(True, 3, 900.0, timedelta(hours=6)),
        ):
            allowed, _reason, platforms = approval_bot._deferred_retry_allowed(item, now)
            self.assertTrue(allowed)
            self.assertEqual(platforms, ["instagram"])

            item["review"]["owner_approved"] = False
            allowed, reason, _platforms = approval_bot._deferred_retry_allowed(item, now)
            self.assertFalse(allowed)
            self.assertEqual(reason, "not_approved")

            item["review"]["owner_approved"] = True
            item["platforms"]["instagram"]["last_attempt_at"] = "2026-06-24T19:50:00+09:00"
            allowed, reason, _platforms = approval_bot._deferred_retry_allowed(item, now)
            self.assertFalse(allowed)
            self.assertEqual(reason, "cooldown")

            item["platforms"]["instagram"]["last_attempt_at"] = "2026-06-24T19:40:00+09:00"
            item["created_at"] = "2026-06-17T09:00:00+09:00"
            allowed, reason, _platforms = approval_bot._deferred_retry_allowed(item, now)
            self.assertFalse(allowed)
            self.assertEqual(reason, "expired")

            item["review"]["decided_at"] = "2026-06-24T19:55:00+09:00"
            allowed, _reason, platforms = approval_bot._deferred_retry_allowed(item, now)
            self.assertTrue(allowed)
            self.assertEqual(platforms, ["instagram"])

            item["review"].pop("decided_at", None)
            item["created_at"] = "2026-06-24T19:00:00+09:00"
            item["platforms"]["instagram"]["last_attempt_at"] = None
            item.pop("deferred_retry", None)
            allowed, reason, _platforms = approval_bot._deferred_retry_allowed(item, now)
            self.assertFalse(allowed)
            self.assertEqual(reason, "missing_attempt_at")

    def test_consume_topic_is_idempotent_for_deferred_retry(self):
        data = {
            "backlog": [
                {"topic": "topic-a", "difficulty": "beginner"},
                {"topic": "topic-b", "difficulty": "beginner"},
            ],
            "used": [],
        }
        saved: list[dict] = []

        def fake_load(allow_cache=True):
            return json.loads(json.dumps(data, ensure_ascii=False))

        def fake_save(updated):
            saved.append(json.loads(json.dumps(updated, ensure_ascii=False)))
            data.clear()
            data.update(updated)

        with (
            patch.object(topic_store, "_load", side_effect=fake_load),
            patch.object(topic_store, "_save", side_effect=fake_save),
        ):
            self.assertEqual(topic_store.consume_topic("topic-a", "slug-1", "Title A", "beginner"), 1)
            self.assertEqual(topic_store.consume_topic("topic-a", "slug-1", "Title A", "beginner"), 1)
            self.assertEqual(topic_store.consume_topic("topic-a", "slug-2", "Title A2", "beginner"), 1)

        self.assertEqual([entry["topic"] for entry in data["backlog"]], ["topic-b"])
        self.assertEqual(len(data["used"]), 1)
        self.assertEqual(data["used"][0]["slug"], "slug-1")

    def test_next_topic_can_skip_topics_already_in_queue_when_requested(self):
        data = {
            "backlog": [
                {
                    "topic": "ChatGPTに業務フローを棚卸しさせ、自動化候補を優先順位付けする方法",
                    "difficulty": "intermediate",
                },
                {
                    "topic": "ChatGPTにプロンプトの評価基準を作らせ、出力品質を比較する方法",
                    "difficulty": "intermediate",
                },
            ],
            "used": [],
        }

        with (
            patch.object(topic_store, "_load", return_value=data),
            patch.object(
                topic_store,
                "_queue_topic_entries",
                return_value=[
                    {
                        "topic": "ChatGPTに業務フローを棚卸しさせ、自動化候補を優先順位付けする方法",
                        "title": "仕事で使える改善の型",
                    }
                ],
            ),
        ):
            topic, remaining = topic_store.next_topic("intermediate", include_queue=True)

        self.assertEqual(topic, "ChatGPTにプロンプトの評価基準を作らせ、出力品質を比較する方法")
        self.assertEqual(remaining, 2)

    def test_add_topics_rejects_near_duplicate_topics(self):
        data = {
            "backlog": [],
            "used": [
                {
                    "topic": "ChatGPTに業務フローを棚卸しさせ、自動化候補を優先順位付けする方法",
                    "title": "自動化候補を見抜く3軸",
                }
            ],
        }
        saved: list[dict] = []

        def fake_save(updated):
            saved.append(json.loads(json.dumps(updated, ensure_ascii=False)))
            data.clear()
            data.update(updated)

        with (
            patch.object(topic_store, "_load", side_effect=lambda *args, **kwargs: json.loads(json.dumps(data, ensure_ascii=False))),
            patch.object(topic_store, "_save", side_effect=fake_save),
            patch.object(topic_store, "_queue_topic_entries", return_value=[]),
        ):
            count = topic_store.add_topics(
                [
                    {
                        "topic": "業務フローを棚卸しして自動化候補を優先順位付けする方法",
                        "difficulty": "intermediate",
                    },
                    {
                        "topic": "ChatGPTで月次レポートの異常値を見つける方法",
                        "difficulty": "intermediate",
                    },
                ]
            )

        self.assertEqual(count, 1)
        self.assertEqual(
            [entry["topic"] for entry in data["backlog"]],
            ["ChatGPTで月次レポートの異常値を見つける方法"],
        )
        self.assertEqual(len(saved), 1)

    def test_replenish_topics_adds_intermediate_without_duplicates(self):
        data = {
            "backlog": [],
            "used": [
                {
                    "topic": "ChatGPTとClaudeで提案書の弱点を抽出し、反論対策まで整える方法",
                    "title": "提案書の弱点をAIで見抜く",
                }
            ],
        }
        saved: list[dict] = []

        def fake_save(updated):
            saved.append(json.loads(json.dumps(updated, ensure_ascii=False)))
            data.clear()
            data.update(updated)

        with (
            patch.object(topic_store, "_load", side_effect=lambda *args, **kwargs: json.loads(json.dumps(data, ensure_ascii=False))),
            patch.object(topic_store, "_save", side_effect=fake_save),
            patch.object(topic_store, "_queue_topic_entries", return_value=[]),
        ):
            result = topic_store.replenish_topics("intermediate", force=True)

        self.assertGreaterEqual(result["added"], 30)
        self.assertEqual({entry["difficulty"] for entry in data["backlog"]}, {"intermediate"})
        self.assertNotIn(
            "ChatGPTとClaudeで提案書の弱点を抽出し、反論対策まで整える方法",
            [entry["topic"] for entry in data["backlog"]],
        )
        self.assertEqual(len(saved), 1)

    def test_list_items_can_scan_recent_files_only(self):
        with tempfile.TemporaryDirectory() as td:
            qdir = Path(td)
            for i, status in enumerate(("posted", "ready_for_review", "approved"), start=1):
                (qdir / f"2026-06-27_090{i}.json").write_text(
                    json.dumps({"id": f"item-{i}", "status": status}, ensure_ascii=False),
                    encoding="utf-8",
                )
            with patch.object(queue_lib.CONFIG, "queue_dir", qdir):
                recent = queue_lib.list_items(recent_files=2)
                approved = queue_lib.list_items("approved", recent_files=2, max_items=1)

        self.assertEqual([item["id"] for item in recent], ["item-3", "item-2"])
        self.assertEqual([item["id"] for item in approved], ["item-3"])

    def test_fallback_scripts_do_not_return_typecasting_theme(self):
        for topic in (
            "ChatGPTに業務フローを棚卸しさせ、自動化候補を優先順位付けする方法",
            "ChatGPTで採用面接の評価基準を揃え、属人化を減らす方法",
            "ChatGPTに競合比較表を作らせ、差別化ポイントを言語化する方法",
        ):
            script = script_gen._fallback_script(topic, "intermediate", ["forced fallback"])
            self.assertEqual(script_gen.validate_script(script, 4), [])
            rendered = json.dumps(script, ensure_ascii=False)
            self.assertNotIn("型化", rendered)
            self.assertNotIn("仕事で使える改善の型", rendered)

    def test_approval_bot_recovers_deferred_topic_consume(self):
        item = {
            "id": "item-1",
            "status": "ready_for_review",
            "topic": "topic-a",
            "title": "Title A",
            "difficulty": "beginner",
            "topic_store": {"consume_deferred_error": "[Errno 11] Resource deadlock avoided"},
            "history": [],
        }
        saved: list[dict] = []

        def fake_list_items(status=None, **_kwargs):
            return [item] if status == "ready_for_review" else []

        def fake_save_item(updated):
            saved.append(json.loads(json.dumps(updated, ensure_ascii=False)))
            return updated

        with (
            patch.object(approval_bot.queue_lib, "list_items", side_effect=fake_list_items),
            patch.object(approval_bot.queue_lib, "save_item", side_effect=fake_save_item),
            patch.object(approval_bot.topic_store, "consume_topic", return_value=12) as consume,
        ):
            approval_bot._retry_deferred_topic_consumes()

        consume.assert_called_once_with("topic-a", "item-1", "Title A", "beginner")
        self.assertNotIn("consume_deferred_error", item["topic_store"])
        self.assertEqual(item["topic_store"]["remaining"], 12)
        self.assertIn("topic_consume_recovered", item["history"][-1]["event"])
        self.assertEqual(len(saved), 1)

    def test_approval_bot_recovers_deferred_platform_group_consume(self):
        item = {
            "id": "item-1-x",
            "status": "ready_for_review",
            "topic": "topic-a",
            "title": "X Title",
            "difficulty": "intermediate",
            "variant_group_id": "2026-07-04_190630_platforms",
            "topic_store": {
                "consume_deferred_error": "[Errno 11] Resource deadlock avoided",
            },
            "history": [],
        }

        def fake_list_items(status=None, **_kwargs):
            return [item] if status == "ready_for_review" else []

        with (
            patch.object(approval_bot.queue_lib, "list_items", side_effect=fake_list_items),
            patch.object(approval_bot.queue_lib, "save_item", return_value=Path("/tmp/item.json")),
            patch.object(approval_bot.topic_store, "consume_topic", return_value=11) as consume,
        ):
            approval_bot._retry_deferred_topic_consumes()

        consume.assert_called_once_with(
            "topic-a",
            "2026-07-04_190630_platforms",
            "SNS別動画: topic-a",
            "intermediate",
        )
        self.assertNotIn("consume_deferred_error", item["topic_store"])
        self.assertEqual(item["topic_store"]["remaining"], 11)

    def test_telegram_text_command_approves_item(self):
        item = make_item()
        item["status"] = "ready_for_review"
        item["review"] = {"owner_approved": False, "decided_at": None, "via": None}
        messages: list[str] = []
        spawned: list[tuple[str, str]] = []

        with (
            patch.dict(os.environ, {"SHORTS_TG_CHAT_ID": "123"}),
            patch.object(approval_bot.queue_lib, "load_item", return_value=item),
            patch.object(approval_bot.queue_lib, "transition", side_effect=FakeQueue.transition),
            patch.object(
                approval_bot,
                "_spawn_post_worker",
                side_effect=lambda updated, reason: spawned.append((updated["id"], reason)) or True,
            ),
            patch.object(approval_bot.notify, "send_message", side_effect=lambda text: messages.append(text)),
        ):
            approval_bot.handle_message({"chat": {"id": "123"}, "text": "承認 item-1"})

        self.assertTrue(item["review"]["owner_approved"])
        self.assertEqual(item["review"]["via"], "telegram_text")
        self.assertEqual(item["status"], "approved")
        self.assertEqual(spawned, [("item-1", "approved:telegram_text")])
        self.assertIn("承認しました", messages[0])

    def test_approval_bot_watchdog_stall_boundary(self):
        self.assertFalse(approval_bot._watchdog_stalled(109.9, 100.0, 10.0))
        self.assertTrue(approval_bot._watchdog_stalled(110.0, 100.0, 10.0))

    def test_posting_worker_active_when_lock_exists(self):
        with tempfile.TemporaryDirectory() as td:
            runtime = Path(td)
            with patch.object(approval_bot.CONFIG, "runtime_dir", runtime):
                fd, path = approval_bot.post_lock.acquire("item-1")
                self.assertTrue(approval_bot._posting_worker_active({"id": "item-1"}))
                approval_bot.post_lock.release(fd, path)

    def test_untracked_preview_receipt_suppresses_duplicate_preview(self):
        item = make_item()
        item["telegram"] = {
            "message_id": None,
            "preview_send_attempts": 1,
            "preview_send_started_at": datetime.now().astimezone().isoformat(),
            "preview_sent_untracked_at": datetime.now().astimezone().isoformat(),
        }
        self.assertFalse(approval_bot._preview_retry_allowed(item))

    def test_started_preview_without_receipt_fails_closed(self):
        item = make_item()
        item["telegram"] = {
            "message_id": None,
            "preview_send_attempts": 1,
            "preview_send_started_at": (
                datetime.now().astimezone() - timedelta(hours=1)
            ).isoformat(),
        }
        self.assertFalse(approval_bot._preview_retry_allowed(item))

    def test_approval_button_message_is_not_replayed_from_outbox(self):
        with tempfile.TemporaryDirectory() as td:
            with (
                patch.object(notify.CONFIG, "marketing_dir", Path(td)),
                patch.object(notify, "enabled", return_value=True),
                patch.object(notify, "_send_message_payload", return_value=None),
            ):
                self.assertIsNone(
                    notify.send_message("approval", reply_markup={"inline_keyboard": []})
                )
                self.assertEqual([], list((Path(td) / "notification_outbox").glob("*.json")))

    def test_ambiguous_video_request_does_not_send_text_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            video = Path(td) / "final.mp4"
            video.write_bytes(b"video")
            with (
                patch.object(notify, "enabled", return_value=True),
                patch.object(
                    notify.requests,
                    "post",
                    side_effect=notify.requests.ConnectionError("ambiguous"),
                ),
                patch.object(notify, "send_message") as fallback,
            ):
                self.assertIsNone(
                    notify.send_video(video, "preview", {"inline_keyboard": []})
                )
            fallback.assert_not_called()

    def test_expired_callback_with_current_message_is_applied(self):
        item = make_item()
        item["status"] = "ready_for_review"
        item["review"] = {"owner_approved": False, "decided_at": None, "via": None}
        item["telegram"] = {"message_id": 42}
        messages: list[str] = []
        spawned: list[tuple[str, str]] = []

        with (
            patch.object(approval_bot.queue_lib, "load_item", return_value=item),
            patch.object(approval_bot.queue_lib, "transition", side_effect=FakeQueue.transition),
            patch.object(
                approval_bot,
                "_spawn_post_worker",
                side_effect=lambda updated, reason: spawned.append((updated["id"], reason)) or True,
            ),
            patch.object(approval_bot, "_answer_callback_status", return_value="expired"),
            patch.object(approval_bot, "_remove_buttons"),
            patch.object(approval_bot.notify, "send_message", side_effect=lambda text: messages.append(text)),
        ):
            approval_bot.handle_callback({"id": "cb-1", "data": "approve:item-1", "message": {"message_id": 42}})

        self.assertEqual(item["status"], "approved")
        self.assertTrue(item["review"]["owner_approved"])
        self.assertEqual(spawned, [("item-1", "approved:telegram")])
        self.assertIn("期限切れ", messages[0])

    def test_expired_callback_without_current_message_does_not_mutate_review_state(self):
        item = make_item()
        item["status"] = "ready_for_review"
        item["review"] = {"owner_approved": False, "decided_at": None, "via": None}
        messages: list[str] = []
        spawned: list[tuple[str, str]] = []

        with (
            patch.object(approval_bot.queue_lib, "load_item", return_value=item),
            patch.object(approval_bot.queue_lib, "transition", side_effect=FakeQueue.transition),
            patch.object(
                approval_bot,
                "_spawn_post_worker",
                side_effect=lambda updated, reason: spawned.append((updated["id"], reason)) or True,
            ),
            patch.object(approval_bot, "_answer_callback_status", return_value="expired"),
            patch.object(approval_bot.notify, "send_message", side_effect=lambda text: messages.append(text)),
        ):
            approval_bot.handle_callback({"id": "cb-1", "data": "approve:item-1", "message": {}})

        self.assertEqual(item["status"], "ready_for_review")
        self.assertFalse(item["review"]["owner_approved"])
        self.assertEqual(spawned, [])
        self.assertIn("操作は反映していません", messages[0])

    def test_next_topic_entry_preserves_content_metadata(self):
        data = {
            "backlog": [
                {
                    "topic": "ChatGPT、Claude、Geminiを業務別に使い分ける判断基準",
                    "difficulty": "intermediate",
                    "domain": "ai_tool_comparison",
                    "primary_tools": ["ChatGPT", "Claude", "Gemini"],
                    "platform_angles": {"instagram": "保存版。AIツール使い分け表"},
                }
            ],
            "used": [],
        }

        with (
            patch.object(topic_store, "_load", return_value=data),
            patch.object(topic_store, "_queue_topic_entries", return_value=[]),
        ):
            entry, remaining = topic_store.next_topic_entry("intermediate")
            topic, topic_remaining = topic_store.next_topic("intermediate")

        self.assertEqual(remaining, 1)
        self.assertEqual(topic_remaining, 1)
        self.assertEqual(topic, data["backlog"][0]["topic"])
        self.assertEqual(entry["domain"], "ai_tool_comparison")
        self.assertEqual(entry["platform_angles"]["instagram"], "保存版。AIツール使い分け表")

    def test_script_prompt_includes_topic_context_and_platform_guidance(self):
        topic = {
            "topic": "NotebookLMで社内資料を検索しやすい知識ベースにする方法",
            "difficulty": "intermediate",
            "domain": "knowledge_management",
            "primary_tools": ["NotebookLM", "Google Drive"],
            "platform_angles": {"instagram": "保存版。社内資料をAIで探しやすくする3手順"},
        }
        with patch.object(topic_store, "recent_titles", return_value=[]):
            prompt = script_gen._build_prompt(topic, image_count=4, difficulty="intermediate", target_platform="instagram")

        self.assertIn("AIツール・AI導入・業務自動化", prompt)
        self.assertIn("target_platform: `instagram`", prompt)
        self.assertIn("保存版・チェックリスト", prompt)
        self.assertIn("NotebookLM、Google Drive", prompt)
        self.assertIn("保存版。社内資料をAIで探しやすくする3手順", prompt)

    def test_normalize_generated_script_preserves_display_brand_terms(self):
        data = {
            "cues": [
                {
                    "display": ["CanvaとGamma", "NotebookLMとPDF"],
                    "tts_text": "CanvaとGammaとNotebookLMとPDFを比較します。",
                    "reading_kana": "CanvaトGammaトNotebookLMトPDFヲヒカクシマス。",
                }
            ]
        }

        script_gen.normalize_generated_script(data)

        self.assertEqual(data["cues"][0]["display"], ["CanvaとGamma", "NotebookLMとPDF"])
        self.assertNotIn("Canva", data["cues"][0]["tts_text"])
        self.assertNotIn("Gamma", data["cues"][0]["tts_text"])
        self.assertNotIn("NotebookLM", data["cues"][0]["tts_text"])
        self.assertNotIn("PDF", data["cues"][0]["tts_text"])
        self.assertIn("キャンバ", data["cues"][0]["tts_text"])
        self.assertIn("ガンマ", data["cues"][0]["tts_text"])
        self.assertIn("ノートブックエルエム", data["cues"][0]["tts_text"])
        self.assertIn("ピーディーエフ", data["cues"][0]["reading_kana"])

    def test_display_validator_allows_only_canonical_ai_brand_terms(self):
        self.assertFalse(script_gen._display_unstable_text("AIとClaude"))
        self.assertFalse(script_gen._display_unstable_text("GeminiとChatGPT"))
        self.assertFalse(script_gen._display_unstable_text("NotebookLMとPerplexity"))
        self.assertFalse(script_gen._display_unstable_text("CanvaとGamma"))
        self.assertFalse(script_gen._display_unstable_text("ZapierとMakeとn8n"))
        self.assertFalse(script_gen._display_unstable_text("Google DriveとNotion"))
        self.assertFalse(script_gen._display_unstable_text("PDFとAPIとURL"))
        self.assertFalse(script_gen._display_unstable_text("CSVとKPIとCRM"))
        self.assertFalse(script_gen._display_unstable_text("生成AI"))
        self.assertFalse(script_gen._display_unstable_text("OpenAIとFigma"))
        self.assertTrue(script_gen._display_unstable_text("Before改善"))
        self.assertTrue(script_gen._display_unstable_text("UnknownTool"))
        self.assertTrue(script_gen._display_unstable_text("15%改善"))

    def test_phonetic_match_allows_tool_display_with_kana_tts(self):
        display = jp_text.phonetic_hira("この三つをNotebookLMやPDFに渡します")
        tts = jp_text.phonetic_hira("この三つをノートブックエルエムやピーディーエフに渡します。")

        self.assertGreaterEqual(jp_text.lcs_coverage(display, tts), 0.70)

    def test_platform_copy_prepends_platform_angle(self):
        item = make_item()
        item["platform_angles"] = {
            "x": "AI導入はツール選びより最初の1業務選びで差が出ます",
            "instagram": "保存版。AI導入前に見る3項目",
        }

        copies = platform_copy.build_platform_copy_set(item)

        self.assertIn("AI導入はツール選び", copies["x"]["text"])
        self.assertIn("保存版。AI導入前", copies["instagram"]["caption"])
        self.assertNotIn("保存版。AI導入前", copies["x"]["text"])

    def test_new_item_persists_content_strategy_metadata(self):
        script = {
            "title": "AI導入は最初の業務選び",
            "caption": "AI導入では、ツール選びより最初に任せる業務を決めることが重要です。",
            "hashtags": ["#生成AI", "#AI導入", "#仕事術"],
            "difficulty": "intermediate",
            "target_platform": "common",
            "content_strategy": {"domain": "ai_adoption", "primary_tools": ["ChatGPT", "Gemini"]},
            "platform_angles": {"youtube": "AI導入で最初の1業務を選ぶ基準"},
        }
        with tempfile.TemporaryDirectory() as td, patch.object(queue_lib.CONFIG, "queue_dir", Path(td)):
            item = queue_lib.new_item(
                "item-meta",
                "AI導入で最初の1業務を選ぶ3つの条件",
                script,
                Path("/tmp/final.mp4"),
                40.0,
                4.0,
                Path("/tmp/quality.json"),
                True,
                0.02,
                Path("/tmp/out"),
            )

        self.assertEqual(item["target_platform"], "common")
        self.assertEqual(item["content_strategy"]["domain"], "ai_adoption")
        self.assertEqual(item["platform_angles"]["youtube"], "AI導入で最初の1業務を選ぶ基準")


if __name__ == "__main__":
    unittest.main()
