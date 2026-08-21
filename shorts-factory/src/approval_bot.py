"""Telegram承認デーモン。

- queue の ready_for_review を検知 → 動画プレビュー+承認ボタンを送信
- ボタン押下（callback_query）を getUpdates ロングポーリングで受信
    ✅承認 → approved へ遷移 → 有効媒体へ投稿 → posted/failed
    ❌却下 → skipped
    ⏸保留 → そのまま（ボタンは残る）
- ボタンが届かない時は Telegram の文字コマンドでも同じ操作を受け付ける
- approved（auto_post含む）を検知 → 投稿実行

launchd（com.ynfactory.shorts-approval）で KeepAlive 常駐する。
"""
from __future__ import annotations

import atexit
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

from .config import CONFIG
from . import notify, post_lock, queue_lib, topic_store
from .logging_utils import redact_secrets
from .state_io import atomic_write_json
from . import drive_guard

LOCK_FILE = CONFIG.runtime_dir / "approval_bot.pid"
QUEUE_SCAN_INTERVAL = 30
PENDING_REJECTIONS_DIR = CONFIG.marketing_dir / "pending_rejections"
PREVIEW_RETRY_DELAY = timedelta(minutes=10)
PREVIEW_LOCK_STALE_AFTER = timedelta(minutes=15)
QUEUE_SCAN_RECENT_FILES = 80
QUEUE_SCAN_MAX_ITEMS = 20
WATCHDOG_TIMEOUT_SEC = 600
WATCHDOG_CHECK_INTERVAL_SEC = 60
POST_WORKER_STALE_AFTER = timedelta(minutes=30)
APPROVED_SCAN_RESUME_WINDOW = timedelta(minutes=10)
TEXT_COMMANDS = {
    "/approve": "approve",
    "approve": "approve",
    "承認": "approve",
    "投稿": "approve",
    "ok": "approve",
    "ｏｋ": "approve",
    "/reject": "reject",
    "reject": "reject",
    "却下": "reject",
    "作り直し": "reject",
    "作り直す": "reject",
    "/hold": "hold",
    "hold": "hold",
    "保留": "hold",
    "待機": "hold",
}
_last_progress_at = time.monotonic()
_watchdog_started = False


