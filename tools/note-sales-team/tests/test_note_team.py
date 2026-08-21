from __future__ import annotations

import importlib.util
import http.cookiejar
import json
import os
import re
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "note_team.py"
SPEC = importlib.util.spec_from_file_location("note_team", MODULE_PATH)
note_team = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(note_team)


class NoteTeamTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "AGENTS.md").write_text("test\n", encoding="utf-8")
        project = self.root / ".company/projects/note販売AIチーム"
        (project / "config").mkdir(parents=True)
        (project / "data").mkdir(parents=True)
        legacy = self.root / ".company/outputs/note-articles"
        legacy.mkdir(parents=True)
        accounts = {
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
        }
        (legacy / "accounts.json").write_text(
            json.dumps(accounts, ensure_ascii=False), encoding="utf-8"
        )
        (legacy / "history.json").write_text("[]\n", encoding="utf-8")
        config = {
            "timezone": "Asia/Tokyo",
            "project_root": ".company/projects/note販売AIチーム",
            "legacy_accounts_path": ".company/outputs/note-articles/accounts.json",
            "legacy_history_path": ".company/outputs/note-articles/history.json",
            "default_account_id": "you-ai-dx",
            "default_theme_id": "ai-utilization",
            "x_account": {"user_id": "12345", "username": "testuser"},
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
                "note_csv": ".company/projects/note販売AIチーム/data/note_metrics.csv",
                "x_csv": ".company/projects/note販売AIチーム/data/x_metrics.csv",
            },
            "style_sources": {
                "candidate_registry_path": ".company/projects/note販売AIチーム/data/style-candidates.json",
                "registry_path": ".company/projects/note販売AIチーム/data/style-corpus.json",
                "minimum_note_samples": 3,
                "minimum_x_samples": 20,
                "require_owner_approval": True,
            },
        }
        (project / "config/team.json").write_text(
            json.dumps(config, ensure_ascii=False), encoding="utf-8"
        )
        (project / "data/note_metrics.csv").write_text(
            "date,run_id,account_id,title,pv,likes,sales_count,revenue_yen,price_yen\n",
            encoding="utf-8",
        )
        (project / "data/x_metrics.csv").write_text(
            "date,run_id,variant,impressions,engagements,link_clicks\n", encoding="utf-8"
        )
        style_samples = project / "data/style-samples"
        style_samples.mkdir()
        note_candidates = []
        for number in range(1, 4):
            source = style_samples / f"note-{number:02d}.md"
            source.write_text(f"# 公開記事{number}\n\n本人の公開済み記事候補です。\n", encoding="utf-8")
            note_candidates.append(
                {
                    "candidate_id": f"note-{number:02d}",
                    "title": f"公開記事{number}",
                    "source_path": source.relative_to(self.root).as_posix(),
                    "source_url": f"https://note.com/you_ai_dx/n/nstyle{number:02d}",
                    "public_url": f"https://note.com/you_ai_dx/n/nstyle{number:02d}",
                    "published_at": "2026-07-01",
                    "public_verified_at": "2026-07-19",
                    "verification_precision": "date",
                    "preview": f"プレビュー{number}",
                    "metrics": {
                        "scope": "publication-verified-only",
                        "sales_units": "N/A",
                        "sales_amount_yen": "N/A",
                        "paid_conversion_rate": "N/A",
                    },
                    "constraints": ["売上不明", "本人手書きとは未確定"],
                    "file_sha256": note_team.sha256_file(source),
                }
            )
        x_candidates = []
        for number in range(1, 21):
            text = f"AI活用の実投稿候補{number}です。"
            tweet_id = str(10000 + number)
            x_candidates.append(
                {
                    "candidate_id": f"x-{number:02d}",
                    "tweet_id": tweet_id,
                    "title": f"X実投稿{number}",
                    "source_url": f"https://x.com/testuser/status/{tweet_id}",
                    "text": text,
                    "preview": text,
                    "posted_at": note_team.iso_now(),
                    "author_id": "12345",
                    "author_username": "testuser",
                    "source_queue": f"state/queue/item-{number:02d}.json",
                    "source_ledger": f"posting_ledger/item-{number:02d}.json",
                    "metrics": {
                        "public_metrics": {"impressions": number, "likes": 0}
                    },
                    "metrics_as_of": "2026-07-19",
                    "brand_style_candidate": True,
                    "owner_style_approval_required": True,
                    "constraints": ["X反応は小規模", "本人手書きとは未確定"],
                    "text_sha256": note_team.sha256_bytes(text.encode("utf-8")),
                }
            )
        manifest = note_team.style_selection_manifest(note_candidates, x_candidates)
        self.style_candidate_path = project / "data/style-candidates.json"
        self.style_registry_path = project / "data/style-corpus.json"
        self.style_candidate_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "status": "owner-approval-required",
                    "generated_at": note_team.iso_now(),
                    "source_root_env": "SHORTS_FACTORY_ROOT",
                    "metrics_as_of": "2026-07-19",
                    "brand_style_candidate": True,
                    "owner_style_approval_required": True,
                    "limitations": ["売上不明", "X反応は小規模", "本人手書きとは未確定"],
                    "note_candidates": note_candidates,
                    "x_candidates": x_candidates,
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
        self.reset_style_registry()
        note_team.approve_style_corpus(
            self.root,
            note_team.sha256_file(self.style_candidate_path),
            note_team.sha256_file(self.style_registry_path),
            owner_session_confirmed=True,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def reset_style_registry(self) -> None:
        self.style_registry_path.write_text(
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
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def rewrite_style_candidate_pack(self, payload: dict) -> None:
        notes = payload.get("note_candidates", [])
        x_posts = payload.get("x_candidates", [])
        manifest = note_team.style_selection_manifest(notes, x_posts)
        payload["selection_manifest"] = manifest
        payload["selection_sha256"] = note_team.sha256_bytes(
            note_team.canonical_json_bytes(manifest)
        )
        self.style_candidate_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    def start_approval_test_server(self, token: str):
        server = ThreadingHTTPServer(
            ("127.0.0.1", 0), note_team.make_handler(self.root, token)
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread, f"http://127.0.0.1:{server.server_address[1]}"

    def bootstrap_approval_test_session(self, base: str, token: str):
        class RecordingRedirectHandler(urllib.request.HTTPRedirectHandler):
            set_cookie_header: str | None = None

            def redirect_request(self, req, fp, code, msg, headers, newurl):
                self.set_cookie_header = headers.get("Set-Cookie")
                redirected = super().redirect_request(
                    req, fp, code, msg, headers, newurl
                )
                if redirected is not None:
                    # A browser's 303 follow-up is a fresh GET navigation; it
                    # does not carry the form POST's Origin header forward.
                    redirected.remove_header("Origin")
                return redirected

        cookie_jar = http.cookiejar.CookieJar()
        redirects = RecordingRedirectHandler()
        opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(cookie_jar), redirects
        )
        with opener.open(base + "/?token=" + token, timeout=3) as response:
            page = response.read().decode("utf-8")
        return opener, page, redirects.set_cookie_header

    def style_approval_post(
        self,
        opener,
        base: str,
        *,
        csrf: str,
        candidate_pack_sha256: str,
        registry_sha256: str,
        origin: str | None,
    ):
        body = urllib.parse.urlencode(
            {
                "csrf": csrf,
                "action": "approve_style_corpus",
                "candidate_pack_sha256": candidate_pack_sha256,
                "registry_sha256": registry_sha256,
            }
        ).encode("utf-8")
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        if origin is not None:
            headers["Origin"] = origin
        request = urllib.request.Request(
            base + "/action", data=body, headers=headers, method="POST"
        )
        return opener.open(request, timeout=3)

    def symlink_or_skip(
        self, link: Path, target: Path, *, target_is_directory: bool = False
    ) -> None:
        try:
            link.symlink_to(target, target_is_directory=target_is_directory)
        except OSError as exc:
            if os.name == "nt" and getattr(exc, "winerror", None) == 1314:
                self.skipTest("Windowsでsymlink作成権限がないため実リンク防御テストを省略")
            raise

    def artifact(self, run_id: str, name: str, content: str = "ok") -> str:
        path = self.root / note_team.RUNS_REL / run_id / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return name

    def plan_artifact(self, run_id: str, suffix: str = "") -> str:
        return self.artifact(
            run_id,
            "plan.md",
            "proposal_id: plan-01\n企画A\n\n"
            "proposal_id: plan-02\n企画B\n\n"
            "proposal_id: plan-03\n企画C\n"
            + suffix,
        )

    def promotion_artifact(self, run_id: str) -> str:
        variants = [
            {
                "promotion_id": f"x-0{number}",
                "intent": f"告知案{number}",
                "primary_text": f"AI活用の実例を1つ紹介します。案{number}",
                "reply_text_template": "記事の詳細はこちらです。 [NOTE_URL]",
            }
            for number in range(1, 4)
        ]
        return self.artifact(
            run_id,
            "promotion.json",
            json.dumps({"variants": variants}, ensure_ascii=False),
        )

    def analysis_artifact(self, run_id: str, month: str = "2026-07") -> str:
        result, _ = note_team.analyze_metrics(self.root, month)
        provenance = result["provenance"]
        return self.artifact(
            run_id,
            "analysis.md",
            f"metrics_month: {month}\n"
            f"note_csv_sha256: {provenance['note_csv']['sha256']}\n"
            f"x_csv_sha256: {provenance['x_csv']['sha256']}\n\n"
            f"metrics_snapshot_sha256: {note_team.metrics_snapshot_sha256(result)}\n\n"
            "# 分析\n継続・変更・次回方針\n",
        )

    def create(self, slug: str = "pilot"):
        return note_team.create_run(
            self.root, "you-ai-dx", "ai-utilization", slug, product_profile="free-standard"
        )

    def prepare_claimed_note_draft(self, slug: str):
        state, _ = self.create(slug)
        run_id = state["run_id"]
        self.artifact(run_id, "manuscript.md", "承認済みの原稿本文です。" * 4)
        directory = self.root / note_team.RUNS_REL / run_id
        snapshot, digest = note_team.snapshot_text(
            directory, "manuscript.md", "draft/final", 1
        )
        state["current_stage"] = "note_draft"
        for stage in ("plan", "outline", "draft", "promotion"):
            state["stages"][stage]["status"] = "approved"
        state["stages"]["draft"].update(
            {"artifact": snapshot, "artifact_sha256": digest}
        )
        state["stages"]["note_draft"]["status"] = "authorization_required"
        note_team.atomic_write_json(note_team.state_path(self.root, run_id), state)
        self.artifact(
            run_id,
            "note-preflight.json",
            json.dumps(
                {
                    "account_id": "you-ai-dx",
                    "expected_note_id": "you_ai_dx",
                    "observed_note_id": "you_ai_dx",
                    "editor_ready": True,
                    "operation": "create_new_draft",
                    "editor_url": "https://note.com/notes/new",
                    "initial_content_empty": True,
                    "checked_at": note_team.iso_now(),
                }
            ),
        )
        note_team.submit_preflight(self.root, run_id, "note-preflight.json")
        note_team.authorize_external(
            self.root, run_id, "note_draft", owner_session_confirmed=True
        )
        return note_team.claim_external(self.root, run_id, "note_draft")

    def note_draft_outcome(self, state: dict) -> dict:
        stage = state["stages"]["note_draft"]
        return {
            "account_id": "you-ai-dx",
            "expected_note_id": "you_ai_dx",
            "observed_note_id": "you_ai_dx",
            "draft_url": "https://editor.note.com/notes/n-newdraft/edit/",
            "editor_draft_id": "n-newdraft",
            "operation": "create_new_draft",
            "initial_content_empty_before_write": True,
            "saved_indicator": True,
            "published": False,
            "draft_saved_at": note_team.iso_now(),
            "checked_at": note_team.iso_now(),
            "image_status": {
                "mode": "image-free",
                "heading_image_verified": False,
                "inline_images_expected": 0,
                "inline_images_verified": 0,
                "pending": [],
            },
            "claim_id": stage["claim_id"],
            "manuscript_sha256": state["stages"]["draft"]["artifact_sha256"],
            "preflight_sha256": stage["preflight_sha256"],
        }

    def qa_artifact(
        self,
        run_id: str,
        stage: str,
        artifact: str,
        unit: str | None = None,
        score: int = 90,
        fatal_violations: list[str] | None = None,
    ) -> str:
        source = self.root / note_team.RUNS_REL / run_id / artifact
        payload = {
            "stage": stage,
            "unit": unit,
            "checked_artifact_sha256": note_team.sha256_file(source),
            "score": score,
            "verdict": "PASS" if score >= 85 and not fatal_violations else "FAIL",
            "fatal_violations": fatal_violations or [],
            "checked_at": "2026-07-19T10:00:00+09:00",
            "reviewer": "note-director",
        }
        name = f"qa/{stage}-{unit or 'final'}.json"
        return self.artifact(run_id, name, json.dumps(payload, ensure_ascii=False))

    def submit(
        self,
        run_id: str,
        stage: str,
        artifact: str,
        actor: str = "agent",
        unit: str | None = None,
    ):
        qa = self.qa_artifact(run_id, stage, artifact, unit)
        return note_team.submit_artifact(
            self.root, run_id, stage, artifact, actor, unit, qa
        )

    def test_full_state_machine_with_chapter_approval_and_external_gate(self) -> None:
        state, existed = self.create()
        self.assertFalse(existed)
        run_id = state["run_id"]

        self.plan_artifact(run_id)
        self.submit(run_id, "plan", "plan.md", "note-planner")
        note_team.select_plan(
            self.root, run_id, "plan-01", owner_session_confirmed=True
        )
        note_team.approve(self.root, run_id, "plan", owner_session_confirmed=True)

        self.artifact(run_id, "outline.md")
        self.submit(run_id, "outline", "outline.md", "note-architect")
        note_team.approve(self.root, run_id, "outline", owner_session_confirmed=True)

        note_team.set_units(
            self.root,
            run_id,
            "draft",
            ["chapter-01", "chapter-02", "chapter-03", "chapter-04"],
        )
        self.artifact(run_id, "chapters/chapter-01.md")
        self.submit(run_id, "draft", "chapters/chapter-01.md", "note-writer", "chapter-01")
        note_team.request_revision(
            self.root,
            run_id,
            "draft",
            "具体例を追加",
            unit="chapter-01",
            owner_session_confirmed=True,
        )
        self.submit(run_id, "draft", "chapters/chapter-01.md", "note-writer", "chapter-01")
        note_team.approve(
            self.root,
            run_id,
            "draft",
            unit="chapter-01",
            owner_session_confirmed=True,
        )

        self.artifact(run_id, "chapters/chapter-02.md")
        self.submit(run_id, "draft", "chapters/chapter-02.md", "note-writer", "chapter-02")
        state = note_team.approve(
            self.root,
            run_id,
            "draft",
            unit="chapter-02",
            owner_session_confirmed=True,
        )
        self.assertEqual(state["stages"]["draft"]["status"], "unit_cycle")

        for chapter in ("chapter-03", "chapter-04"):
            path = f"chapters/{chapter}.md"
            self.artifact(run_id, path)
            self.submit(run_id, "draft", path, "note-writer", chapter)
            state = note_team.approve(
                self.root,
                run_id,
                "draft",
                unit=chapter,
                owner_session_confirmed=True,
            )
        self.assertEqual(state["stages"]["draft"]["status"], "awaiting_final_output")

        self.artifact(run_id, "manuscript.md", "承認済みの最終原稿本文です。" * 3)
        self.submit(run_id, "draft", "manuscript.md", "note-writer")
        note_team.request_revision(
            self.root,
            run_id,
            "draft",
            "結論を簡潔に",
            owner_session_confirmed=True,
        )
        self.submit(run_id, "draft", "manuscript.md", "note-writer")
        note_team.approve(self.root, run_id, "draft", owner_session_confirmed=True)

        self.promotion_artifact(run_id)
        self.submit(run_id, "promotion", "promotion.json", "note-promoter")
        note_team.select_promotion(
            self.root, run_id, "x-01", owner_session_confirmed=True
        )
        state = note_team.approve(
            self.root, run_id, "promotion", owner_session_confirmed=True
        )
        self.assertEqual(state["stages"]["note_draft"]["status"], "authorization_required")

        note_draft_record = {
                "account_id": "you-ai-dx",
                "expected_note_id": "you_ai_dx",
                "observed_note_id": "you_ai_dx",
            "draft_url": "https://editor.note.com/notes/n-test/edit/",
            "editor_draft_id": "n-test",
                "operation": "create_new_draft",
                "initial_content_empty_before_write": True,
                "saved_indicator": True,
                "published": False,
                "draft_saved_at": "2026-07-19T10:00:00+09:00",
                "checked_at": "2026-07-19T10:00:00+09:00",
                "image_status": {
                    "mode": "image-free",
                    "heading_image_verified": False,
                    "inline_images_expected": 0,
                    "inline_images_verified": 0,
                    "pending": [],
                },
            }
        self.artifact(run_id, "note-draft.json", json.dumps(note_draft_record))
        with self.assertRaises(note_team.NoteTeamError):
            note_team.submit_artifact(
                self.root, run_id, "note_draft", "note-draft.json", "note-article-publisher"
            )
        preflight = json.dumps(
            {
                "account_id": "you-ai-dx",
                "expected_note_id": "you_ai_dx",
                "observed_note_id": "you_ai_dx",
                "editor_ready": True,
                "operation": "create_new_draft",
                "editor_url": "https://note.com/notes/new",
                "initial_content_empty": True,
                "checked_at": note_team.iso_now(),
            }
        )
        self.artifact(run_id, "note-preflight.json", preflight)
        note_team.submit_preflight(self.root, run_id, "note-preflight.json")
        note_team.authorize_external(
            self.root, run_id, "note_draft", owner_session_confirmed=True
        )
        claimed = note_team.claim_external(self.root, run_id, "note_draft")
        with self.assertRaises(note_team.NoteTeamError):
            note_team.claim_external(self.root, run_id, "note_draft")
        note_draft_record.update(
            {
                "claim_id": claimed["stages"]["note_draft"]["claim_id"],
                "manuscript_sha256": claimed["stages"]["draft"]["artifact_sha256"],
                "preflight_sha256": claimed["stages"]["note_draft"]["preflight_sha256"],
                "draft_saved_at": note_team.iso_now(),
                "checked_at": note_team.iso_now(),
            }
        )
        self.artifact(run_id, "note-draft.json", json.dumps(note_draft_record))
        note_team.submit_artifact(
            self.root, run_id, "note_draft", "note-draft.json", "note-article-publisher"
        )
        note_team.approve(
            self.root, run_id, "note_draft", owner_session_confirmed=True
        )

        state = note_team.load_state(self.root, run_id)
        note_publish_preflight = {
            "account_id": "you-ai-dx",
            "expected_note_id": "you_ai_dx",
            "observed_note_id": "you_ai_dx",
            "operation": "publish_existing_draft",
            "editor_ready": True,
            "editor_draft_id": "n-test",
            "draft_url": "https://editor.note.com/notes/n-test/edit/",
            "draft_record_sha256": state["stages"]["note_draft"]["artifact_sha256"],
            "manuscript_sha256": state["stages"]["draft"]["artifact_sha256"],
            "content_readback_verified": True,
            "publish_settings_verified": True,
            "publish_button_ready": True,
            "published": False,
            "checked_at": note_team.iso_now(),
        }
        self.artifact(
            run_id,
            "note-publish-preflight.json",
            json.dumps(note_publish_preflight, ensure_ascii=False),
        )
        note_team.submit_preflight(
            self.root,
            run_id,
            "note-publish-preflight.json",
            stage="note_publish",
        )
        note_team.authorize_external(
            self.root, run_id, "note_publish", owner_session_confirmed=True
        )
        claimed = note_team.claim_external(self.root, run_id, "note_publish")
        public_url = "https://note.com/you_ai_dx/n/n-test"
        note_publish_result = {
            "account_id": "you-ai-dx",
            "expected_note_id": "you_ai_dx",
            "observed_note_id": "you_ai_dx",
            "operation": "publish_existing_draft",
            "editor_draft_id": "n-test",
            "draft_url": "https://editor.note.com/notes/n-test/edit/",
            "public_url": public_url,
            "published": True,
            "content_readback_verified": True,
            "publish_settings_verified": True,
            "published_at": note_team.iso_now(),
            "checked_at": note_team.iso_now(),
            "claim_id": claimed["stages"]["note_publish"]["claim_id"],
            "manuscript_sha256": claimed["stages"]["draft"]["artifact_sha256"],
            "draft_record_sha256": claimed["stages"]["note_draft"]["artifact_sha256"],
            "preflight_sha256": claimed["stages"]["note_publish"]["preflight_sha256"],
        }
        self.artifact(
            run_id,
            "note-publish-result.json",
            json.dumps(note_publish_result, ensure_ascii=False),
        )
        note_team.submit_artifact(
            self.root,
            run_id,
            "note_publish",
            "note-publish-result.json",
            "note-publish-worker",
        )
        note_team.approve(
            self.root, run_id, "note_publish", owner_session_confirmed=True
        )

        state = note_team.load_state(self.root, run_id)
        variant = note_team.selected_promotion_variant(self.root, state)
        primary_text = variant["primary_text"]
        reply_text = variant["reply_text_template"].replace("[NOTE_URL]", public_url)
        x_preflight = {
            "platform": "x",
            "operation": "create_post_and_reply",
            "expected_x_user_id": "12345",
            "observed_x_user_id": "12345",
            "expected_x_username": "testuser",
            "observed_x_username": "testuser",
            "selected_promotion_id": "x-01",
            "primary_text": primary_text,
            "reply_text": reply_text,
            "primary_text_sha256": note_team.sha256_bytes(primary_text.encode("utf-8")),
            "reply_text_sha256": note_team.sha256_bytes(reply_text.encode("utf-8")),
            "note_public_url": public_url,
            "promotion_sha256": state["stages"]["promotion"]["artifact_sha256"],
            "note_publish_sha256": state["stages"]["note_publish"]["artifact_sha256"],
            "dry_run_ready": True,
            "checked_at": note_team.iso_now(),
        }
        self.artifact(
            run_id, "x-preflight.json", json.dumps(x_preflight, ensure_ascii=False)
        )
        note_team.submit_preflight(
            self.root, run_id, "x-preflight.json", "x-publish-worker", "x_publish"
        )
        note_team.authorize_external(
            self.root, run_id, "x_publish", owner_session_confirmed=True
        )
        claimed = note_team.claim_external(self.root, run_id, "x_publish")
        primary_id, reply_id = "100001", "100002"
        primary_url = f"https://x.com/testuser/status/{primary_id}"
        reply_url = f"https://x.com/testuser/status/{reply_id}"
        note_team.record_external_component(
            self.root, run_id, "x_publish", "main", primary_id, primary_url
        )
        note_team.record_external_component(
            self.root, run_id, "x_publish", "reply", reply_id, reply_url
        )
        posted_at = note_team.iso_now()
        x_result = {
            **{
                key: x_preflight[key]
                for key in (
                    "platform",
                    "operation",
                    "expected_x_user_id",
                    "observed_x_user_id",
                    "expected_x_username",
                    "observed_x_username",
                    "selected_promotion_id",
                    "note_public_url",
                    "primary_text_sha256",
                    "reply_text_sha256",
                    "promotion_sha256",
                    "note_publish_sha256",
                )
            },
            "primary_tweet_id": primary_id,
            "primary_tweet_url": primary_url,
            "primary_author_id": "12345",
            "reply_tweet_id": reply_id,
            "reply_tweet_url": reply_url,
            "reply_author_id": "12345",
            "reply_to_tweet_id": primary_id,
            "api_readback_verified": True,
            "posted_at": posted_at,
            "reply_posted_at": posted_at,
            "checked_at": posted_at,
            "claim_id": claimed["stages"]["x_publish"]["claim_id"],
            "preflight_sha256": claimed["stages"]["x_publish"]["preflight_sha256"],
        }
        self.artifact(
            run_id, "x-publish-result.json", json.dumps(x_result, ensure_ascii=False)
        )
        note_team.submit_artifact(
            self.root,
            run_id,
            "x_publish",
            "x-publish-result.json",
            "x-publish-worker",
        )
        note_team.approve(
            self.root, run_id, "x_publish", owner_session_confirmed=True
        )

        self.analysis_artifact(run_id)
        self.submit(run_id, "analysis", "analysis.md", "note-analyst")
        state = note_team.approve(
            self.root, run_id, "analysis", owner_session_confirmed=True
        )
        self.assertEqual(state["status"], "completed")
        self.assertGreaterEqual(len(state["approvals"]), 11)

    def test_create_is_idempotent_and_conflict_safe(self) -> None:
        first, existed = self.create("same")
        second, existed_again = self.create("same")
        self.assertFalse(existed)
        self.assertTrue(existed_again)
        self.assertEqual(first["run_id"], second["run_id"])
        with self.assertRaises(note_team.NoteTeamError):
            note_team.create_run(
                self.root,
                "you-ai-dx",
                "ai-utilization",
                "different",
                run_id_value=first["run_id"],
            )

    def test_concurrent_create_is_idempotent_and_incomplete_run_recovers(self) -> None:
        barrier = threading.Barrier(3)
        outcomes: list[tuple[bool, str]] = []
        failures: list[Exception] = []

        def create_same() -> None:
            barrier.wait()
            try:
                state, existed = self.create("parallel-create")
                outcomes.append((existed, state["run_id"]))
            except Exception as exc:  # pragma: no cover - asserted below
                failures.append(exc)

        threads = [threading.Thread(target=create_same) for _ in range(2)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(timeout=3)
        self.assertEqual(failures, [])
        self.assertEqual(sorted(existed for existed, _ in outcomes), [False, True])
        self.assertEqual(len({run_id for _, run_id in outcomes}), 1)

        poisoned_id = "20260719-you-ai-dx-incomplete"
        poisoned = self.root / note_team.RUNS_REL / poisoned_id
        poisoned.mkdir(mode=0o700)
        (poisoned / "partial.txt").write_text("recoverable", encoding="utf-8")
        state, existed = note_team.create_run(
            self.root,
            "you-ai-dx",
            "ai-utilization",
            "incomplete",
            run_id_value=poisoned_id,
        )
        self.assertFalse(existed)
        self.assertEqual(state["run_id"], poisoned_id)
        recovered = list((poisoned.parent / ".incomplete").glob(poisoned_id + "-*"))
        self.assertEqual(len(recovered), 1)
        self.assertEqual(
            (recovered[0] / "partial.txt").read_text(encoding="utf-8"), "recoverable"
        )

    def test_path_traversal_and_secret_comments_are_rejected(self) -> None:
        state, _ = self.create("guards")
        run_id = state["run_id"]
        outside = self.root / "outside.md"
        outside.write_text("bad", encoding="utf-8")
        with self.assertRaises(note_team.NoteTeamError):
            note_team.submit_artifact(self.root, run_id, "plan", str(outside), "agent")
        self.plan_artifact(run_id)
        self.submit(run_id, "plan", "plan.md", "agent")
        note_team.select_plan(
            self.root, run_id, "plan-01", owner_session_confirmed=True
        )
        with self.assertRaises(note_team.NoteTeamError):
            note_team.approve(
                self.root,
                run_id,
                "plan",
                comment="api_key=abcdefghijklmnop",
                owner_session_confirmed=True,
            )
        with self.assertRaises(note_team.NoteTeamError):
            note_team.create_run(
                self.root,
                "you-ai-dx",
                "ai-utilization",
                "sk-abcdefghijklmnop",
            )

    def test_note_draft_identity_mismatch_is_rejected(self) -> None:
        state, _ = self.create("identity")
        run_id = state["run_id"]
        state["current_stage"] = "note_draft"
        state["stages"]["plan"]["status"] = "approved"
        state["stages"]["note_draft"]["status"] = "awaiting_output"
        note_team.atomic_write_json(note_team.state_path(self.root, run_id), state)
        relative = self.artifact(
            run_id,
            "note-draft.json",
            json.dumps(
                {
                    "account_id": "you-ai-dx",
                    "expected_note_id": "you_ai_dx",
                    "observed_note_id": "wrong_account",
                    "draft_url": "https://editor.note.com/notes/n-test/edit/",
                    "editor_draft_id": "n-test",
                    "saved_indicator": True,
                    "published": False,
                    "checked_at": "2026-07-19T10:00:00+09:00",
                    "image_status": {
                        "mode": "image-free",
                        "heading_image_verified": False,
                        "inline_images_expected": 0,
                        "inline_images_verified": 0,
                        "pending": [],
                    },
                }
            ),
        )
        with self.assertRaises(note_team.NoteTeamError):
            note_team.validate_note_draft_record(
                self.root,
                state,
                self.root / note_team.RUNS_REL / run_id / relative,
            )

    def test_exact_metric_analysis(self) -> None:
        data = self.root / ".company/projects/note販売AIチーム/data"
        (data / "note_metrics.csv").write_text(
            "date,run_id,account_id,title,pv,likes,sales_count,revenue_yen,price_yen\n"
            "2026-07-01,r1,you-ai-dx,A,100,10,2,1000,500\n"
            "2026-07-02,r2,you-ai-dx,B,50,5,0,0,0\n",
            encoding="utf-8",
        )
        (data / "x_metrics.csv").write_text(
            "date,run_id,variant,impressions,engagements,link_clicks\n"
            "2026-07-01,r1,a,1000,50,20\n"
            "2026-07-02,r2,b,500,25,5\n",
            encoding="utf-8",
        )
        result, markdown = note_team.analyze_metrics(self.root, "2026-07")
        self.assertEqual(result["note"]["pv"], 150)
        self.assertEqual(result["note"]["sales_count"], 2)
        self.assertEqual(result["note"]["paid_pv"], 100)
        self.assertEqual(result["note"]["paid_conversion_rate"], "2.00%")
        self.assertEqual(result["x"]["click_rate"], "1.67%")
        self.assertEqual(result["comparison"]["sold"]["avg_pv"], 100)
        self.assertEqual(result["comparison"]["free"]["articles"], 1)
        self.assertEqual(result["comparison"]["unsold"]["articles"], 0)
        self.assertIn("入力CSVの実値だけ", markdown)
        self.assertEqual(
            result["provenance"]["metrics_snapshot_sha256"],
            note_team.metrics_snapshot_sha256(result),
        )
        self.assertIn(result["provenance"]["metrics_snapshot_sha256"], markdown)
        later = json.loads(json.dumps(result))
        later["provenance"]["generated_at"] = "2099-01-01T00:00:00+09:00"
        self.assertEqual(
            note_team.metrics_snapshot_sha256(result),
            note_team.metrics_snapshot_sha256(later),
        )

    def test_daily_delta_counts_distinct_x_posts_and_stable_note_identity(self) -> None:
        data = self.root / ".company/projects/note販売AIチーム/data"
        (data / "note_metrics.csv").write_text(
            "date,run_id,account_id,title,pv,likes,sales_count,revenue_yen,price_yen\n"
            "2026-07-01,r1,you-ai-dx,A,10,1,0,0,0\n"
            "2026-07-02,r1,you-ai-dx,A,20,2,0,0,0\n",
            encoding="utf-8",
        )
        (data / "x_metrics.csv").write_text(
            "date,run_id,variant,impressions,engagements,link_clicks\n"
            "2026-07-01,r1,a,100,10,3\n"
            "2026-07-02,r1,a,200,20,6\n"
            "2026-07-02,r1,b,50,5,1\n",
            encoding="utf-8",
        )
        result, _ = note_team.analyze_metrics(self.root, "2026-07")
        self.assertEqual(result["x"]["posts"], 2)
        self.assertEqual(result["x"]["impressions"], 350)

        (data / "note_metrics.csv").write_text(
            "date,run_id,account_id,title,pv,likes,sales_count,revenue_yen,price_yen\n"
            "2026-07-01,r1,you-ai-dx,A,10,1,0,0,0\n"
            "2026-07-02,r1,other-account,B,20,2,0,0,0\n",
            encoding="utf-8",
        )
        with self.assertRaises(note_team.NoteTeamError):
            note_team.analyze_metrics(self.root, "2026-07")

    def test_title_changes_and_unicode_forms_do_not_change_run_identity(self) -> None:
        data = self.root / ".company/projects/note販売AIチーム/data"
        (data / "note_metrics.csv").write_text(
            "date,run_id,account_id,title,pv,likes,sales_count,revenue_yen,price_yen\n"
            "2026-06-30,r1,you-ai-dx,Old title,10,1,0,0,0\n"
            "2026-07-01,r1,you-ai-dx,が,20,2,0,0,0\n"
            "2026-07-02,r1,you-ai-dx,が,30,3,0,0,0\n",
            encoding="utf-8",
        )
        result, _ = note_team.analyze_metrics(self.root, "2026-07")
        self.assertEqual(result["note"]["articles"], 1)
        self.assertEqual(result["note"]["pv"], 50)

    def test_sales_revenue_consistency_line_numbers_and_integer_bounds(self) -> None:
        data = self.root / ".company/projects/note販売AIチーム/data"
        header = "date,run_id,account_id,title,pv,likes,sales_count,revenue_yen,price_yen\n"
        for row in (
            "2026-07-01,r1,you-ai-dx,A,10,1,0,1000,500\n",
            "2026-07-01,r1,you-ai-dx,A,10,1,2,0,500\n",
        ):
            (data / "note_metrics.csv").write_text(header + row, encoding="utf-8")
            with self.assertRaises(note_team.NoteTeamError):
                note_team.analyze_metrics(self.root, "2026-07")

        (data / "note_metrics.csv").write_text(
            header
            + "2026-06-30,r0,you-ai-dx,June,1,0,0,0,0\n"
            + "2026-07-01,r1,you-ai-dx,July,10,bad,0,0,0\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(note_team.NoteTeamError, "CSV 3行目"):
            note_team.analyze_metrics(self.root, "2026-07")

        (data / "note_metrics.csv").write_text(
            header
            + "2026-07-01,r1,you-ai-dx,Huge,10,"
            + "9" * 4000
            + ",0,0,0\n",
            encoding="utf-8",
        )
        with self.assertRaises(note_team.NoteTeamError):
            note_team.analyze_metrics(self.root, "2026-07")

    def test_note_attestation_urls_must_be_exact(self) -> None:
        note_team.validate_new_draft_url("https://note.com/notes/new")
        note_team.validate_new_draft_url("https://note.com:443/notes/new/")
        note_team.validate_editor_draft_url(
            "https://editor.note.com/notes/n-test/edit/", "n-test", "note下書き確認"
        )
        for value in (
            "https://note.com:444/notes/new",
            "https://note.com/notes/new?next=1",
            "https://note.com/notes/new#fragment",
            "https://NOTE.com/notes/new",
        ):
            with self.assertRaises(note_team.NoteTeamError):
                note_team.validate_new_draft_url(value)
        for value in (
            "https://editor.note.com:444/notes/n-test/edit/",
            "https://editor.note.com/notes/n-test/edit/?preview=1",
            "https://editor.note.com/notes/n-test/edit/#fragment",
        ):
            with self.assertRaises(note_team.NoteTeamError):
                note_team.validate_editor_draft_url(value, "n-test", "note下書き確認")

    def test_invalid_metrics_are_rejected(self) -> None:
        path = self.root / ".company/projects/note販売AIチーム/data/note_metrics.csv"
        path.write_text(
            "date,run_id,account_id,title,pv,likes,sales_count,revenue_yen,price_yen\n"
            "2026-07-01,r1,you-ai-dx,A,1,0,2,1000,500\n",
            encoding="utf-8",
        )
        with self.assertRaises(note_team.NoteTeamError):
            note_team.analyze_metrics(self.root, "2026-07")

        path.write_text(
            "date,run_id,account_id,title,pv,likes,sales_count,revenue_yen,price_yen\n"
            "2026-07-01,r1,you-ai-dx,Missing,10,1,0,0\n",
            encoding="utf-8",
        )
        with self.assertRaises(note_team.NoteTeamError):
            note_team.analyze_metrics(self.root, "2026-07")
        path.write_text(
            "date,run_id,account_id,title,pv,likes,sales_count,revenue_yen,price_yen\n"
            "2026-07-01,r1,you-ai-dx,Extra,10,1,0,0,0,unexpected\n",
            encoding="utf-8",
        )
        with self.assertRaises(note_team.NoteTeamError):
            note_team.analyze_metrics(self.root, "2026-07")
        path.write_text(
            "date,run_id,run_id,title,pv,likes,sales_count,revenue_yen,price_yen\n",
            encoding="utf-8",
        )
        with self.assertRaises(note_team.NoteTeamError):
            note_team.analyze_metrics(self.root, "2026-07")

        path.write_text(
            "date,run_id,account_id,title,pv,likes,sales_count,revenue_yen,price_yen\n"
            "2026-07-01,r1,you-ai-dx,Free,10,1,1,500,0\n",
            encoding="utf-8",
        )
        with self.assertRaises(note_team.NoteTeamError):
            note_team.analyze_metrics(self.root, "2026-07")

    def test_director_gate_and_reviewed_snapshot_are_enforced(self) -> None:
        state, _ = self.create("director")
        run_id = state["run_id"]
        self.plan_artifact(run_id, "\nreviewed bytes")
        with self.assertRaises(note_team.NoteTeamError):
            note_team.submit_artifact(self.root, run_id, "plan", "plan.md", "agent")
        failed_qa = self.qa_artifact(run_id, "plan", "plan.md", score=84)
        with self.assertRaises(note_team.NoteTeamError):
            note_team.submit_artifact(
                self.root, run_id, "plan", "plan.md", "agent", qa_artifact=failed_qa
            )

        state = self.submit(run_id, "plan", "plan.md")
        reviewed = state["stages"]["plan"]
        self.assertEqual(reviewed["director_qa"]["score"], 90)
        self.artifact(run_id, "plan.md", "changed after submit")
        note_team.select_plan(
            self.root, run_id, "plan-01", owner_session_confirmed=True
        )
        state = note_team.approve(
            self.root, run_id, "plan", owner_session_confirmed=True
        )
        self.assertEqual(state["current_stage"], "outline")
        self.assertEqual(
            state["approvals"][-1]["artifact_sha256"], reviewed["artifact_sha256"]
        )

    def test_tampered_director_qa_snapshot_blocks_selection_and_approval(self) -> None:
        state, _ = self.create("tampered-director-qa")
        run_id = state["run_id"]
        self.plan_artifact(run_id)
        state = self.submit(run_id, "plan", "plan.md")
        qa_path = (
            self.root
            / note_team.RUNS_REL
            / run_id
            / state["stages"]["plan"]["director_qa"]["artifact"]
        )
        qa_path.chmod(0o600)
        qa_path.write_text("{}\n", encoding="utf-8")
        with self.assertRaises(note_team.NoteTeamError):
            note_team.select_plan(
                self.root, run_id, "plan-01", owner_session_confirmed=True
            )

        # Even if an old state was manually given a selected plan, approval
        # re-verifies the immutable QA evidence independently.
        tampered = note_team.load_state(self.root, run_id)
        tampered["selected_plan_id"] = "plan-01"
        note_team.atomic_write_json(note_team.state_path(self.root, run_id), tampered)
        with self.assertRaises(note_team.NoteTeamError):
            note_team.approve(
                self.root, run_id, "plan", owner_session_confirmed=True
            )

    def test_tampered_snapshot_is_rejected_at_approval(self) -> None:
        state, _ = self.create("tamper")
        run_id = state["run_id"]
        self.plan_artifact(run_id, "\noriginal")
        state = self.submit(run_id, "plan", "plan.md")
        note_team.select_plan(
            self.root, run_id, "plan-01", owner_session_confirmed=True
        )
        snapshot = self.root / note_team.RUNS_REL / run_id / state["stages"]["plan"]["artifact"]
        snapshot.chmod(0o644)
        snapshot.write_text("tampered", encoding="utf-8")
        with self.assertRaises(note_team.NoteTeamError):
            note_team.approve(
                self.root, run_id, "plan", owner_session_confirmed=True
            )

    def test_paid_profile_can_plan_but_cannot_advance_without_fact_pack(self) -> None:
        state, existed = note_team.create_run(
            self.root,
            "you-ai-dx",
            "ai-utilization",
            "paid-ready",
            product_profile="paid-longform",
        )
        self.assertFalse(existed)
        run_id = state["run_id"]
        self.plan_artifact(run_id, "\nthree researched ideas")
        self.submit(run_id, "plan", "plan.md", "note-planner")
        note_team.select_plan(
            self.root, run_id, "plan-02", owner_session_confirmed=True
        )
        with self.assertRaises(note_team.NoteTeamError):
            note_team.approve(
                self.root, run_id, "plan", owner_session_confirmed=True
            )
        fact_pack = self.root / ".company/projects/note販売AIチーム/data/fact-pack.md"
        fact_pack.write_text(
            "owner_approved: true\n"
            "approved_at: 2026-07-19T10:00:00+09:00\n\n"
            "# 本人の体験\n公開可能な本人提供事実。\n",
            encoding="utf-8",
        )
        state = note_team.attach_fact_pack(self.root, run_id, fact_pack)
        self.assertIn("fact_pack", state["inputs"])
        with self.assertRaises(note_team.NoteTeamError):
            note_team.approve(
                self.root, run_id, "plan", owner_session_confirmed=True
            )
        with self.assertRaises(note_team.NoteTeamError):
            note_team.approve_fact_pack(self.root, run_id)
        state = note_team.approve_fact_pack(
            self.root, run_id, owner_session_confirmed=True
        )
        self.assertEqual(
            state["inputs"]["fact_pack"]["owner_approved_by"], "owner"
        )
        state = note_team.approve(
            self.root, run_id, "plan", owner_session_confirmed=True
        )
        self.assertEqual(state["current_stage"], "outline")

    def test_approved_fact_pack_digest_is_verified_on_later_stages(self) -> None:
        fact_pack = self.root / ".company/projects/note販売AIチーム/data/tamper-fact-pack.md"
        fact_pack.write_text(
            "owner_approved: true\n"
            "approved_at: 2026-07-19T10:00:00+09:00\n\n"
            "公開可能な本人体験\n",
            encoding="utf-8",
        )
        state, _ = note_team.create_run(
            self.root,
            "you-ai-dx",
            "ai-utilization",
            "tampered-fact-pack",
            product_profile="paid-longform",
            fact_pack=fact_pack,
        )
        run_id = state["run_id"]
        state = note_team.approve_fact_pack(
            self.root, run_id, owner_session_confirmed=True
        )
        saved = (
            self.root
            / note_team.RUNS_REL
            / run_id
            / state["inputs"]["fact_pack"]["artifact"]
        )
        saved.chmod(0o600)
        saved.write_text("改ざん済み\n", encoding="utf-8")
        with self.assertRaises(note_team.NoteTeamError):
            note_team.verify_fact_pack(self.root, note_team.load_state(self.root, run_id))

    def test_na_metrics_valid_month_and_output_scope(self) -> None:
        data = self.root / ".company/projects/note販売AIチーム/data"
        (data / "note_metrics.csv").write_text(
            "date,run_id,account_id,title,pv,likes,sales_count,revenue_yen,price_yen\n"
            "2026-07-01,r1,you-ai-dx,A,100,N/A,N/A,N/A,500\n",
            encoding="utf-8",
        )
        (data / "x_metrics.csv").write_text(
            "date,run_id,variant,impressions,engagements,link_clicks\n"
            "2026-07-01,r1,a,1000,N/A,N/A\n",
            encoding="utf-8",
        )
        result, markdown = note_team.analyze_metrics(self.root, "2026-07")
        self.assertIsNone(result["note"]["sales_count"])
        self.assertEqual(result["note"]["paid_conversion_rate"], "N/A")
        self.assertEqual(result["comparison"]["unknown"]["articles"], 1)
        self.assertIn("売上不明", markdown)
        self.assertNotIn(": None", markdown)
        self.assertEqual(result["provenance"]["note_csv"]["filtered_rows"], 1)
        self.assertEqual(len(result["provenance"]["note_csv"]["sha256"]), 64)
        with self.assertRaises(note_team.NoteTeamError):
            note_team.analyze_metrics(self.root, "2026-13")
        with self.assertRaises(note_team.NoteTeamError):
            note_team.resolve_report_output(self.root, Path("AGENTS.md"), "2026-07")

    def test_report_output_rejects_symlink_escape_and_no_force_overwrite(self) -> None:
        project = self.root / ".company/projects/note販売AIチーム"
        outside = self.root / "outside-reports"
        outside.mkdir()
        self.symlink_or_skip(
            project / "reports", outside, target_is_directory=True
        )
        with self.assertRaises(note_team.NoteTeamError):
            note_team.resolve_report_output(self.root, None, "2026-07")
        self.assertEqual(list(outside.iterdir()), [])

        (project / "reports").unlink()
        output = note_team.resolve_report_output(self.root, None, "2026-07")
        note_team.write_report(output, b"first\n", force=False)
        with self.assertRaises(note_team.NoteTeamError):
            note_team.write_report(output, b"second\n", force=False)
        self.assertEqual(output.read_bytes(), b"first\n")
        note_team.write_report(output, b"forced\n", force=True)
        self.assertEqual(output.read_bytes(), b"forced\n")
        with self.assertRaises(note_team.NoteTeamError):
            note_team.resolve_report_output(self.root, None, None)

    def test_metric_dates_and_duplicate_keys_are_rejected(self) -> None:
        data = self.root / ".company/projects/note販売AIチーム/data"
        header = "date,run_id,account_id,title,pv,likes,sales_count,revenue_yen,price_yen\n"
        (data / "note_metrics.csv").write_text(
            header + "2026-07-bad,r1,you-ai-dx,A,10,1,0,0,0\n",
            encoding="utf-8",
        )
        with self.assertRaises(note_team.NoteTeamError):
            note_team.analyze_metrics(self.root, "2026-07")

        (data / "note_metrics.csv").write_text(
            header + " 2026-07-01 ,r1,you-ai-dx,A,10,1,0,0,0\n",
            encoding="utf-8",
        )
        with self.assertRaises(note_team.NoteTeamError):
            note_team.analyze_metrics(self.root, "2026-07")
        (data / "note_metrics.csv").write_text(
            header + "2026-07-01, r1 ,you-ai-dx,A,10,1,0,0,0\n",
            encoding="utf-8",
        )
        with self.assertRaises(note_team.NoteTeamError):
            note_team.analyze_metrics(self.root, "2026-07")
        duplicate = "2026-07-01,r1,you-ai-dx,A,10,1,0,0,0\n"
        (data / "note_metrics.csv").write_text(
            header + duplicate + duplicate,
            encoding="utf-8",
        )
        with self.assertRaises(note_team.NoteTeamError):
            note_team.analyze_metrics(self.root, "2026-07")

    def test_unknown_price_makes_paid_conversion_na(self) -> None:
        data = self.root / ".company/projects/note販売AIチーム/data"
        (data / "note_metrics.csv").write_text(
            "date,run_id,account_id,title,pv,likes,sales_count,revenue_yen,price_yen\n"
            "2026-07-01,r1,you-ai-dx,Paid,100,5,2,1000,500\n"
            "2026-07-02,r2,you-ai-dx,Unknown,50,2,0,0,N/A\n",
            encoding="utf-8",
        )
        result, _ = note_team.analyze_metrics(self.root, "2026-07")
        self.assertEqual(result["note"]["paid_pv"], 100)
        self.assertEqual(result["note"]["unknown_price_rows"], 1)
        self.assertEqual(result["note"]["paid_conversion_rate"], "N/A")
        self.assertEqual(result["comparison"]["unknown"]["articles"], 1)

    def test_concurrent_owner_decisions_do_not_overwrite_each_other(self) -> None:
        state, _ = self.create("race")
        run_id = state["run_id"]
        self.plan_artifact(run_id)
        self.submit(run_id, "plan", "plan.md")
        note_team.select_plan(
            self.root, run_id, "plan-01", owner_session_confirmed=True
        )
        barrier = threading.Barrier(3)
        successes: list[str] = []
        failures: list[Exception] = []

        def decide(action: str) -> None:
            barrier.wait()
            try:
                if action == "approve":
                    note_team.approve(
                        self.root,
                        run_id,
                        "plan",
                        owner_session_confirmed=True,
                    )
                else:
                    note_team.reject(
                        self.root,
                        run_id,
                        "plan",
                        "停止",
                        owner_session_confirmed=True,
                    )
                successes.append(action)
            except note_team.NoteTeamError as exc:
                failures.append(exc)

        threads = [
            threading.Thread(target=decide, args=("approve",)),
            threading.Thread(target=decide, args=("reject",)),
        ]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(timeout=3)
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(failures), 1)
        final = note_team.load_state(self.root, run_id)
        self.assertIn(final["status"], {"active", "rejected"})

    def test_quality_failures_stop_at_five_and_fatal_violation_rejects(self) -> None:
        state, _ = self.create("five-failures")
        run_id = state["run_id"]
        self.plan_artifact(run_id)
        for attempt in range(5):
            qa = self.qa_artifact(run_id, "plan", "plan.md", score=84)
            with self.assertRaises(note_team.NoteTeamError):
                note_team.submit_artifact(
                    self.root, run_id, "plan", "plan.md", "agent", qa_artifact=qa
                )
        stopped = note_team.load_state(self.root, run_id)
        self.assertEqual(stopped["stages"]["plan"]["attempts"], 5)
        self.assertEqual(stopped["stages"]["plan"]["status"], "owner_escalation")
        self.assertEqual(len(stopped["stages"]["plan"]["quality_failures"]), 5)
        for failure in stopped["stages"]["plan"]["quality_failures"]:
            self.assertTrue(
                (self.root / note_team.RUNS_REL / run_id / failure["artifact"]).is_file()
            )
            self.assertTrue(
                (self.root / note_team.RUNS_REL / run_id / failure["qa_artifact"]).is_file()
            )
        with self.assertRaises(note_team.NoteTeamError):
            note_team.extend_quality_loop(self.root, run_id, "plan")
        extended = note_team.extend_quality_loop(
            self.root, run_id, "plan", owner_session_confirmed=True
        )
        self.assertEqual(extended["stages"]["plan"]["attempts"], 0)
        self.assertEqual(extended["stages"]["plan"]["status"], "revision_requested")

        fatal, _ = self.create("fatal")
        fatal_id = fatal["run_id"]
        self.plan_artifact(fatal_id)
        fatal_qa = self.qa_artifact(
            fatal_id,
            "plan",
            "plan.md",
            score=90,
            fatal_violations=["架空実績"],
        )
        with self.assertRaises(note_team.FatalQualityError):
            note_team.submit_artifact(
                self.root, fatal_id, "plan", "plan.md", "agent", qa_artifact=fatal_qa
            )
        self.assertEqual(note_team.load_state(self.root, fatal_id)["status"], "rejected")
        fatal_state = note_team.load_state(self.root, fatal_id)
        self.assertEqual(
            fatal_state["stages"]["plan"]["quality_failures"][0]["error_type"],
            "FatalQualityError",
        )

    def test_snapshot_name_is_bounded_for_long_source_filename(self) -> None:
        state, _ = self.create("long-source-name")
        run_id = state["run_id"]
        source_name = "a" * 230 + ".md"
        self.artifact(run_id, source_name, "bounded snapshot")
        directory = self.root / note_team.RUNS_REL / run_id
        snapshot, digest = note_team.snapshot_text(
            directory, source_name, "plan/final", 1
        )
        snapshot_path = directory / snapshot
        self.assertTrue(snapshot_path.is_file())
        self.assertLessEqual(len(snapshot_path.name.encode("utf-8")), 120)
        self.assertEqual(note_team.sha256_file(snapshot_path), digest)

    def test_state_run_id_binding_and_draft_unit_bypass_are_rejected(self) -> None:
        first, _ = self.create("state-a")
        second, _ = self.create("state-b")
        gibberish = json.loads(json.dumps(first))
        gibberish["stages"]["plan"]["status"] = "gibberish"
        with self.assertRaises(note_team.NoteTeamError):
            note_team.validate_state(gibberish)
        active_approved = json.loads(json.dumps(first))
        active_approved["stages"]["plan"]["status"] = "approved"
        with self.assertRaises(note_team.NoteTeamError):
            note_team.validate_state(active_approved)
        false_completed = json.loads(json.dumps(first))
        false_completed["status"] = "completed"
        for stage in note_team.STAGES:
            false_completed["stages"][stage]["status"] = "approved"
        with self.assertRaises(note_team.NoteTeamError):
            note_team.validate_state(false_completed)

        empty_unit_cycle = json.loads(json.dumps(first))
        empty_unit_cycle["current_stage"] = "draft"
        empty_unit_cycle["stages"]["plan"]["status"] = "approved"
        empty_unit_cycle["stages"]["outline"]["status"] = "approved"
        empty_unit_cycle["stages"]["draft"]["status"] = "unit_cycle"
        empty_unit_cycle["stages"]["draft"]["units"] = {}
        with self.assertRaises(note_team.NoteTeamError):
            note_team.validate_state(empty_unit_cycle)

        missing_unit_evidence = json.loads(json.dumps(empty_unit_cycle))
        missing_unit_evidence["stages"]["draft"]["units"] = {
            "chapter-01": {"status": "review", "attempts": 1, "artifact": None}
        }
        with self.assertRaises(note_team.NoteTeamError):
            note_team.validate_state(missing_unit_evidence)

        missing_authorization = json.loads(json.dumps(first))
        missing_authorization["current_stage"] = "note_draft"
        for earlier in ("plan", "outline", "draft", "promotion"):
            missing_authorization["stages"][earlier]["status"] = "approved"
        missing_authorization["stages"]["note_draft"].update(
            {"status": "authorized", "authorization_id": "missing"}
        )
        with self.assertRaises(note_team.NoteTeamError):
            note_team.validate_state(missing_authorization)

        corrupted = dict(first)
        corrupted["run_id"] = second["run_id"]
        note_team.atomic_write_json(note_team.state_path(self.root, first["run_id"]), corrupted)
        with self.assertRaises(note_team.NoteTeamError):
            note_team.load_state(self.root, first["run_id"])

        malformed = dict(second)
        malformed["stages"] = []
        note_team.atomic_write_json(
            note_team.state_path(self.root, second["run_id"]), malformed
        )
        with self.assertRaises(note_team.NoteTeamError):
            note_team.load_state(self.root, second["run_id"])

        state, _ = self.create("draft-bypass")
        run_id = state["run_id"]
        state["current_stage"] = "draft"
        state["stages"]["plan"]["status"] = "approved"
        state["stages"]["outline"]["status"] = "approved"
        state["stages"]["draft"]["status"] = "awaiting_output"
        note_team.atomic_write_json(note_team.state_path(self.root, run_id), state)
        self.artifact(run_id, "manuscript.md")
        qa = self.qa_artifact(run_id, "draft", "manuscript.md")
        with self.assertRaises(note_team.NoteTeamError):
            note_team.submit_artifact(
                self.root,
                run_id,
                "draft",
                "manuscript.md",
                "note-writer",
                qa_artifact=qa,
            )

    def test_empty_metrics_and_multi_day_article_classification(self) -> None:
        empty, markdown = note_team.analyze_metrics(self.root, "2026-07")
        self.assertIsNone(empty["note"]["pv"])
        self.assertIsNone(empty["x"]["impressions"])
        self.assertIn("PV: N/A", markdown)
        data = self.root / ".company/projects/note販売AIチーム/data"
        (data / "note_metrics.csv").write_text(
            "date,run_id,account_id,title,pv,likes,sales_count,revenue_yen,price_yen\n"
            "2026-07-01,r1,you-ai-dx,A,10,1,0,0,500\n"
            "2026-07-02,r1,you-ai-dx,A,20,2,1,500,500\n",
            encoding="utf-8",
        )
        result, _ = note_team.analyze_metrics(self.root, "2026-07")
        self.assertEqual(result["comparison"]["sold"]["articles"], 1)
        self.assertEqual(result["comparison"]["unsold"]["articles"], 0)
        self.assertEqual(result["comparison"]["sold"]["avg_pv"], 30)

    def test_symlink_write_destinations_and_reserved_run_ids_are_rejected(self) -> None:
        state, _ = self.create("symlink")
        run_id = state["run_id"]
        directory = self.root / note_team.RUNS_REL / run_id
        outside = self.root / "outside-destination"
        outside.mkdir()
        self.symlink_or_skip(
            directory / ".snapshots", outside, target_is_directory=True
        )
        self.plan_artifact(run_id)
        qa = self.qa_artifact(run_id, "plan", "plan.md")
        with self.assertRaises(note_team.NoteTeamError):
            note_team.submit_artifact(
                self.root, run_id, "plan", "plan.md", "agent", qa_artifact=qa
            )
        self.assertEqual(list(outside.iterdir()), [])

        long_state, _ = self.create("a" * 80)
        self.assertLessEqual(len(long_state["run_id"]), 96)
        with self.assertRaises(note_team.NoteTeamError):
            note_team.create_run(
                self.root,
                "you-ai-dx",
                "ai-utilization",
                "reserved",
                run_id_value="con",
            )

        reserved, _ = self.create("reserved-unit")
        reserved_id = reserved["run_id"]
        reserved["current_stage"] = "draft"
        reserved["stages"]["plan"]["status"] = "approved"
        reserved["stages"]["outline"]["status"] = "approved"
        reserved["stages"]["draft"]["status"] = "awaiting_output"
        note_team.atomic_write_json(note_team.state_path(self.root, reserved_id), reserved)
        with self.assertRaises(note_team.NoteTeamError):
            note_team.set_units(
                self.root,
                reserved_id,
                "draft",
                ["con", "chapter-02", "chapter-03", "chapter-04"],
            )

    def test_lock_and_audit_symlinks_cannot_modify_external_files(self) -> None:
        locked, _ = self.create("linked-lock")
        locked_id = locked["run_id"]
        locked_dir = self.root / note_team.RUNS_REL / locked_id
        outside_lock = self.root / "outside-lock.txt"
        outside_lock.write_text("do-not-truncate\n", encoding="utf-8")
        self.symlink_or_skip(locked_dir / ".state.lock", outside_lock)
        self.plan_artifact(locked_id)
        qa = self.qa_artifact(locked_id, "plan", "plan.md")
        with self.assertRaises(note_team.NoteTeamError):
            note_team.submit_artifact(
                self.root,
                locked_id,
                "plan",
                "plan.md",
                "agent",
                qa_artifact=qa,
            )
        self.assertEqual(outside_lock.read_text(encoding="utf-8"), "do-not-truncate\n")

        audited, _ = self.create("linked-audit")
        audited_id = audited["run_id"]
        audited_dir = self.root / note_team.RUNS_REL / audited_id
        (audited_dir / "audit.jsonl").unlink()
        outside_audit = self.root / "outside-audit.txt"
        outside_audit.write_text("do-not-append\n", encoding="utf-8")
        self.symlink_or_skip(audited_dir / "audit.jsonl", outside_audit)
        self.plan_artifact(audited_id)
        state = self.submit(audited_id, "plan", "plan.md")
        self.assertEqual(state["stages"]["plan"]["status"], "review")
        self.assertEqual(outside_audit.read_text(encoding="utf-8"), "do-not-append\n")

    def test_unknown_external_outcome_blocks_rewrite_until_reconciled(self) -> None:
        claimed = self.prepare_claimed_note_draft("unknown-outcome-found")
        run_id = claimed["run_id"]
        claim_id = claimed["stages"]["note_draft"]["claim_id"]
        state = note_team.record_external_failure(
            self.root,
            run_id,
            "note_draft",
            "browserの応答が結果記録前に途絶",
        )
        self.assertEqual(
            state["stages"]["note_draft"]["status"], "reconciliation_required"
        )
        self.assertEqual(state["stages"]["note_draft"]["claim_id"], claim_id)
        with self.assertRaises(note_team.NoteTeamError):
            note_team.claim_external(self.root, run_id, "note_draft")
        with self.assertRaises(note_team.NoteTeamError):
            note_team.submit_preflight(self.root, run_id, "note-preflight.json")

        self.artifact(
            run_id,
            "note-draft-found.json",
            json.dumps(self.note_draft_outcome(state), ensure_ascii=False),
        )
        state = note_team.submit_artifact(
            self.root,
            run_id,
            "note_draft",
            "note-draft-found.json",
            "note-article-publisher",
        )
        self.assertEqual(state["stages"]["note_draft"]["status"], "review")

        missing = self.prepare_claimed_note_draft("unknown-outcome-missing")
        missing_id = missing["run_id"]
        note_team.record_external_failure(
            self.root,
            missing_id,
            "note_draft",
            "browserの応答が結果記録前に途絶",
        )
        with self.assertRaises(note_team.NoteTeamError):
            note_team.confirm_no_external_draft(
                self.root,
                missing_id,
                "note_draft",
                "下書き一覧を確認",
            )
        state = note_team.confirm_no_external_draft(
            self.root,
            missing_id,
            "note_draft",
            "you_ai_dx の下書き一覧に対象タイトルなし",
            owner_session_confirmed=True,
        )
        self.assertEqual(
            state["stages"]["note_draft"]["status"], "authorization_required"
        )
        self.assertIsNone(state["stages"]["note_draft"]["claim_id"])

        late = self.prepare_claimed_note_draft("late-reconciliation")
        late_id = late["run_id"]
        late = note_team.record_external_failure(
            self.root,
            late_id,
            "note_draft",
            "保存後に結果記録途絶",
        )
        authorization = next(
            item
            for item in late["external_authorizations"]
            if item.get("claim_id") == late["stages"]["note_draft"]["claim_id"]
        )
        claimed_at = note_team.parse_checked_at(authorization["claimed_at"])
        later = claimed_at + timedelta(minutes=11)
        outcome = self.note_draft_outcome(late)
        outcome["draft_saved_at"] = authorization["claimed_at"]
        outcome["checked_at"] = later.isoformat(timespec="seconds")
        self.artifact(
            late_id,
            "late-reconciled-result.json",
            json.dumps(outcome, ensure_ascii=False),
        )
        with mock.patch.object(note_team, "now_jst", return_value=later):
            state = note_team.submit_artifact(
                self.root,
                late_id,
                "note_draft",
                "late-reconciled-result.json",
                "note-article-publisher",
            )
        self.assertEqual(state["stages"]["note_draft"]["status"], "review")

    def test_external_result_binds_new_draft_and_claim_deadline(self) -> None:
        claimed = self.prepare_claimed_note_draft("wrong-draft-id")
        run_id = claimed["run_id"]
        wrong = self.note_draft_outcome(claimed)
        wrong["editor_draft_id"] = "n-otherdraft"
        self.artifact(
            run_id,
            "wrong-draft.json",
            json.dumps(wrong, ensure_ascii=False),
        )
        with self.assertRaises(note_team.NoteTeamError):
            note_team.submit_artifact(
                self.root,
                run_id,
                "note_draft",
                "wrong-draft.json",
                "note-article-publisher",
            )
        self.assertEqual(
            note_team.load_state(self.root, run_id)["stages"]["note_draft"]["status"],
            "reconciliation_required",
        )

        expired = self.prepare_claimed_note_draft("expired-claim")
        expired_id = expired["run_id"]
        past = "2026-07-18T10:00:00+09:00"
        expired["stages"]["note_draft"]["claim_expires_at"] = past
        for authorization in expired["external_authorizations"]:
            if authorization.get("claim_id") == expired["stages"]["note_draft"]["claim_id"]:
                authorization["claim_expires_at"] = past
        note_team.atomic_write_json(note_team.state_path(self.root, expired_id), expired)
        self.artifact(
            expired_id,
            "expired-result.json",
            json.dumps(self.note_draft_outcome(expired), ensure_ascii=False),
        )
        with self.assertRaises(note_team.NoteTeamError):
            note_team.submit_artifact(
                self.root,
                expired_id,
                "note_draft",
                "expired-result.json",
                "note-article-publisher",
            )
        self.assertEqual(
            note_team.load_state(self.root, expired_id)["stages"]["note_draft"]["status"],
            "reconciliation_required",
        )

        tampered = self.prepare_claimed_note_draft("tampered-preflight-after-claim")
        tampered_id = tampered["run_id"]
        tampered_stage = tampered["stages"]["note_draft"]
        preflight_path = (
            self.root
            / note_team.RUNS_REL
            / tampered_id
            / tampered_stage["preflight_artifact"]
        )
        preflight_path.chmod(0o600)
        preflight_path.write_text(
            json.dumps(
                {
                    "account_id": "you-ai-dx",
                    "expected_note_id": "you_ai_dx",
                    "observed_note_id": "you_ai_dx",
                    "editor_ready": True,
                    "operation": "create_new_draft",
                    "editor_url": "https://note.com/notes/new",
                    "initial_content_empty": True,
                    "checked_at": note_team.iso_now(),
                    "tampered_marker": "changed-after-claim",
                }
            ),
            encoding="utf-8",
        )
        swapped = self.note_draft_outcome(tampered)
        swapped["editor_draft_id"] = "n-swappeddraft"
        swapped["draft_url"] = "https://editor.note.com/notes/n-swappeddraft/edit/"
        self.artifact(
            tampered_id,
            "swapped-result.json",
            json.dumps(swapped, ensure_ascii=False),
        )
        with self.assertRaises(note_team.NoteTeamError):
            note_team.submit_artifact(
                self.root,
                tampered_id,
                "note_draft",
                "swapped-result.json",
                "note-article-publisher",
            )

        manuscript = self.prepare_claimed_note_draft("tampered-manuscript-after-claim")
        manuscript_id = manuscript["run_id"]
        manuscript_path = (
            self.root
            / note_team.RUNS_REL
            / manuscript_id
            / manuscript["stages"]["draft"]["artifact"]
        )
        manuscript_path.chmod(0o600)
        manuscript_path.write_text("承認後の改ざん", encoding="utf-8")
        self.artifact(
            manuscript_id,
            "tampered-manuscript-result.json",
            json.dumps(self.note_draft_outcome(manuscript), ensure_ascii=False),
        )
        with self.assertRaises(note_team.NoteTeamError):
            note_team.submit_artifact(
                self.root,
                manuscript_id,
                "note_draft",
                "tampered-manuscript-result.json",
                "note-article-publisher",
            )

    def test_analysis_artifact_must_bind_current_csv_hashes(self) -> None:
        state, _ = self.create("analysis-binding")
        run_id = state["run_id"]
        state["current_stage"] = "analysis"
        for stage in note_team.STAGES[:-1]:
            state["stages"][stage]["status"] = "approved"
        state["stages"]["analysis"]["status"] = "awaiting_output"
        note_team.atomic_write_json(note_team.state_path(self.root, run_id), state)
        self.artifact(
            run_id,
            "analysis.md",
            "metrics_month: 2026-07\nnote_csv_sha256: " + "0" * 64 +
            "\nx_csv_sha256: " + "0" * 64 +
            "\nmetrics_snapshot_sha256: " + "0" * 64 + "\n",
        )
        qa = self.qa_artifact(run_id, "analysis", "analysis.md")
        with self.assertRaises(note_team.NoteTeamError):
            note_team.submit_artifact(
                self.root,
                run_id,
                "analysis",
                "analysis.md",
                "note-analyst",
                qa_artifact=qa,
            )

        result, _ = note_team.analyze_metrics(self.root, "2026-07")
        provenance = result["provenance"]
        self.artifact(
            run_id,
            "analysis.md",
            "metrics_month: 2026-07\n"
            f"note_csv_sha256: {provenance['note_csv']['sha256']}\n"
            f"x_csv_sha256: {provenance['x_csv']['sha256']}\n"
            f"metrics_snapshot_sha256: {note_team.metrics_snapshot_sha256(result)}\n\n"
            "# 分析\nPVは999でした。\n",
        )
        qa = self.qa_artifact(run_id, "analysis", "analysis.md")
        with self.assertRaises(note_team.NoteTeamError):
            note_team.submit_artifact(
                self.root,
                run_id,
                "analysis",
                "analysis.md",
                "note-analyst",
                qa_artifact=qa,
            )

    def test_profile_chapter_and_manuscript_character_boundaries(self) -> None:
        free, _ = self.create("free-chapters")
        free_id = free["run_id"]
        free["current_stage"] = "draft"
        free["stages"]["plan"]["status"] = "approved"
        free["stages"]["outline"]["status"] = "approved"
        free["stages"]["draft"]["status"] = "awaiting_output"
        note_team.atomic_write_json(note_team.state_path(self.root, free_id), free)
        with self.assertRaises(note_team.NoteTeamError):
            note_team.set_units(
                self.root, free_id, "draft", ["chapter-01", "chapter-02", "chapter-03"]
            )
        note_team.set_units(
            self.root,
            free_id,
            "draft",
            ["chapter-01", "chapter-02", "chapter-03", "chapter-04"],
        )

        fact_pack = self.root / ".company/projects/note販売AIチーム/data/paid-fact-pack.md"
        fact_pack.write_text(
            "owner_approved: true\napproved_at: 2026-07-19T10:00:00+09:00\n公開可能な本人事実\n",
            encoding="utf-8",
        )
        paid, _ = note_team.create_run(
            self.root,
            "you-ai-dx",
            "ai-utilization",
            "paid-boundary",
            product_profile="paid-longform",
            fact_pack=fact_pack,
        )
        paid_id = paid["run_id"]
        note_team.approve_fact_pack(
            self.root, paid_id, owner_session_confirmed=True
        )
        paid = note_team.load_state(self.root, paid_id)
        paid["current_stage"] = "draft"
        paid["stages"]["plan"]["status"] = "approved"
        paid["stages"]["outline"]["status"] = "approved"
        paid["stages"]["draft"]["status"] = "awaiting_output"
        note_team.atomic_write_json(note_team.state_path(self.root, paid_id), paid)
        with self.assertRaises(note_team.NoteTeamError):
            note_team.set_units(
                self.root,
                paid_id,
                "draft",
                [f"chapter-{number:02d}" for number in range(1, 8)],
            )
        with self.assertRaises(note_team.NoteTeamError):
            note_team.set_units(
                self.root,
                paid_id,
                "draft",
                [f"chapter-{number:02d}" for number in range(1, 12)],
            )
        state = note_team.set_units(
            self.root,
            paid_id,
            "draft",
            [f"chapter-{number:02d}" for number in range(1, 9)],
        )
        for unit_data in state["stages"]["draft"]["units"].values():
            unit_data["status"] = "approved"
        state["stages"]["draft"]["status"] = "awaiting_final_output"
        note_team.atomic_write_json(note_team.state_path(self.root, paid_id), state)

        self.artifact(paid_id, "manuscript.md", "あ" * 14999)
        qa = self.qa_artifact(paid_id, "draft", "manuscript.md")
        with self.assertRaises(note_team.NoteTeamError):
            note_team.submit_artifact(
                self.root,
                paid_id,
                "draft",
                "manuscript.md",
                "note-writer",
                qa_artifact=qa,
            )
        self.artifact(paid_id, "manuscript.md", "あ" * 15000)
        state = self.submit(paid_id, "draft", "manuscript.md", "note-writer")
        self.assertEqual(state["stages"]["draft"]["manuscript_characters"], 15000)
        note_team.request_revision(
            self.root,
            paid_id,
            "draft",
            "上限境界を確認",
            owner_session_confirmed=True,
        )
        self.artifact(paid_id, "manuscript.md", "あ" * 20001)
        qa = self.qa_artifact(paid_id, "draft", "manuscript.md")
        with self.assertRaises(note_team.NoteTeamError):
            note_team.submit_artifact(
                self.root,
                paid_id,
                "draft",
                "manuscript.md",
                "note-writer",
                qa_artifact=qa,
            )
        self.artifact(paid_id, "manuscript.md", "あ" * 20000)
        state = self.submit(paid_id, "draft", "manuscript.md", "note-writer")
        self.assertEqual(state["stages"]["draft"]["manuscript_characters"], 20000)

        paid_ten, _ = note_team.create_run(
            self.root,
            "you-ai-dx",
            "ai-utilization",
            "paid-ten-chapters",
            product_profile="paid-longform",
            fact_pack=fact_pack,
        )
        paid_ten_id = paid_ten["run_id"]
        note_team.approve_fact_pack(
            self.root, paid_ten_id, owner_session_confirmed=True
        )
        paid_ten = note_team.load_state(self.root, paid_ten_id)
        paid_ten["current_stage"] = "draft"
        paid_ten["stages"]["plan"]["status"] = "approved"
        paid_ten["stages"]["outline"]["status"] = "approved"
        paid_ten["stages"]["draft"]["status"] = "awaiting_output"
        note_team.atomic_write_json(note_team.state_path(self.root, paid_ten_id), paid_ten)
        state = note_team.set_units(
            self.root,
            paid_ten_id,
            "draft",
            [f"chapter-{number:02d}" for number in range(1, 11)],
        )
        self.assertEqual(len(state["stages"]["draft"]["units"]), 10)

    def test_local_approval_ui_requires_token_and_records_approval(self) -> None:
        state, _ = self.create("ui")
        run_id = state["run_id"]
        self.plan_artifact(run_id)
        self.submit(run_id, "plan", "plan.md", "agent")
        with self.assertRaises(note_team.NoteTeamError):
            note_team.approve(self.root, run_id, "plan")
        token = "test-token"
        server = ThreadingHTTPServer(("127.0.0.1", 0), note_team.make_handler(self.root, token))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        cookie_jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(cookie_jar),
            urllib.request.HTTPRedirectHandler(),
        )
        try:
            with self.assertRaises(urllib.error.HTTPError) as denied:
                urllib.request.urlopen(base + "/", timeout=3)
            self.assertEqual(denied.exception.code, 403)
            with opener.open(base + "/?token=" + token, timeout=3) as response:
                self.assertEqual(response.status, 200)
                page = response.read().decode("utf-8")
                self.assertIn("承認画面", page)
                csrf = re.search(r'name="csrf" value="([^"]+)"', page)
                self.assertIsNotNone(csrf)
            select_body = urllib.parse.urlencode(
                {
                    "csrf": csrf.group(1),
                    "run_id": run_id,
                    "stage": "plan",
                    "action": "select_plan",
                    "plan_id": "plan-01",
                }
            ).encode("utf-8")
            with opener.open(
                urllib.request.Request(base + "/action", data=select_body, method="POST"),
                timeout=3,
            ) as response:
                self.assertEqual(response.status, 200)
            body = urllib.parse.urlencode(
                {
                    "csrf": csrf.group(1),
                    "run_id": run_id,
                    "stage": "plan",
                    "action": "approve",
                }
            ).encode("utf-8")
            request = urllib.request.Request(base + "/action", data=body, method="POST")
            with opener.open(request, timeout=3) as response:
                self.assertEqual(response.status, 200)
            updated = note_team.load_state(self.root, run_id)
            self.assertEqual(updated["current_stage"], "outline")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_style_candidate_pack_rejects_counts_duplicates_and_fake_manifest_ids(self) -> None:
        original = json.loads(self.style_candidate_path.read_text(encoding="utf-8"))

        too_few = json.loads(json.dumps(original))
        too_few["x_candidates"].pop()
        self.rewrite_style_candidate_pack(too_few)
        with self.assertRaisesRegex(note_team.NoteTeamError, "正確に20件"):
            note_team.load_style_candidate_pack(self.root)

        duplicate = json.loads(json.dumps(original))
        duplicate["x_candidates"][0]["candidate_id"] = duplicate["note_candidates"][0][
            "candidate_id"
        ]
        self.rewrite_style_candidate_pack(duplicate)
        with self.assertRaisesRegex(note_team.NoteTeamError, "candidate_idが重複"):
            note_team.load_style_candidate_pack(self.root)

        fake_manifest = json.loads(json.dumps(original))
        manifest = note_team.style_selection_manifest(
            fake_manifest["note_candidates"], fake_manifest["x_candidates"]
        )
        manifest["x"][0]["candidate_id"] = "fake-x-id"
        fake_manifest["selection_manifest"] = manifest
        fake_manifest["selection_sha256"] = note_team.sha256_bytes(
            note_team.canonical_json_bytes(manifest)
        )
        self.style_candidate_path.write_text(
            json.dumps(fake_manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(note_team.NoteTeamError, "selection_manifest"):
            note_team.load_style_candidate_pack(self.root)

    def test_style_approval_requires_owner_stale_guard_and_is_idempotent(self) -> None:
        self.reset_style_registry()
        pack_sha = note_team.sha256_file(self.style_candidate_path)
        initial_registry_sha = note_team.sha256_file(self.style_registry_path)
        with self.assertRaisesRegex(note_team.NoteTeamError, "ローカル承認画面"):
            note_team.approve_style_corpus(
                self.root, pack_sha, initial_registry_sha
            )
        with self.assertRaisesRegex(note_team.NoteTeamError, "画面表示後に変更"):
            note_team.approve_style_corpus(
                self.root,
                pack_sha,
                "0" * 64,
                owner_session_confirmed=True,
            )
        first = note_team.approve_style_corpus(
            self.root,
            pack_sha,
            initial_registry_sha,
            owner_session_confirmed=True,
        )
        self.assertEqual(first["version"], 2)
        self.assertEqual(first["approved_by"], "owner")
        self.assertIsNotNone(note_team.parse_checked_at(first["approved_at"]))
        self.assertEqual(
            first["selection_sha256"],
            note_team.sha256_bytes(
                note_team.canonical_json_bytes(first["selection_manifest"])
            ),
        )

        # A browser double-submit with the now-stale initial registry SHA is a
        # safe no-op when the fixed selection is already approved.
        second = note_team.approve_style_corpus(
            self.root,
            pack_sha,
            initial_registry_sha,
            owner_session_confirmed=True,
        )
        self.assertEqual(second, first)

        changed = json.loads(self.style_candidate_path.read_text(encoding="utf-8"))
        changed["note_candidates"][0]["title"] = "別の候補タイトル"
        self.rewrite_style_candidate_pack(changed)
        with self.assertRaisesRegex(note_team.NoteTeamError, "別内容で上書き"):
            note_team.approve_style_corpus(
                self.root,
                note_team.sha256_file(self.style_candidate_path),
                note_team.sha256_file(self.style_registry_path),
                owner_session_confirmed=True,
            )

    def test_concurrent_style_approval_is_serialized_and_idempotent(self) -> None:
        self.reset_style_registry()
        pack_sha = note_team.sha256_file(self.style_candidate_path)
        registry_sha = note_team.sha256_file(self.style_registry_path)
        barrier = threading.Barrier(3)
        results: list[dict] = []
        failures: list[Exception] = []

        def approve_once() -> None:
            barrier.wait()
            try:
                results.append(
                    note_team.approve_style_corpus(
                        self.root,
                        pack_sha,
                        registry_sha,
                        owner_session_confirmed=True,
                    )
                )
            except Exception as exc:  # pragma: no cover - asserted below
                failures.append(exc)

        threads = [threading.Thread(target=approve_once) for _ in range(2)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(timeout=3)
        self.assertEqual(failures, [])
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0], results[1])

    def test_style_paths_symlinks_and_registry_fake_ids_are_rejected(self) -> None:
        original = json.loads(self.style_candidate_path.read_text(encoding="utf-8"))
        traversal = json.loads(json.dumps(original))
        traversal["note_candidates"][0]["source_path"] = "../outside.md"
        self.rewrite_style_candidate_pack(traversal)
        with self.assertRaisesRegex(note_team.NoteTeamError, "絶対パスや .."):
            note_team.load_style_candidate_pack(self.root)

        self.rewrite_style_candidate_pack(original)
        target = self.root / original["note_candidates"][0]["source_path"]
        linked = target.parent / "linked-style-note.md"
        self.symlink_or_skip(linked, target)
        linked_pack = json.loads(json.dumps(original))
        linked_pack["note_candidates"][0]["source_path"] = linked.relative_to(
            self.root
        ).as_posix()
        self.rewrite_style_candidate_pack(linked_pack)
        with self.assertRaisesRegex(note_team.NoteTeamError, "シンボリックリンク"):
            note_team.load_style_candidate_pack(self.root)

        self.rewrite_style_candidate_pack(original)
        registry = json.loads(self.style_registry_path.read_text(encoding="utf-8"))
        registry["x_sources"][0]["candidate_id"] = "fake-x-source"
        self.style_registry_path.write_text(
            json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(note_team.NoteTeamError, "x_sources"):
            note_team.verify_style_corpus(self.root)

    def test_create_and_draft_submit_fail_closed_on_style_corpus_state(self) -> None:
        self.reset_style_registry()
        with self.assertRaisesRegex(note_team.NoteTeamError, "approved"):
            self.create("unapproved-style")
        note_team.approve_style_corpus(
            self.root,
            note_team.sha256_file(self.style_candidate_path),
            note_team.sha256_file(self.style_registry_path),
            owner_session_confirmed=True,
        )
        state, existed = self.create("approved-style")
        self.assertFalse(existed)
        run_id = state["run_id"]
        state["current_stage"] = "draft"
        state["stages"]["plan"]["status"] = "approved"
        state["stages"]["outline"]["status"] = "approved"
        state["stages"]["draft"]["status"] = "awaiting_output"
        note_team.atomic_write_json(note_team.state_path(self.root, run_id), state)
        note_team.set_units(
            self.root,
            run_id,
            "draft",
            ["chapter-01", "chapter-02", "chapter-03", "chapter-04"],
        )
        chapter = self.artifact(run_id, "chapters/chapter-01.md", "承認前の章本文")
        qa = self.qa_artifact(run_id, "draft", chapter, "chapter-01")
        pack = json.loads(self.style_candidate_path.read_text(encoding="utf-8"))
        source = self.root / pack["note_candidates"][0]["source_path"]
        source.write_text(source.read_text(encoding="utf-8") + "改変\n", encoding="utf-8")
        with self.assertRaisesRegex(note_team.NoteTeamError, "noteファイルSHA-256"):
            note_team.submit_artifact(
                self.root,
                run_id,
                "draft",
                chapter,
                "note-writer",
                "chapter-01",
                qa,
            )
        with self.assertRaises(note_team.NoteTeamError):
            self.create("tampered-style")
        self.assertTrue(
            any(
                "style corpusエラー" in issue
                for issue in note_team.validate_installation(self.root)
            )
        )

    def test_style_dashboard_escapes_full_text_and_precedes_run_cards(self) -> None:
        existing, _ = self.create("style-dashboard-run")
        self.reset_style_registry()
        pack = json.loads(self.style_candidate_path.read_text(encoding="utf-8"))
        pack["note_candidates"][0]["title"] = "<script>alert(1)</script>"
        pack["note_candidates"][0]["preview"] = '<img src=x onerror="boom">'
        pack["x_candidates"][0]["text"] = "<b>X全文</b>"
        pack["x_candidates"][0]["preview"] = "<i>Xプレビュー</i>"
        pack["x_candidates"][0]["text_sha256"] = note_team.sha256_bytes(
            pack["x_candidates"][0]["text"].encode("utf-8")
        )
        self.rewrite_style_candidate_pack(pack)
        page = note_team.render_dashboard(
            self.root, [existing], "csrf-token"
        )
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertNotIn('<img src=x onerror="boom">', page)
        self.assertNotIn("<b>X全文</b>", page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)
        self.assertIn("&lt;b&gt;X全文&lt;/b&gt;", page)
        self.assertIn("承認対象のnote本文を全文確認", page)
        self.assertLess(page.index("文体学習元のオーナー承認"), page.index(existing["run_id"]))
        style_form = re.search(
            r"<form method=\"post\" action=\"/action\">(.*?)</form>", page, re.S
        )
        self.assertIsNotNone(style_form)
        self.assertIn("candidate_pack_sha256", style_form.group(1))
        self.assertIn("registry_sha256", style_form.group(1))
        self.assertNotIn("source_path", style_form.group(1))
        self.assertNotIn("X全文", style_form.group(1))

        self.style_candidate_path.unlink()
        missing = note_team.render_dashboard(self.root, [existing], "csrf-token")
        self.assertIn("候補packは準備中", missing)

    def test_style_approval_via_local_ui_uses_csrf_and_sha_guards(self) -> None:
        self.reset_style_registry()
        token = "style-ui-token"
        server = ThreadingHTTPServer(
            ("127.0.0.1", 0), note_team.make_handler(self.root, token)
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        cookie_jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(cookie_jar),
            urllib.request.HTTPRedirectHandler(),
        )
        try:
            with opener.open(base + "/?token=" + token, timeout=3) as response:
                page = response.read().decode("utf-8")
            csrf = re.search(r'name="csrf" value="([^"]+)"', page)
            pack_sha = re.search(
                r'name="candidate_pack_sha256" value="([0-9a-f]{64})"', page
            )
            registry_sha = re.search(
                r'name="registry_sha256" value="([0-9a-f]{64})"', page
            )
            self.assertIsNotNone(csrf)
            self.assertIsNotNone(pack_sha)
            self.assertIsNotNone(registry_sha)
            denied_body = urllib.parse.urlencode(
                {
                    "csrf": "wrong",
                    "action": "approve_style_corpus",
                    "candidate_pack_sha256": pack_sha.group(1),
                    "registry_sha256": registry_sha.group(1),
                }
            ).encode("utf-8")
            with self.assertRaises(urllib.error.HTTPError) as denied:
                opener.open(
                    urllib.request.Request(
                        base + "/action", data=denied_body, method="POST"
                    ),
                    timeout=3,
                )
            self.assertEqual(denied.exception.code, 403)

            approved_body = urllib.parse.urlencode(
                {
                    "csrf": csrf.group(1),
                    "action": "approve_style_corpus",
                    "candidate_pack_sha256": pack_sha.group(1),
                    "registry_sha256": registry_sha.group(1),
                }
            ).encode("utf-8")
            with opener.open(
                urllib.request.Request(
                    base + "/action", data=approved_body, method="POST"
                ),
                timeout=3,
            ) as response:
                self.assertEqual(response.status, 200)
            self.assertEqual(note_team.verify_style_corpus(self.root)["status"], "approved")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_approval_ui_accepts_browser_loopback_origins_without_weakening_guards(self) -> None:
        self.reset_style_registry()
        token = "browser-origin-token"
        server, thread, base = self.start_approval_test_server(token)
        try:
            opener, page, set_cookie = self.bootstrap_approval_test_session(
                base, token
            )
            self.assertIsNotNone(set_cookie)
            self.assertIn("HttpOnly", set_cookie)
            self.assertIn("SameSite=Strict", set_cookie)
            self.assertNotIn("SameSite=None", set_cookie)

            csrf = re.search(r'name="csrf" value="([^"]+)"', page)
            pack_sha = re.search(
                r'name="candidate_pack_sha256" value="([0-9a-f]{64})"', page
            )
            registry_sha = re.search(
                r'name="registry_sha256" value="([0-9a-f]{64})"', page
            )
            self.assertIsNotNone(csrf)
            self.assertIsNotNone(pack_sha)
            self.assertIsNotNone(registry_sha)
            fields = {
                "csrf": csrf.group(1),
                "candidate_pack_sha256": pack_sha.group(1),
                "registry_sha256": registry_sha.group(1),
            }
            initial_registry = self.style_registry_path.read_bytes()

            with self.assertRaises(urllib.error.HTTPError) as foreign:
                self.style_approval_post(
                    opener,
                    base,
                    origin="https://foreign.example",
                    **fields,
                )
            self.assertIn(foreign.exception.code, {403, 404})
            self.assertEqual(self.style_registry_path.read_bytes(), initial_registry)

            no_cookie_opener = urllib.request.build_opener(
                urllib.request.HTTPRedirectHandler()
            )
            with self.assertRaises(urllib.error.HTTPError) as no_cookie:
                self.style_approval_post(
                    no_cookie_opener,
                    base,
                    origin="null",
                    **fields,
                )
            self.assertIn(no_cookie.exception.code, {403, 404})
            self.assertEqual(self.style_registry_path.read_bytes(), initial_registry)

            with self.assertRaises(urllib.error.HTTPError) as bad_csrf:
                self.style_approval_post(
                    opener,
                    base,
                    csrf="invalid-csrf",
                    candidate_pack_sha256=fields["candidate_pack_sha256"],
                    registry_sha256=fields["registry_sha256"],
                    origin="null",
                )
            self.assertEqual(bad_csrf.exception.code, 403)
            self.assertEqual(self.style_registry_path.read_bytes(), initial_registry)

            alias_origin = base.replace("127.0.0.1", "localhost")
            with self.style_approval_post(
                opener, base, origin=alias_origin, **fields
            ) as response:
                self.assertEqual(response.status, 200)
            approved_registry = self.style_registry_path.read_bytes()
            self.assertNotEqual(approved_registry, initial_registry)
            self.assertEqual(
                json.loads(approved_registry.decode("utf-8"))["status"], "approved"
            )

            # Origin=null is accepted only with both the valid session cookie
            # and valid CSRF token. Re-approving the exact fixed corpus is an
            # intentionally idempotent existing operation.
            with self.style_approval_post(
                opener,
                base,
                origin="null",
                **fields,
            ) as response:
                self.assertEqual(response.status, 200)
            self.assertEqual(self.style_registry_path.read_bytes(), approved_registry)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_reconciliation_reset_is_available_only_in_local_ui(self) -> None:
        state = self.prepare_claimed_note_draft("reconciliation-ui")
        run_id = state["run_id"]
        state = note_team.record_external_failure(
            self.root, run_id, "note_draft", "結果記録前に通信断"
        )
        claim_id = state["stages"]["note_draft"]["claim_id"]
        token = "reconciliation-token"
        server = ThreadingHTTPServer(
            ("127.0.0.1", 0), note_team.make_handler(self.root, token)
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        cookie_jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(cookie_jar),
            urllib.request.HTTPRedirectHandler(),
        )
        try:
            with opener.open(base + "/?token=" + token, timeout=3) as response:
                page = response.read().decode("utf-8")
                self.assertIn("外部操作の結果が不明", page)
                self.assertIn(claim_id, page)
                csrf = re.search(r'name="csrf" value="([^"]+)"', page)
                self.assertIsNotNone(csrf)
            body = urllib.parse.urlencode(
                {
                    "csrf": csrf.group(1),
                    "run_id": run_id,
                    "stage": "note_draft",
                    "action": "confirm_no_external_draft",
                    "comment": "you_ai_dx の下書き一覧に対象なし",
                }
            ).encode("utf-8")
            with opener.open(
                urllib.request.Request(base + "/action", data=body, method="POST"),
                timeout=3,
            ) as response:
                self.assertEqual(response.status, 200)
            updated = note_team.load_state(self.root, run_id)
            self.assertEqual(
                updated["stages"]["note_draft"]["status"], "authorization_required"
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_installation_validation(self) -> None:
        self.assertEqual(note_team.validate_installation(self.root), [])

    def test_note_public_url_must_match_editor_draft_id(self) -> None:
        with self.assertRaisesRegex(note_team.NoteTeamError, "editor draft ID"):
            note_team.validate_note_public_url(
                "https://note.com/you_ai_dx/n/n-different",
                "you_ai_dx",
                "note公開結果",
                "n-original",
            )

    def test_installation_validation_rejects_bad_x_account(self) -> None:
        config_path = self.root / note_team.PROJECT_REL / "config/team.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["x_account"] = {"user_id": "not-a-number", "username": "too-long-username-value"}
        config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
        issues = note_team.validate_installation(self.root)
        self.assertIn("x_account.user_id の形式が不正です", issues)
        self.assertIn("x_account.username の形式が不正です", issues)

    def test_validate_state_rejects_x_reply_without_main(self) -> None:
        state, _ = self.create("bad-x-component-order")
        state["current_stage"] = "x_publish"
        for stage in note_team.STAGES[: note_team.STAGES.index("x_publish")]:
            state["stages"][stage]["status"] = "approved"
        authorization_id = "authorization-test"
        claim_id = "claim-test"
        state["external_authorizations"] = [
            {
                "id": authorization_id,
                "stage": "x_publish",
                "consumed_at": note_team.iso_now(),
                "claim_id": claim_id,
            }
        ]
        state["stages"]["x_publish"].update(
            {
                "status": "external_in_progress",
                "authorization_id": authorization_id,
                "claim_id": claim_id,
                "claim_expires_at": note_team.iso_now(),
                "components": {
                    "main": {"status": "pending", "tweet_id": None, "tweet_url": None},
                    "reply": {
                        "status": "posted",
                        "tweet_id": "100002",
                        "tweet_url": "https://x.com/testuser/status/100002",
                    },
                },
            }
        )
        with self.assertRaisesRegex(note_team.NoteTeamError, "X本投稿より先"):
            note_team.validate_state(state)


if __name__ == "__main__":
    unittest.main()
