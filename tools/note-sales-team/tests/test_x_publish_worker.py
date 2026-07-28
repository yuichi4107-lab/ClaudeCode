from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "x_publish_worker.py"
SPEC = importlib.util.spec_from_file_location("x_publish_worker_test", MODULE_PATH)
worker = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(worker)
note_team = worker.note_team


class XPublishWorkerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "AGENTS.md").write_text("test\n", encoding="utf-8")
        project = self.root / note_team.PROJECT_REL
        (project / "config").mkdir(parents=True)
        (project / "data").mkdir(parents=True)
        legacy = self.root / ".company/outputs/note-articles"
        legacy.mkdir(parents=True)
        (legacy / "accounts.json").write_text(
            json.dumps(
                {
                    "accounts": [
                        {
                            "account_id": "you-ai-dx",
                            "display_name": "Test",
                            "note_id": "you_ai_dx",
                            "theme_ids": ["ai-utilization"],
                            "word_count_target": [20, 1000],
                            "status": "active",
                        }
                    ],
                    "themes": [
                        {
                            "theme_id": "ai-utilization",
                            "theme_name": "AI活用",
                            "account_id": "you-ai-dx",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (legacy / "history.json").write_text("[]\n", encoding="utf-8")
        config = {
            "timezone": "Asia/Tokyo",
            "project_root": str(note_team.PROJECT_REL),
            "legacy_accounts_path": ".company/outputs/note-articles/accounts.json",
            "legacy_history_path": ".company/outputs/note-articles/history.json",
            "default_account_id": "you-ai-dx",
            "default_theme_id": "ai-utilization",
            "_account": {"user_id": "12345", "username": "testuser"},
            "article_defaults": {"approval_granularity": "chapter", "quality_gate": 85},
            "product_profiles": {
                "free-standard": {"chapter_range": [4, 7]},
                "paid-longform": {
                    "chapter_range": [8, 10],
                    "word_count_target": [15000, 20000],
                },
            },
            "safety": {
                "note_draft_requires_explicit_approval": True,
                "note_publish_requires_explicit_approval": True,
                "x_publish_requires_explicit_approval": True,
                "note_publish_enabled": True,
                "x_publish_enabled": True,
                "line_send_enabled": False,
                "scheduled_runs_enabled": False,
                "require_director_qa": True,
                "store_credentials": False,
                "unknown_metrics_policy": "N/A",
            },
            "metrics": {
                "aggregation_mode": "daily_delta",
                "note_csv": f"{note_team.PROJECT_REL}/data/note_metrics.csv",
                "x_csv": f"{note_team.PROJECT_REL}/data/x_metrics.csv",
            },
            "style_sources": {
                "candidate_registry_path": f"{note_team.PROJECT_REL}/data/style-candidates.json",
                "registry_path": f"{note_team.PROJECT_REL}/data/style-corpus.json",
                "minimum_note_samples": 3,
                "minimum_x_samples": 20,
                "require_owner_approval": True,
            },
        }
        (project / "config/team.json").write_text(
            json.dumps(config, ensure_ascii=False), encoding="utf-8"
        )
        (project / "data/note_metrics.csv").write_text(
            "date,run_id,pv,sales_count,revenue_yen\n", encoding="utf-8"
        )
        (project / "data/x_metrics.csv").write_text(
            "date,run_id,impressions,link_clicks\n", encoding="utf-8"
        )
        self.install_style_fixture(project)
        state, _ = note_team.create_run(
            self.root, "you-ai-dx", "ai-utilization", "worker"
        )
        self.run_id = state["run_id"]
        directory = note_team.run_dir(self.root, self.run_id)
        promotion = {
            "variants": [
                {
                    "promotion_id": f"x-0{number}",
                    "intent": f"案{number}",
                    "primary_text": f"AI活用の具体例です。{number}",
                    "reply_text_template": "詳細はこちら [NOTE_URL]",
                }
                for number in range(1, 4)
            ]
        }
        (directory / "promotion.json").write_text(
            json.dumps(promotion, ensure_ascii=False), encoding="utf-8"
        )
        promotion_snapshot, promotion_sha = note_team.snapshot_text(
            directory, "promotion.json", "promotion/final", 1
        )
        note_result = {
            "public_url": "https://note.com/you_ai_dx/n/n-worker123",
        }
        (directory / "note-publish.json").write_text(
            json.dumps(note_result), encoding="utf-8"
        )
        note_snapshot, note_sha = note_team.snapshot_text(
            directory, "note-publish.json", "note_publish/final", 1
        )
        state["current_stage"] = "x_publish"
        for stage in note_team.STAGES[: note_team.STAGES.index("x_publish")]:
            state["stages"][stage]["status"] = "approved"
        state["stages"]["promotion"].update(
            {"artifact": promotion_snapshot, "artifact_sha256": promotion_sha}
        )
        state["stages"]["note_publish"].update(
            {"artifact": note_snapshot, "artifact_sha256": note_sha}
        )
        state["stages"]["x_publish"]["status"] = "authorization_required"
        state["selected_promotion_id"] = "x-01"
        note_team.atomic_write_json(note_team.state_path(self.root, self.run_id), state)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def install_style_fixture(self, project: Path) -> None:
        samples = project / "data/style-samples"
        samples.mkdir()
        notes = []
        for number in range(1, 4):
            source = samples / f"note-{number:02d}.md"
            source.write_text(f"# style note {number}\n", encoding="utf-8")
            notes.append(
                {
                    "candidate_id": f"note-{number:02d}",
                    "title": f"Style note {number}",
                    "source_path": source.relative_to(self.root).as_posix(),
                    "source_url": f"https://note.com/you_ai_dx/n/nstyle{number:02d}",
                    "public_url": f"https://note.com/you_ai_dx/n/nstyle{number:02d}",
                    "published_at": "2026-07-01",
                    "public_verified_at": "2026-07-19",
                    "verification_precision": "date",
                    "preview": f"style note {number}",
                    "metrics": {
                        "scope": "publication-verified-only",
                        "sales_units": "N/A",
                        "sales_amount_yen": "N/A",
                        "paid_conversion_rate": "N/A",
                    },
                    "constraints": ["売上不明"],
                    "file_sha256": note_team.sha256_file(source),
                }
            )
        x_posts = []
        for number in range(1, 21):
            text = f"style X post {number}"
            tweet_id = str(10000 + number)
            x_posts.append(
                {
                    "candidate_id": f"x-{number:02d}",
                    "tweet_id": tweet_id,
                    "title": f"Style X {number}",
                    "source_url": f"https://x.com/testuser/status/{tweet_id}",
                    "posted_at": note_team.iso_now(),
                    "author_id": "12345",
                    "author_username": "testuser",
                    "source_queue": f"state/queue/item-{number:02d}.json",
                    "source_ledger": f"posting_ledger/item-{number:02d}.json",
                    "text": text,
                    "preview": text,
                    "metrics": {"public_metrics": {"impression_count": number}},
                    "brand_style_candidate": True,
                    "owner_style_approval_required": True,
                    "constraints": ["X反応は小規模"],
                    "text_sha256": note_team.sha256_bytes(text.encode("utf-8")),
                }
            )
        manifest = note_team.style_selection_manifest(notes, x_posts)
        candidate_path = project / "data/style-candidates.json"
        candidate_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "status": "owner-approval-required",
                    "generated_at": note_team.iso_now(),
                    "brand_style_candidate": True,
                    "owner_style_approval_required": True,
                    "limitations": ["テスト用文体候補"],
                    "note_candidates": notes,
                    "x_candidates": x_posts,
                    "selection_manifest": manifest,
                    "selection_sha256": note_team.sha256_bytes(
                        note_team.canonical_json_bytes(manifest)
                    ),
                    "selection_sha256_algorithm": "canonical-json-test-v1",
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        registry_path = project / "data/style-corpus.json"
        registry_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "status": "setup-required",
                    "approved_by": None,
                    "approved_at": None,
                    "note_sources": [],
                    "x_sources": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        note_team.approve_style_corpus(
            self.root,
            note_team.sha256_file(candidate_path),
            note_team.sha256_file(registry_path),
            owner_session_confirmed=True,
        )

    @staticmethod
    def identity() -> dict[str, str]:
        return {"id": "12345", "username": "testuser", "name": "Test"}

    def test_prepare_and_claim_backed_publish(self) -> None:
        with mock.patch.object(worker.post_to_x, "get_identity", side_effect=self.identity):
            preflight, path = worker.build_preflight(self.root, self.run_id)
        self.assertTrue(path.is_file())
        self.assertIn("https://note.com/you_ai_dx/n/n-worker123", preflight["reply_text"])
        state = note_team.load_state(self.root, self.run_id)
        self.assertEqual(state["stages"]["x_publish"]["status"], "authorization_ready")
        note_team.authorize_external(
            self.root, self.run_id, "x_publish", owner_session_confirmed=True
        )

        created = [
            {"id": "100001"},
            {"id": "100002"},
        ]

        def readback(tweet_id: str) -> dict[str, object]:
            if tweet_id == "100001":
                return {
                    "id": tweet_id,
                    "author_id": "12345",
                    "text": preflight["primary_text"],
                    "reply_to_tweet_id": None,
                }
            return {
                "id": tweet_id,
                "author_id": "12345",
                "text": "記事の詳細はこちらです。 https://t.co/example",
                "expanded_text": preflight["reply_text"],
                "reply_to_tweet_id": "100001",
            }

        with (
            mock.patch.object(worker.post_to_x, "get_identity", side_effect=self.identity),
            mock.patch.object(worker.post_to_x, "post_one", side_effect=created) as post_one,
            mock.patch.object(worker.post_to_x, "readback_tweet", side_effect=readback),
        ):
            result, _ = worker.publish(self.root, self.run_id)

        self.assertEqual(post_one.call_count, 2)
        self.assertEqual(
            post_one.call_args_list[1].kwargs["in_reply_to_tweet_id"], "100001"
        )
        self.assertEqual(result["reply_to_tweet_id"], "100001")
        state = note_team.load_state(self.root, self.run_id)
        self.assertEqual(state["stages"]["x_publish"]["status"], "review")
        self.assertEqual(
            state["stages"]["x_publish"]["components"]["main"]["tweet_id"],
            "100001",
        )

    def test_main_success_reply_failure_does_not_repost_main(self) -> None:
        with mock.patch.object(worker.post_to_x, "get_identity", side_effect=self.identity):
            worker.build_preflight(self.root, self.run_id)
        note_team.authorize_external(
            self.root, self.run_id, "x_publish", owner_session_confirmed=True
        )
        with (
            mock.patch.object(worker.post_to_x, "get_identity", side_effect=self.identity),
            mock.patch.object(
                worker.post_to_x,
                "post_one",
                side_effect=[{"id": "100001"}, TimeoutError("reply response lost")],
            ) as post_one,
            self.assertRaises(TimeoutError),
        ):
            worker.publish(self.root, self.run_id)
        self.assertEqual(post_one.call_count, 2)
        state = note_team.load_state(self.root, self.run_id)
        self.assertEqual(
            state["stages"]["x-publish"]["status"], "reconciliation_required"
        )
        self.assertEqual(
            state["stages"]["x-publish"]["components"]["main"]["tweet_id"],
            "100001",
        )
        with self.assertRaisesRegex(note_team.NoteTeamError, "本投稿は既に確定済み"):
            note_team.confirm_no_external_result(
                self.root,
                self.run_id,
                "x_publish",
                "APIでリプ不存在を랊認",
                owner_session_confirmed=True,
            )
        unchanged = note_team.load_state(self.root, self.run_id)
        self.assertEqual(
            unchanged["stages"]["x_publish"]["components"]["main"]["tweet_id"],
            "100001",
        )
        controls = note_team.reconciliation_controls(
            self.run_id,
            "x_publish",
            "csrf-test",
            unchanged["stages"]["x_publish"]["claim_id"],
            unchanged["stages"]["x-publish"],
        )
        self.assertIn("本投稿は確定済み", controls)
        self.assertNotIn("結果不存在を確認、再許可待べしへ戻す", controls)
        with self.assertRaises(note_team.NoteTeamError):
            worker.publish(self.root, self.run_id)

    def test_expired_claim_cannot_record_x_component(self) -> None:
        with mock.patch.object(worker.post_to_x, "get_identity", side_effect=self.identity):
            worker.build_preflight(self.root, self.run_id)
        note_team.authorize_external(
            self.root, self.run_id, "x_publish", owner_session_confirmed=True
        )
        note_team.claim_external(self.root, self.run_id, "x_publish")
        state = note_team.load_state(self.root, self.run_id)
        state["stages"]["x_publish"]["claim_expires_at"] = "2000-01-01T00:00:00+09:00"
        note_team.atomic_write_json(note_team.state_path(self.root, self.run_id), state)
        with self.assertRaisesRegex(note_team.NoteTeamError, "claim期限が切れ"):
            note_team.record_external_component(
                self.root,
                self.run_id,
                "x-publish",
                "main",
                "100001",
                "https://x.com/testuser/status/100001",
            )


if __name__ == "__main__":
    unittest.main()