def log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%m-%d %H:%M:%S')}] {redact_secrets(msg, [CONFIG.telegram_token])}"
    print(line, flush=True)
    with open(CONFIG.logs_dir / "approval_bot.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _mark_progress() -> None:
    global _last_progress_at
    _last_progress_at = time.monotonic()


def _watchdog_stalled(now: float, last_progress_at: float, timeout_sec: float) -> bool:
    return now - last_progress_at >= timeout_sec


def _watchdog_loop() -> None:
    while True:
        time.sleep(WATCHDOG_CHECK_INTERVAL_SEC)
        stalled_for = time.monotonic() - _last_progress_at
        if _watchdog_stalled(time.monotonic(), _last_progress_at, WATCHDOG_TIMEOUT_SEC):
            log(f"approval_bot watchdog: {int(stalled_for)}秒応答なし。再起動します")
            os._exit(70)


def _start_watchdog() -> None:
    global _watchdog_started
    if _watchdog_started:
        return
    _watchdog_started = True
    threading.Thread(target=_watchdog_loop, name="approval-bot-watchdog", daemon=True).start()


def _acquire_lock() -> None:
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    while True:
        try:
            fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            try:
                pid = int(LOCK_FILE.read_text().strip())
                os.kill(pid, 0)
                raise SystemExit(f"approval_bot は既に稼働中です (pid={pid})")
            except (ValueError, ProcessLookupError, PermissionError, OSError):
                LOCK_FILE.unlink(missing_ok=True)
                continue
        else:
            os.write(fd, str(os.getpid()).encode("utf-8"))
            os.close(fd)
            break
    atexit.register(lambda: LOCK_FILE.unlink(missing_ok=True))


def _api(method: str) -> str:
    return f"https://api.telegram.org/bot{CONFIG.telegram_token}/{method}"


def _answer_callback_status(cb_id: str, text: str) -> str:
    try:
        response = requests.post(
            _api("answerCallbackQuery"),
            data={"callback_query_id": cb_id, "text": text[:190]},
            timeout=15,
        )
        response.raise_for_status()
        return "ok"
    except requests.RequestException as exc:
        response = getattr(exc, "response", None)
        detail = ""
        if response is not None and response.text:
            detail = f" body={response.text[:300]}"
        log(f"Telegram callback応答失敗: {exc}{detail}")
        body = (getattr(response, "text", "") or "").lower() if response is not None else ""
        if response is not None and response.status_code == 400 and (
            "query is too old" in body or "query id is invalid" in body
        ):
            return "expired"
        return "failed"


def _answer_callback(cb_id: str, text: str) -> bool:
    return _answer_callback_status(cb_id, text) == "ok"


def _callback_message_matches_item(item: dict, msg: dict) -> bool:
    expected = item.get("telegram", {}).get("message_id")
    actual = msg.get("message_id")
    if expected is None or actual is None:
        return False
    try:
        return int(expected) == int(actual)
    except (TypeError, ValueError):
        return False


def _allow_action_after_callback_answer(
    cb_id: str,
    response_text: str,
    item: dict,
    msg: dict,
    action_label: str,
    retry_command: str,
) -> bool:
    status = _answer_callback_status(cb_id, response_text)
    if status == "ok":
        return True
    if status == "expired" and _callback_message_matches_item(item, msg):
        log(f"callback応答期限切れだが現行メッセージ一致のため反映: action={action_label} item={item['id']}")
        notify.send_message(
            f"⚠️ Telegram側の応答期限切れでしたが、現行ボタンの操作として{action_label}を反映します: "
            f"<code>{item['id']}</code>"
        )
        return True
    notify.send_message(
        "⚠️ 承認ボタンの応答期限切れ/確認失敗のため、操作は反映していません。\n"
        f"操作する場合は <code>{retry_command} {item['id']}</code> と送ってください。"
    )
    return False


def _remove_buttons(message_id: int) -> None:
    try:
        requests.post(
            _api("editMessageReplyMarkup"),
            data={
                "chat_id": CONFIG.telegram_chat_id,
                "message_id": message_id,
                "reply_markup": json.dumps({"inline_keyboard": []}),
            },
            timeout=15,
        ).raise_for_status()
    except requests.RequestException as exc:
        log(f"Telegramボタン削除失敗: {exc}")


def _pending_rejection_path(chat_id: str | int) -> Path:
    PENDING_REJECTIONS_DIR.mkdir(parents=True, exist_ok=True)
    return PENDING_REJECTIONS_DIR / f"{chat_id}.json"


def _set_pending_rejection(chat_id: str | int, item_id: str) -> None:
    atomic_write_json(
        _pending_rejection_path(chat_id),
        {"item_id": item_id, "created_at": datetime.now().isoformat()},
    )


def _spawn_replacement(item: dict) -> None:
    """Rejected slots should get another candidate without requiring manual recovery."""
    difficulty = item.get("difficulty") or "intermediate"
    script = CONFIG.runtime_dir / "app" / "scripts" / "run_generate.sh"
    log_path = CONFIG.logs_dir / "replacement_generate.log"
    env = os.environ.copy()
    with open(log_path, "a", encoding="utf-8") as log_file:
        log_file.write(
            f"\n[{datetime.now().isoformat()}] replacement_for={item['id']} difficulty={difficulty}\n"
        )
        try:
            subprocess.Popen(
                [str(script), "--difficulty", difficulty],
                cwd=str(CONFIG.runtime_dir / "app"),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError as exc:
            log(f"代替候補生成の起動失敗: {exc}")


def _preview_video_path(item: dict) -> Path:
    """Resolve preview media from local runtime storage only."""
    video = item.get("video") or {}
    raw_video_path = video.get("local_path") or video.get("path")
    video_path = Path(raw_video_path) if raw_video_path else None
    if video_path is not None:
        drive_guard.assert_local(video_path, "preview video")
    output_dir = item.get("output_dir")
    if output_dir:
        video_name = video_path.name if video_path is not None else "final.mp4"
        runtime_path = CONFIG.work_dir / Path(output_dir).name / video_name
        if runtime_path.exists():
            return runtime_path
        archived_path = CONFIG.outputs_dir / Path(output_dir).name / video_name
        if archived_path.exists():
            return archived_path
    if video_path is not None and video_path.exists():
        return video_path
    raise FileNotFoundError(f"local preview video missing for {item.get('id')}")


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _preview_retry_allowed(item: dict) -> bool:
    telegram = item.setdefault("telegram", {})
    if telegram.get("preview_sent_untracked_at"):
        return False
    started_at = _parse_iso(telegram.get("preview_send_started_at"))
    if not started_at:
        return True
    # A started attempt without an explicit failure may already be visible in
    # Telegram. Fail closed instead of creating a duplicate preview/button.
    if not telegram.get("preview_send_failed_at"):
        return False
    return datetime.now().astimezone() - started_at >= PREVIEW_RETRY_DELAY


def _preview_lock_path(item_id: str) -> Path:
    lock_dir = CONFIG.runtime_dir / "preview_locks"
    lock_dir.mkdir(parents=True, exist_ok=True)
    safe_id = item_id.replace("/", "_").replace(":", "_")
    return lock_dir / f"{safe_id}.lock"


def _preview_lock_stale(path: Path) -> bool:
    try:
        modified_at = datetime.fromtimestamp(path.stat().st_mtime).astimezone()
    except OSError:
        return True
    return datetime.now().astimezone() - modified_at >= PREVIEW_LOCK_STALE_AFTER


def _acquire_preview_lock(item_id: str) -> bool:
    path = _preview_lock_path(item_id)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        if _preview_lock_stale(path):
            try:
                path.unlink()
            except OSError:
                return False
            return _acquire_preview_lock(item_id)
        return False
    except OSError as exc:
        log(f"プレビュー送信ロック作成失敗: {item_id}: {exc}")
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"pid": os.getpid(), "created_at": _now_iso()}, f, ensure_ascii=False)
    return True


