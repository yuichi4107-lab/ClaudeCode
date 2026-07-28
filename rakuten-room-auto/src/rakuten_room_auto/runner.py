from __future__ import annotations

from dataclasses import dataclass

from .browser import (
    SUBMIT_NOT_REFLECTED_PREFIX,
    BrowserAutomationError,
    LoginRequiredError,
    RakutenRoomBrowser,
)
from .config import AppConfig
from .ledger import Ledger, LedgerEvent
from .llm import DescriptionError, DescriptionGenerator
from .replenish import build_description, is_duplicate_product
from .sheets import GoogleSheetClient, SheetRow, now_jst_iso, parse_attempts, select_rows

DUPLICATE_PRODUCT_MESSAGE = "同一とみられる商品が既に投稿済み（または投稿待ち）のためスキップしました。"


@dataclass
class RunSummary:
    seen: int = 0
    changed: int = 0
    posted: int = 0
    errors: int = 0


def short_error(exc: BaseException) -> str:
    return " ".join(str(exc).split())[:300]


URL_CHECK_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0 Safari/537.36"
)


def validate_product_url_format(url: str) -> str | None:
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return "商品URLの形式が不正です。https:// から始まるURLを入れてください。"
    host = parsed.netloc.lower()
    if host != "rakuten.co.jp" and not host.endswith(".rakuten.co.jp"):
        return "楽天のURLではありません。楽天市場の商品ページURLを入れてください。"
    return None


