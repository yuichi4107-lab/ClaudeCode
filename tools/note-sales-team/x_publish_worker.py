#!/usr/bin/env python3
"""Claim-backed X publisher for one note-sales-team run.

``prepare`` performs only read operations against X and freezes the exact
account/text/note URL shown in the local approval UI.  ``publish`` requires the
stage to be owner-authorized, consumes that authorization, creates the main
post once, persists its ID, then creates and verifies the first reply.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"moduleを読み込めません: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


note_team = _load_module("note_team_worker", HERE / "note_team.py")
post_to_x = _load_module("post_to_x_worker", ROOT / "scripts" / "post_to_x.py")


def _canonical_url(username: str, tweet_id: str) -> str:
    return f"https://x.com/{username}/status/{tweet_id}"


def _identity(root: Path) -> dict[str, str]:
    observed = post_to_x.get_identity()
    user_id = str(observed.get("id") or "")
    username = str(observed.get("username") or "")
    if not user_id.isdigit() or not username:
        raise note_team.NoteTeamError("X APIから有効なuser ID/usernameを取得できません")
    configured = note_team.load_config(root).get("x_account", {})
    if not isinstance(configured, dict) or not configured.get("user_id") or not configured.get("username"):
        raise note_team.NoteTeamError("team.jsonにx_account.user_idとusernameの固定が必要です")
    expected_id = str(configured["user_id"])
    expected_username = str(configured["username"])
    if expected_id != user_id or expected_username.lower() != username.lower():
        raise note_team.NoteTeamError("team.jsonの予定XアカウントとAPI認証アカウントが一致しません")
    return {
        "expected_x_user_id": expected_id,
        "observed_x_user_id": user_id,
        "expected_x_username": expected_username,
        "observed_x_username": username,
    }


def build_preflight(root: Path, run_id: str) -> tuple[dict[str, Any], Path]:
    state = note_team.load_state(root, run_id)
    stage_data = note_team.active_stage(state, "x_publish")
    if stage_data.get("status") != "authorization_required":
        raise note_team.NoteTeamError("X事前確認はauthorization_required状態だけ作成できます")
    identity = _identity(root)
    variant = note_team.selected_promotion_variant(root, state)
    note_publish_record = note_team.load_stage_json(root, state, "note_publish")
    public_url = str(note_publish_record.get("public_url") or "")
    primary_text = variant["primary_text"]
    reply_text = variant["reply_text_template"].replace("[NOTE_URL]", public_url)
    primary_check = post_to_x.dry_run(primary_text)
    reply_check = post_to_x.dry_run(reply_text, in_reply_to_tweet_id="1")
    blockers = list(primary_check["blockers"]) + list(reply_check["blockers"])
    if blockers:
        raise note_team.NoteTeamError("X事前検証が不合格です: " + " / ".join(blockers))
    payload: dict[str, Any] = {
        "platform": "x",
        "operation": "create_post_and_reply",
        **identity,
        "selected_promotion_id": state["selected_promotion_id"],
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
    directory = note_team.run_dir(root, run_id)
    output = directory / "x-preflight.json"
    note_team.atomic_write_json(output, payload)
    note_team.submit_preflight(
        root,
        run_id,
        output.relative_to(directory).as_posix(),
        actor="x-publish-worker",
        stage="x_publish",
    )
    return payload, output


def _verify_readback(
    readback: dict[str, Any],
    *,
    expected_id: str,
    expected_author_id: str,
    expected_text: str,
    expected_reply_to: str | None,
) -> None:
    if str(readback.get("id")) != expected_id:
        raise note_team.NoteTeamError("X API読み戻しのtweet IDがPOST結果と一致しません")
    if str(readback.get("author_id")) != expected_author_id:
        raise note_team.NoteTeamError("X API読み戻しのauthor IDが予定アカウントと一致しません")
    if readback.get("expanded_text", readback.get("text")) != expected_text:
        raise note_team.NoteTeamError("X API読み戻し本文が承認済み本文と一致しません")
    observed_reply_to = readback.get("reply_to_tweet_id")
    if observed_reply_to != expected_reply_to:
        raise note_team.NoteTeamError("X API読み戻しの返信先が予定と一致しません")


def publish(root: Path, run_id: str) -> tuple[dict[str, Any], Path]:
    state = note_team.load_state(root, run_id)
    stage_data = note_team.active_stage(state, "x_publish")
    if stage_data.get("status") != "authorized":
        raise note_team.NoteTeamError("X投稿の未使用個別許可がありません")
    directory = note_team.run_dir(root, run_id)
    preflight_path = note_team.resolve_inside(
        directory, stage_data.get("preflight_artifact") or ""
    )
    preflight = note_team.validate_x_publish_preflight(
        root,
        state,
        preflight_path,
        stage_data.get("preflight_sha256"),
    )
    identity = _identity(root)
    for key in (
        "expected_x_user_id",
        "observed_x_user_id",
        "expected_x_username",
        "observed_x_username",
    ):
        if identity[key] != preflight[key]:
            raise note_team.NoteTeamError("X投稿直前の認証アカウントが承認時から変わりました")

    claimed = note_team.claim_external(root, run_id, "x_publish", "x-publish-worker")
    username = preflight["expected_x_username"]
    try:
        note_team.require_active_external_claim(claimed, "x_publish", "X本投稿")
        main_created = post_to_x.post_one(preflight["primary_text"])
        main_id = str(main_created["id"])
        main_url = _canonical_url(username, main_id)
        posted_at = note_team.iso_now()
        note_team.record_external_component(
            root, run_id, "x_publish", "main", main_id, main_url
        )

        note_team.require_active_external_claim(
            note_team.load_state(root, run_id), "x_publish", "Xリプ投稿"
        )
        reply_created = post_to_x.post_one(
            preflight["reply_text"], in_reply_to_tweet_id=main_id
        )
        reply_id = str(reply_created["id"])
        reply_url = _canonical_url(username, reply_id)
        reply_posted_at = note_team.iso_now()
        note_team.record_external_component(
            root, run_id, "x_publish", "reply", reply_id, reply_url
        )

        main_readback = post_to_x.readback_tweet(main_id)
        reply_readback = post_to_x.readback_tweet(reply_id)
        expected_author_id = preflight["expected_x_user_id"]
        _verify_readback(
            main_readback,
            expected_id=main_id,
            expected_author_id=expected_author_id,
            expected_text=preflight["primary_text"],
            expected_reply_to=None,
        )
        _verify_readback(
            reply_readback,
            expected_id=reply_id,
            expected_author_id=expected_author_id,
            expected_text=preflight["reply_text"],
            expected_reply_to=main_id,
        )
        checked_at = note_team.iso_now()
        result = {
            **{
                key: preflight[key]
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
            "primary_tweet_id": main_id,
            "primary_tweet_url": main_url,
            "primary_author_id": main_readback["author_id"],
            "reply_tweet_id": reply_id,
            "reply_tweet_url": reply_url,
            "reply_author_id": reply_readback["author_id"],
            "reply_to_tweet_id": reply_readback["reply_to_tweet_id"],
            "api_readback_verified": True,
            "posted_at": posted_at,
            "reply_posted_at": reply_posted_at,
            "checked_at": checked_at,
            "claim_id": claimed["stages"]["x_publish"]["claim_id"],
            "preflight_sha256": claimed["stages"]["x_publish"]["preflight_sha256"],
        }
        output = directory / "x-publish-result.json"
        note_team.atomic_write_json(output, result)
        note_team.submit_artifact(
            root,
            run_id,
            "x_publish",
            output.relative_to(directory).as_posix(),
            "x-publish-worker",
        )
        return result, output
    except Exception as exc:
        current = note_team.load_state(root, run_id)
        if (
            current.get("status") == "active"
            and current.get("current_stage") == "x_publish"
            and current["stages"]["x_publish"].get("status") == "external_in_progress"
        ):
            note_team.record_external_failure(
                root,
                run_id,
                "x_publish",
                f"{type(exc).__name__}: X投稿結果を完全確定できません",
                "x-publish-worker",
            )
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="note販売AIチーム X publisher")
    parser.add_argument("command", choices=("prepare", "publish"))
    parser.add_argument("run_id")
    parser.add_argument("--root", type=Path)
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve() if args.root else note_team.repo_root()
        if args.command == "prepare":
            payload, output = build_preflight(root, args.run_id)
        else:
            payload, output = publish(root, args.run_id)
        print(
            json.dumps(
                {
                    "status": "prepared" if args.command == "prepare" else "posted",
                    "run_id": args.run_id,
                    "artifact": output.relative_to(root).as_posix(),
                    "payload": payload,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except (note_team.NoteTeamError, RuntimeError, ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