def _release_preview_lock(item_id: str) -> None:
    try:
        _preview_lock_path(item_id).unlink(missing_ok=True)
    except OSError as exc:
        log(f"プレビュー送信ロック解除失敗: {item_id}: {exc}")


def _as_bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return bool(value)


def _as_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _deferred_retry_settings() -> tuple[bool, int, float, timedelta]:
    enabled = _as_bool(CONFIG.get("queue", "deferred_retry_failed_posts", default=True))
    attempts = _as_int(CONFIG.get("queue", "deferred_retry_max_attempts", default=3), 3)
    delay_sec = _as_float(CONFIG.get("queue", "deferred_retry_delay_sec", default=900), 900.0)
    window_hours = _as_float(CONFIG.get("queue", "deferred_retry_window_hours", default=6), 6.0)
    return enabled, max(0, attempts), max(0.0, delay_sec), timedelta(hours=max(0.0, window_hours))


def _scan_items(status: str) -> list[dict]:
    return queue_lib.list_items(
        status,
        recent_files=QUEUE_SCAN_RECENT_FILES,
        max_items=QUEUE_SCAN_MAX_ITEMS,
    )


def _failed_retry_platforms(item: dict) -> list[str]:
    return [
        name
        for name, info in (item.get("platforms") or {}).items()
        if info.get("enabled")
        and info.get("status") == "failed"
        and not info.get("non_retryable")
    ]


def _latest_platform_attempt_at(item: dict, platforms: list[str]) -> datetime | None:
    values = []
    for platform in platforms:
        value = (item.get("platforms") or {}).get(platform, {}).get("last_attempt_at")
        parsed = _parse_iso(value)
        if parsed:
            values.append(parsed)
    return max(values) if values else None


def _retry_window_reference_at(item: dict) -> datetime | None:
    for value in (
        item.get("review", {}).get("decided_at"),
        item.get("scheduled_for"),
        item.get("created_at"),
    ):
        parsed = _parse_iso(value)
        if parsed:
            return parsed
    return None