def check_product_url(url: str, timeout: float = 20.0) -> str | None:
    """事前にURLを開いて確認し、問題があれば運用者向けメッセージを返す。問題なければNone。"""
    import urllib.error
    import urllib.request

    format_problem = validate_product_url_format(url)
    if format_problem:
        return format_problem
    request = urllib.request.Request(url, headers={"User-Agent": URL_CHECK_USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", 200)
    except urllib.error.HTTPError as exc:
        status = exc.code
    except Exception as exc:
        return f"商品ページの事前確認に失敗しました（{short_error(exc)}）。URLを確認してください。"
    if status >= 400:
        return f"商品ページが開けません (HTTP {status})。商品URLが無効か販売終了の可能性があります。"
    return None


def collect_completed_urls(table, config: AppConfig) -> set[str]:
    urls: set[str] = set()
    for row in table.rows:
        if row.get("status", config.sheet.columns) == config.statuses.completed:
            url = row.get("product_url", config.sheet.columns)
            if url:
                urls.add(url)
    return urls


def collect_all_urls(table, config: AppConfig) -> set[str]:
    """ステータスを問わずシート上の全商品URLを返す（補充時の重複防止用）。"""
    urls: set[str] = set()
    for row in table.rows:
        url = row.get("product_url", config.sheet.columns)
        if url:
            urls.add(url)
    return urls


def collect_items(table, config: AppConfig, statuses: set[str] | None = None) -> list[tuple[str, str]]:
    """(商品URL, 紹介文)の一覧を返す。statuses指定時はそのステータスの行だけ。同一商品判定に使う。"""
    items: list[tuple[str, str]] = []
    for row in table.rows:
        url = row.get("product_url", config.sheet.columns)
        if not url:
            continue
        if statuses is not None and row.get("status", config.sheet.columns) not in statuses:
            continue
        items.append((url, row.get("description", config.sheet.columns)))
    return items


def count_pipeline_rows(table, config: AppConfig) -> int:
    """今後投稿される見込みの「残りネタ」行数を数える。"""
    count = 0
    for row in table.rows:
        url = row.get("product_url", config.sheet.columns)
        status = row.get("status", config.sheet.columns)
        if url and status in config.statuses.pipeline:
            count += 1
    return count


class RoomAutomationRunner:
    def __init__(self, config: AppConfig):
        self.config = config
        self.sheet = GoogleSheetClient(config.google, config.sheet)
        self.ledger = Ledger(config.runtime.ledger_path)
        self.generator = DescriptionGenerator(config.llm)

    def preview(self, limit: int | None = None) -> list[SheetRow]:
        table = self.sheet.read_table()
        limit = limit or self.config.runtime.max_items_per_run
        statuses = self.config.statuses.prepare_candidates | self.config.statuses.run_candidates
        return select_rows(table, self.config.sheet, statuses, limit)

    def prepare(self, limit: int | None = None, dry_run: bool = False) -> RunSummary:
        summary = RunSummary()
        table = self.sheet.read_table()
        limit = limit or self.config.runtime.max_items_per_run
        rows = select_rows(table, self.config.sheet, self.config.statuses.prepare_candidates, limit)
        for row in rows:
            summary.seen += 1
            product_url = row.get("product_url", self.config.sheet.columns)
            description = row.get("description", self.config.sheet.columns)
            updates: dict[str, str] = {"status": self.config.statuses.approval_pending, "error": ""}
            if not description:
                try:
                    updates["description"] = self.generator.generate(product_url)
                except DescriptionError as exc:
                    updates["status"] = self.config.statuses.needs_review
                    updates["error"] = short_error(exc)
                    summary.errors += 1
            if not dry_run:
                self.sheet.update_row_fields(row, updates)
                self.ledger.append(LedgerEvent.create("prepare", product_url, row.row_number, updates["status"], updates.get("error")))
            summary.changed += 1
        return summary

    def replenish(self, dry_run: bool = False) -> RunSummary:
        """残りネタが閾値以下なら、楽天ランキングから実在商品を取得してシートへ補充する。"""
        summary = RunSummary()
        cfg = self.config.replenish
        if not cfg.enabled or not cfg.ranking_urls:
            return summary
        table = self.sheet.read_table()
        remaining = count_pipeline_rows(table, self.config)
        if remaining > cfg.threshold:
            return summary
        existing_urls = collect_all_urls(table, self.config)
        existing_items = collect_items(table, self.config)
        added = 0
        with RakutenRoomBrowser(self.config.browser) as browser:
            for ranking_url in cfg.ranking_urls:
                if added >= cfg.batch:
                    break
                try:
                    items = browser.fetch_ranking_items(ranking_url, limit=cfg.batch * 4)
                except BrowserAutomationError as exc:
                    self.ledger.append(
                        LedgerEvent.create("replenish_error", ranking_url, None, self.config.statuses.error, short_error(exc))
                    )
                    summary.errors += 1
                    continue
                if not items:
                    # ページ構造変化などで0件抽出になった場合も静かに流さず記録する
                    self.ledger.append(
                        LedgerEvent.create(
                            "replenish_error",
                            ranking_url,
                            None,
                            self.config.statuses.error,
                            "ランキングページから商品を1件も取得できませんでした。ページ構造が変わった可能性があります。",
                        )
                    )
                    summary.errors += 1
                    continue
                for item in items:
                    if added >= cfg.batch:
                        break
                    product_url = item.get("url", "")
                    title = item.get("title", "")
                    if not product_url or product_url in existing_urls:
                        continue
                    if is_duplicate_product(product_url, title, existing_items):
                        continue
                    summary.seen += 1
                    description = build_description(title, added, max_chars=self.config.llm.max_chars)
                    if not dry_run:
                        self.sheet.append_row_fields(
                            table.header,
                            {
                                "product_url": product_url,
                                "description": description,
                                "status": self.config.statuses.unposted,
                            },
                        )
                        self.ledger.append(
                            LedgerEvent.create(
                                "replenish", product_url, None, self.config.statuses.unposted, f"ランキングから自動補充: {title[:60]}"
                            )
                        )
                    existing_urls.add(product_url)
                    existing_items.append((product_url, title))
                    added += 1
                    summary.changed += 1
        return summary

    def approve(self, limit: int | None = None, dry_run: bool = False) -> RunSummary:
        """承認待ち行を自動で承認済へ昇格する。事前チェックに落ちた行は要確認に落とす。"""
        summary = RunSummary()
        table = self.sheet.read_table()
        limit = limit or self.config.runtime.max_items_per_run
        rows = select_rows(table, self.config.sheet, {self.config.statuses.approval_pending}, limit)
        completed_urls = collect_completed_urls(table, self.config)
        # 投稿済み＋投稿待ちの商品と同一とみられるものは承認しない
        known_items = collect_items(
            table, self.config, {self.config.statuses.completed, self.config.statuses.approved}
        )
        for row in rows:
            summary.seen += 1
            product_url = row.get("product_url", self.config.sheet.columns)
            description = row.get("description", self.config.sheet.columns)
            if not description:
                updates = {
                    "status": self.config.statuses.needs_review,
                    "error": "紹介文が空のため自動承認できません。紹介文を入力してステータスを「承認待ち」に戻してください。",
                }
            elif product_url in completed_urls:
                updates = {
                    "status": self.config.statuses.needs_review,
                    "error": "同じ商品URLが既に完了済みのためスキップしました。",
                }
            elif is_duplicate_product(product_url, description, known_items):
                updates = {
                    "status": self.config.statuses.needs_review,
                    "error": DUPLICATE_PRODUCT_MESSAGE,
                }
            else:
                problem = check_product_url(product_url)
                if problem:
                    updates = {"status": self.config.statuses.needs_review, "error": problem}
                else:
                    updates = {"status": self.config.statuses.approved, "error": ""}
            if updates["status"] == self.config.statuses.approved:
                # 同一実行内の後続行との重複判定に使う
                known_items.append((product_url, description))
            if not dry_run:
                self.sheet.update_row_fields(row, updates)
                self.ledger.append(
                    LedgerEvent.create("approve", product_url, row.row_number, updates["status"], updates["error"] or None)
                )
            summary.changed += 1
            if updates["status"] == self.config.statuses.needs_review:
                summary.errors += 1
        return summary

    def run(self, limit: int | None = None, dry_run: bool = False) -> RunSummary:
        summary = RunSummary()
        table = self.sheet.read_table()
        limit = limit or self.config.runtime.max_items_per_run
        scan_limit = max(limit * 10, 10)
        rows = select_rows(table, self.config.sheet, self.config.statuses.run_candidates, scan_limit)
        if not rows:
            return summary
        completed_urls = collect_completed_urls(table, self.config)
        # 照合対象は完了行のみ。承認済同士の重複はapprove段階で防ぐ設計
        # （同一run内で投稿した分はループ内でcompleted_itemsに追加して照合する）
        completed_items = collect_items(table, self.config, {self.config.statuses.completed})

        with RakutenRoomBrowser(self.config.browser) as browser:
            for row in rows:
                if summary.posted >= limit:
                    break
                summary.seen += 1
                product_url = row.get("product_url", self.config.sheet.columns)
                description = row.get("description", self.config.sheet.columns)
                if product_url in completed_urls:
                    updates = {
                        "status": self.config.statuses.needs_review,
                        "error": "同じ商品URLが既に完了済みのためスキップしました。",
                    }
                    if not dry_run:
                        self.sheet.update_row_fields(row, updates)
                        self.ledger.append(
                            LedgerEvent.create(
                                "skipped", product_url, row.row_number, updates["status"], updates["error"]
                            )
                        )
                    summary.errors += 1
                    continue
                if is_duplicate_product(product_url, description, completed_items):
                    updates = {
                        "status": self.config.statuses.needs_review,
                        "error": DUPLICATE_PRODUCT_MESSAGE,
                    }
                    if not dry_run:
                        self.sheet.update_row_fields(row, updates)
                        self.ledger.append(
                            LedgerEvent.create(
                                "skipped", product_url, row.row_number, updates["status"], updates["error"]
                            )
                        )
                    summary.errors += 1
                    continue
                if not description:
                    updates = {"status": self.config.statuses.needs_review, "error": "説明文が空です。"}
                    if not dry_run:
                        self.sheet.update_row_fields(row, updates)
                    summary.errors += 1
                    continue
                if not dry_run:
                    attempts = parse_attempts(row.get("attempts", self.config.sheet.columns)) + 1
                    self.sheet.update_row_fields(
                        row,
                        {
                            "status": self.config.statuses.processing,
                            "error": "",
                            "attempts": str(attempts),
                        },
                    )
                    self.ledger.append(LedgerEvent.create("processing", product_url, row.row_number, self.config.statuses.processing))
                try:
                    result = browser.post_product(product_url, description, dry_run=dry_run)
                    if not dry_run:
                        self.sheet.update_row_fields(
                            row,
                            {
                                "status": self.config.statuses.completed,
                                "posted_at": now_jst_iso(),
                                "error": "",
                            },
                        )
                        self.ledger.append(LedgerEvent.create("posted", product_url, row.row_number, self.config.statuses.completed, result.message))
                    # dry-run中も追加する（同一実行内で同じURLを重複処理しないための判定用。シートは書き換えない）
                    completed_urls.add(product_url)
                    completed_items.append((product_url, description))
                    summary.posted += 1
                except Exception as exc:
                    message = short_error(exc)
                    if not dry_run:
                        self.sheet.update_row_fields(
                            row,
                            {
                                "status": self.config.statuses.error,
                                "error": message,
                            },
                        )
                        self.ledger.append(LedgerEvent.create("error", product_url, row.row_number, self.config.statuses.error, message))
                    summary.errors += 1
                    if isinstance(exc, LoginRequiredError) or SUBMIT_NOT_REFLECTED_PREFIX in message:
                        break
        return summary

    def check_session(self) -> str:
        with RakutenRoomBrowser(self.config.browser) as browser:
            result = browser.check_session()
        if not result.ok:
            raise BrowserAutomationError(result.message)
        return result.message