def _deferred_retry_allowed(item: dict, now: datetime | None = None) -> tuple[bool, str, list[str]]:
    now = now or datetime.now().astimezone()
    enabled, max_attempts, delay_sec, window = _deferred_retry_settings()
    if not enabled:
        return False, "disabled", []
    if item.get("status") not in {"partial_failed", "failed"}:
        return False, "status", []
    if not item.get("review", {}).get("owner_approved"):
        return False, "not_approved", []
    platforms = _failed_retry_platforms(item)
    if not platforms:
        return False, "no_failed_platforms", []

    reference_at = _retry_window_reference_at(item)
    if reference_at:
        if reference_at.tzinfo is None and now.tzinfo is not None:
            reference_at = reference_at.replace(tzinfo=now.tzinfo)
        if now - reference_at > window:
            return False, "expired", platforms

    retry_state = item.setdefault("deferred_retry", {})
    attempts = _as_int(retry_state.get("attempts"), 0)
    if attempts >= max_attempts:
        return False, "max_attempts", platforms

    last_attempt = _parse_iso(retry_state.get("last_attempt_at")) or _latest_platform_attempt_at(item, platforms)
    if not last_attempt:
        return False, "missing_attempt_at", platforms
    if last_attempt.tzinfo is None and now.tzinfo is not None:
        last_attempt = last_attempt.replace(tzinfo=now.tzinfo)
    elapsed = now - last_attempt
    if elapsed > window:
        return False, "expired", platforms
    if elapsed < timedelta(seconds=delay_sec):
        return False, "cooldown", platforms
    return True, "due", platforms


def _approval_event(via: str, action: str) -> str:
    route = "Telegram文字コマンド" if via == "telegram_text" else "Telegram"
    return f"{route}で{action}"


def _is_actionable_status(item: dict) -> bool:
    return item.get("status") in ("ready_for_review", "blocked")


def _process_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def _posting_worker_active(item: dict, now: datetime | None = None) -> bool:
    if post_lock.active(item["id"]):
        return True
    worker = item.get("posting_worker") or {}
    if _process_alive(worker.get("pid")):
        return True
    started_at = _parse_iso(worker.get("started_at"))
    if not started_at:
        return False
    now = now or datetime.now().astimezone()
    if started_at.tzinfo is None and now.tzinfo is not None:
        started_at = started_at.replace(tzinfo=now.tzinfo)
    return now - started_at < POST_WORKER_STALE_AFTER


def _enabled_platform_statuses(item: dict) -> list[str]:
    return [
        info.get("status")
        for info in (item.get("platforms") or {}).values()
        if info.get("enabled")
    ]


def _approved_scan_resume_allowed(item: dict) -> tuple[bool, str]:
    """Only resume very recent approved items that have not posted anywhere yet."""
    review = item.get("review") or {}
    if not review.get("owner_approved"):
        return False, "not_owner_approved"
    decided_at = _parse_iso(review.get("decided_at"))
    if not decided_at:
        return False, "missing_decided_at"
    now = datetime.now().astimezone()
    if decided_at.tzinfo is None and now.tzinfo is not None:
        decided_at = decided_at.replace(tzinfo=now.tzinfo)
    if now - decided_at > APPROVED_SCAN_RESUME_WINDOW:
        return False, "approval_expired_for_scan_resume"
    statuses = _enabled_platform_statuses(item)
    if any(status == "posted" for status in statuses):
        return False, "already_partially_posted"
    return True, "ok"


def _record_posting_guard_skip(item: dict, reason: str) -> None:
    guard = item.setdefault("posting_guard", {})
    if guard.get("last_scan_skip_reason") == reason:
        return
    guard["last_scan_skip_reason"] = reason
    guard["last_scan_skip_at"] = _now_iso()
    queue_lib.save_item(item)
    log(f"承認済み自動再開を停止: {item['id']} reason={reason}")


def _spawn_post_worker(item: dict, reason: str, *, retry_failed: bool = False) -> bool:
    if _posting_worker_active(item):
        return False

    now = _now_iso()
    worker = item.setdefault("posting_worker", {})
    worker["attempts"] = _as_int(worker.get("attempts"), 0) + 1
    worker["started_at"] = now
    worker["reason"] = reason
    worker.pop("completed_at", None)
    worker.pop("exit_code", None)
    worker.pop("error", None)
    queue_lib.save_item(item)
    worker = item.setdefault("posting_worker", {})

    script = CONFIG.runtime_dir / "app" / "scripts" / "post_approved_item.py"
    log_path = CONFIG.logs_dir / "post_worker.log"
    env = os.environ.copy()
    env["SHORTS_FACTORY_ROOT"] = str(CONFIG.runtime_dir / "app")
    command = [sys.executable, str(script), item["id"]]
    if retry_failed:
        command.append("--retry-failed")
    with open(log_path, "a", encoding="utf-8") as log_file:
        log_file.write(f"\n[{datetime.now().isoformat()}] item={item['id']} reason={reason}\n")
        try:
            proc = subprocess.Popen(
                command,
                cwd=str(CONFIG.runtime_dir / "app"),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError as exc:
            worker["error"] = str(exc)
            queue_lib.save_item(item)
            log(f"投稿ワーカー起動失敗: {item['id']} {exc}")
            return False

    latest = queue_lib.load_item(item["id"])
    worker = latest.setdefault("posting_worker", {})
    worker["pid"] = proc.pid
    worker.setdefault("started_at", now)
    worker.setdefault("reason", reason)
    queue_lib.save_item(latest)
    log(f"投稿ワーカー起動: {item['id']} pid={proc.pid} reason={reason}")
    return True


def _approve_item(item: dict, *, via: str, message_id: int | None = None) -> dict:
    item.setdefault("review", {}).update(
        {"owner_approved": True, "decided_at": datetime.now().isoformat(), "via": via}
    )
    queue_lib.transition(item, "approved", _approval_event(via, "承認"))
    if message_id:
        _remove_buttons(message_id)
    log(f"承認: {item['id']} via={via}")
    _spawn_post_worker(item, f"approved:{via}")
    return item


def _reject_item(
    item: dict,
    *,
    chat_id: str | int,
    via: str,
    message_id: int | None = None,
) -> dict:
    item.setdefault("review", {}).update(
        {
            "owner_approved": False,
            "decided_at": datetime.now().isoformat(),
            "via": via,
            "rejection_reason_pending": True,
            "replacement_requested_at": datetime.now().isoformat(),
        }
    )
    queue_lib.transition(item, "skipped", _approval_event(via, "却下"))
    _set_pending_rejection(chat_id, item["id"])
    _spawn_replacement(item)
    if message_id:
        _remove_buttons(message_id)
    notify.send_message(
        "📝 却下理由をこのチャットに普通のメッセージで送ると、"
        f"<code>{item['id']}</code> の理由として保存します。\n"
        "代替候補は自動で作成中です。"
    )
    log(f"却下: {item['id']} via={via}")
    return item


def _hold_item(item: dict, *, via: str) -> None:
    item.setdefault("history", []).append(
        {
            "ts": _now_iso(),
            "event": _approval_event(via, "保留"),
        }
    )
    queue_lib.save_item(item)
    log(f"保留: {item['id']} via={via}")


def _parse_text_command(text: str) -> tuple[str, str | None, str | None] | None:
    parts = text.split(maxsplit=2)
    if not parts:
        return None
    command = parts[0].strip().lower()
    if command.startswith("/"):
        command = command.split("@", 1)[0]
    action = TEXT_COMMANDS.get(command)
    if not action:
        return None
    item_id = parts[1] if len(parts) >= 2 else None
    detail = parts[2] if len(parts) >= 3 else None
    return action, item_id, detail


def _infer_single_actionable_item_id() -> tuple[str | None, str | None]:
    items = [item for status in ("ready_for_review", "blocked") for item in _scan_items(status)]
    if len(items) == 1:
        return items[0]["id"], None
    if not items:
        return None, "現在、操作待ちのショート動画はありません。"
    choices = "\n".join(f"- <code>{item['id']}</code>" for item in items[:5])
    return None, "対象が複数あります。次のようにIDを付けて送ってください。\n" + choices


def _scan_deferred_retries() -> None:
    for status in ("partial_failed", "failed"):
        for item in _scan_items(status):
            allowed, reason, platforms = _deferred_retry_allowed(item)
            if not allowed:
                continue
            retry_state = item.setdefault("deferred_retry", {})
            retry_state["attempts"] = _as_int(retry_state.get("attempts"), 0) + 1
            retry_state["last_attempt_at"] = _now_iso()
            retry_state["platforms"] = platforms
            item.setdefault("history", []).append(
                {
                    "ts": _now_iso(),
                    "event": f"遅延自動再投稿 {retry_state['attempts']}: {', '.join(platforms)} ({reason})",
                }
            )
            queue_lib.save_item(item)
            log(f"遅延自動再投稿worker: {item['id']} platforms={','.join(platforms)}")
            _spawn_post_worker(item, "deferred_retry", retry_failed=True)


def _retry_deferred_topic_consumes() -> None:
    """Recover topic-store updates that were deferred by transient Drive locks."""
    statuses = ("ready_for_review", "approved", "posted", "partial_failed", "failed", "blocked", "skipped")
    for status in statuses:
        _mark_progress()
        for item in _scan_items(status):
            _mark_progress()
            topic_state = item.get("topic_store") or {}
            if not topic_state.get("consume_deferred_error"):
                continue
            if not item.get("topic"):
                continue
            consume_slug = topic_state.get("consume_group_slug") or item.get("variant_group_id") or item["id"]
            consume_title = topic_state.get("consume_title") or (
                f"SNS別動画: {item['topic']}" if item.get("variant_group_id") else item["title"]
            )
            try:
                remaining = topic_store.consume_topic(
                    item["topic"],
                    consume_slug,
                    consume_title,
                    item.get("difficulty"),
                )
            except OSError as exc:
                if not topic_store.is_transient_io_error(exc):
                    raise
                topic_state["consume_deferred_error"] = str(exc)
                topic_state["last_retry_at"] = _now_iso()
                item["topic_store"] = topic_state
                queue_lib.save_item(item)
                continue

            topic_state.pop("consume_deferred_error", None)
            topic_state["consume_deferred_resolved_at"] = _now_iso()
            topic_state["remaining"] = remaining
            item["topic_store"] = topic_state
            item.setdefault("history", []).append(
                {
                    "ts": _now_iso(),
                    "event": f"topic_consume_recovered remaining={remaining}",
                }
            )
            queue_lib.save_item(item)
            log(f"ネタ帳消費を復旧: {item['id']} slug={consume_slug} remaining={remaining}")
            if remaining <= topic_store.LOW_STOCK_THRESHOLD:
                notify.send_message(f"📋 shorts-factory: ネタ帳の残りが{remaining}本です。補充してください。")


def scan_queue() -> None:
    """未送信プレビューを優先送付し、後続で復旧処理と投稿実行を行う。"""
    flushed = notify.flush_pending_messages()
    if flushed:
        log(f"保留通知を再送: {flushed}件")

    ready_items = _scan_items("ready_for_review")
    for item in ready_items:
        _mark_progress()
        telegram = item.setdefault("telegram", {})
        if telegram.get("message_id") or not _preview_retry_allowed(item):
            continue
        if not _acquire_preview_lock(item["id"]):
            continue
        try:
            try:
                item = queue_lib.load_item(item["id"])
            except FileNotFoundError:
                continue
            if item.get("status") != "ready_for_review":
                continue
            telegram = item.setdefault("telegram", {})
            if telegram.get("message_id") or not _preview_retry_allowed(item):
                continue
            telegram["preview_send_started_at"] = _now_iso()
            telegram["preview_send_attempts"] = int(telegram.get("preview_send_attempts") or 0) + 1
            queue_lib.save_item(item)
            # save_item may merge a concurrent revision and replace nested mappings.
            # Reacquire the live nested object before recording the send result.
            telegram = item.setdefault("telegram", {})
            _mark_progress()
            mid = notify.send_video(
                _preview_video_path(item),
                notify.preview_caption(item),
                reply_markup=notify.approval_keyboard(item["id"]),
            )
            _mark_progress()
            if mid:
                telegram["message_id"] = mid
                telegram["preview_sent_at"] = _now_iso()
                telegram.pop("preview_send_failed_at", None)
                queue_lib.save_item(item)
                log(f"プレビュー送信: {item['id']}")
            else:
                telegram["preview_delivery_uncertain_at"] = _now_iso()
                telegram.pop("preview_send_failed_at", None)
                queue_lib.save_item(item)
                log(f"プレビュー送信未確認（自動再送を停止）: {item['id']}")
        finally:
            _release_preview_lock(item["id"])

    # ローカル状態なので、承認待ちが残っていてもdeferred処理を飢餓させない。
    # プレビューを先に処理した後、毎scanで整合処理まで完了させる。
    _retry_deferred_topic_consumes()
    _scan_deferred_retries()

    for item in _scan_items("approved"):
        allowed, reason = _approved_scan_resume_allowed(item)
        if not allowed:
            _record_posting_guard_skip(item, reason)
            continue
        _spawn_post_worker(item, "scan_queue")


def handle_callback(cb: dict) -> None:
    data = cb.get("data", "")
    cb_id = cb["id"]
    msg = cb.get("message", {})
    if ":" not in data:
        if not _answer_callback(cb_id, "不明な操作"):
            notify.send_message("⚠️ 不明な操作を受信しました。")
        return
    action, item_id = data.split(":", 1)
    log(f"callback受信: action={action} item={item_id}")
    try:
        item = queue_lib.load_item(item_id)
    except FileNotFoundError:
        if not _answer_callback(cb_id, "対象が見つかりません"):
            notify.send_message(f"⚠️ 対象が見つかりません: <code>{item_id}</code>")
        return

    if not _is_actionable_status(item):
        if not _answer_callback(cb_id, f"既に処理済み（{item['status']}）"):
            notify.send_message(f"ℹ️ 既に処理済みです: <code>{item_id}</code>（{item['status']}）")
        return

    if action == "approve":
        if not _allow_action_after_callback_answer(
            cb_id,
            "承認しました。投稿します…",
            item,
            msg,
            "承認",
            "承認",
        ):
            return
        _approve_item(item, via="telegram", message_id=msg.get("message_id"))
    elif action == "reject":
        chat_id = msg.get("chat", {}).get("id") or CONFIG.telegram_chat_id
        if not _allow_action_after_callback_answer(
            cb_id,
            "却下しました。代替候補を作成します…",
            item,
            msg,
            "却下",
            "却下",
        ):
            return
        _reject_item(item, chat_id=chat_id, via="telegram", message_id=msg.get("message_id"))
    elif action == "hold":
        if not _allow_action_after_callback_answer(
            cb_id,
            "保留しました。ボタンはそのまま使えます",
            item,
            msg,
            "保留",
            "保留",
        ):
            return
        _hold_item(item, via="telegram")
    else:
        if not _answer_callback(cb_id, "不明な操作"):
            notify.send_message(f"⚠️ 不明な操作を受信しました: <code>{item_id}</code>")


def _handle_text_command(chat_id: str | int, text: str) -> bool:
    parsed = _parse_text_command(text)
    if not parsed:
        return False
    action, item_id, detail = parsed
    if not item_id:
        item_id, message = _infer_single_actionable_item_id()
        if not item_id:
            notify.send_message(message or "対象IDを付けて送ってください。")
            return True
    try:
        item = queue_lib.load_item(item_id)
    except FileNotFoundError:
        notify.send_message(f"対象が見つかりません: <code>{item_id}</code>")
        return True
    if not _is_actionable_status(item):
        notify.send_message(f"既に処理済みです: <code>{item_id}</code>（{item.get('status')}）")
        return True

    log(f"文字コマンド受信: action={action} item={item_id}")
    if action == "approve":
        notify.send_message(f"✅ 承認しました。投稿します: <code>{item_id}</code>")
        _approve_item(item, via="telegram_text")
    elif action == "reject":
        _reject_item(item, chat_id=chat_id, via="telegram_text")
        if detail:
            _record_rejection_reason(item_id, detail)
            _pending_rejection_path(chat_id).unlink(missing_ok=True)
            notify.send_message(f"📝 却下理由を保存しました: <code>{item_id}</code>")
    elif action == "hold":
        _hold_item(item, via="telegram_text")
        notify.send_message(f"⏸ 保留しました: <code>{item_id}</code>")
    return True


def _record_rejection_reason(item_id: str, reason: str) -> bool:
    try:
        item = queue_lib.load_item(item_id)
    except FileNotFoundError:
        return False
    item.setdefault("review", {}).update(
        {
            "rejection_reason": reason,
            "rejection_reason_at": datetime.now().isoformat(),
            "rejection_reason_pending": False,
        }
    )
    item.setdefault("history", []).append(
        {
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "event": "却下理由を保存",
        }
    )
    queue_lib.save_item(item)
    return True


def handle_message(msg: dict) -> None:
    chat = msg.get("chat", {})
    chat_id = chat.get("id")
    text = (msg.get("text") or "").strip()
    if not chat_id or not text:
        return
    if str(chat_id) != str(CONFIG.telegram_chat_id):
        return
    if _handle_text_command(chat_id, text):
        return

    item_id = None
    reason = text
    if text.startswith("/reason "):
        parts = text.split(maxsplit=2)
        if len(parts) < 3:
            notify.send_message("形式: <code>/reason item_id 理由</code>")
            return
        _, item_id, reason = parts
    else:
        pending_path = _pending_rejection_path(chat_id)
        if not pending_path.exists():
            return
        try:
            pending = json.loads(pending_path.read_text(encoding="utf-8"))
            item_id = pending.get("item_id")
        except json.JSONDecodeError:
            pending_path.unlink(missing_ok=True)
            return

    if item_id and _record_rejection_reason(item_id, reason):
        _pending_rejection_path(chat_id).unlink(missing_ok=True)
        notify.send_message(f"📝 却下理由を保存しました: <code>{item_id}</code>")
        log(f"却下理由保存: {item_id}")


def main() -> None:
    drive_guard.install()
    CONFIG.assert_runtime_ready()
    if not notify.enabled():
        raise SystemExit("Telegram設定がありません（secrets.yaml を確認）")
    _acquire_lock()
    _start_watchdog()
    _mark_progress()
    log("approval_bot 起動")
    offset = 0
    last_scan = 0.0
    while True:
        try:
            _mark_progress()
            if time.time() - last_scan > QUEUE_SCAN_INTERVAL:
                scan_queue()
                last_scan = time.time()
                _mark_progress()
            r = requests.get(
                _api("getUpdates"),
                params={
                    "offset": offset,
                    "timeout": 25,
                    "allowed_updates": '["callback_query","message"]',
                },
                timeout=35,
            )
            _mark_progress()
            if not r.ok:
                if r.status_code == 409:
                    log("⚠️ getUpdates 409: 別プロセスがこのbotをポーリング中。60秒待機")
                    time.sleep(60)
                    _mark_progress()
                continue
            for upd in r.json().get("result", []):
                offset = max(offset, upd["update_id"] + 1)
                if "callback_query" in upd:
                    handle_callback(upd["callback_query"])
                elif "message" in upd:
                    handle_message(upd["message"])
                _mark_progress()
            if time.time() - last_scan > QUEUE_SCAN_INTERVAL:
                scan_queue()
                last_scan = time.time()
                _mark_progress()
        except KeyboardInterrupt:
            log("停止")
            break
        except Exception as e:  # デーモンは死なない
            log(f"エラー: {e}")
            time.sleep(10)
            _mark_progress()


if __name__ == "__main__":
    main()
