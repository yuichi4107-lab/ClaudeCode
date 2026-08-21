"""企業HPを読み取り、Claude APIでパーソナライズDM下書きを生成する。"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from core.approval_queue import ApprovalQueue
from core.db import Database

logger = logging.getLogger(__name__)


PROMPT_TEMPLATE = """あなたはBtoB向けのインサイドセールス専門コピーライターです。
以下の企業に対して、yn-tools（AI業務自動化ツール31種類、月2000円/ユーザー、{owner_website}）を提案するパーソナライズメールを1通作成してください。

送信者情報（以下を本文の署名にそのまま正確に使ってください。架空の名前や別のメールアドレスを創作しないでください）:
- 会社名: {owner_company}
- 役職: {owner_title}
- 氏名: {owner_name}
- 連絡先メール: {owner_contact_email}
- サービスURL: {owner_website}

企業情報:
- 会社名: {company_name}
- 業種: {industry}
- HP要約: {hp_summary}

制約:
1. 件名は30文字以内、相手の会社名を含める
2. 本文は400-600字、冒頭で相手HPから読み取った具体的要素を1つ触れる（パーソナライズ）
3. 自動化の具体的な業務例を業種に合わせて2-3個提示
4. 最後に14日間の無料トライアル案内と30分オンラインデモ提案
5. 署名は上記の送信者情報をそのまま使う。架空の氏名・部署・メールアドレスを一切創作しないこと
6. 配信停止手順を末尾に記載（「配信停止希望の場合は {owner_contact_email} へ返信」）
7. 絶対に {{}} プレースホルダや [xxx] を残さない、全て実文字で埋める
8. 過度にフォーマルすぎない、「はじめまして、〜と申します」程度の自然な日本語

JSON 形式で返答してください。他の文字を出力してはいけません:
{{
  "subject": "件名",
  "body": "本文（改行は \\n）",
  "personalization_hint": "HPから読み取った要素の要約30字"
}}
"""


PLACEHOLDER_PATTERNS = [
    re.compile(r"\{\{[^}]+\}\}"),
    re.compile(r"\[[A-Z_]+\]"),
    re.compile(r"<[a-z_]+>"),
]


def _strip_code_fence(text: str) -> str:
    """Claude のレスポンスが ```json ... ``` で囲まれている場合に中身だけ取り出す。"""
    text = text.strip()
    if not text.startswith("```"):
        return text
    lines = text.split("\n")
    if lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


class Personalizer:
    def __init__(
        self,
        db: Database,
        claude_client,
        hp_fetcher,
        *,
        model: str = "claude-opus-4-7",
        sender_info: dict[str, str] | None = None,
    ):
        self.db = db
        self.claude = claude_client
        self.hp_fetcher = hp_fetcher
        self.model = model
        # sender_info: owner_company/owner_title/owner_name/owner_contact_email/owner_website
        self.sender_info = sender_info or {
            "owner_company": "YNファクトリー",
            "owner_title": "代表",
            "owner_name": "オーナー",
            "owner_contact_email": "y-nakada@yn-factory.com",
            "owner_website": "https://tools.ynfactory.online",
        }
        self.queue = ApprovalQueue(db)

    def process_new_companies(self, *, batch_size: int = 50) -> int:
        companies = self._list_new_companies(limit=batch_size)
        processed = 0
        for c in companies:
            ok = self._process_one(c)
            self._update_status(c["id"], "drafted" if ok else "needs_retry")
            if ok:
                processed += 1
        return processed

    def _list_new_companies(self, *, limit: int) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM companies WHERE status = 'new' ORDER BY id ASC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def _process_one(self, company: dict[str, Any]) -> bool:
        hp_summary = ""
        if company.get("website_url"):
            try:
                hp_summary = self.hp_fetcher.fetch_summary(company["website_url"])
            except Exception as e:
                logger.warning("hp_fetcher failed for %s: %s", company["website_url"], e)

        prompt = PROMPT_TEMPLATE.format(
            company_name=company["company_name"],
            industry=company.get("industry") or "不明",
            hp_summary=hp_summary or "HPが取得できませんでした",
            **self.sender_info,
        )
        resp = self.claude.messages.create(
            model=self.model,
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text if resp.content else "{}"
        text = _strip_code_fence(text)
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning(
                "claude returned non-json for company %s: %r",
                company["id"], text[:200],
            )
            return False

        subject = data.get("subject", "")
        body = data.get("body", "")

        if self._has_unfilled_placeholders(subject) or self._has_unfilled_placeholders(body):
            logger.warning(
                "unfilled placeholders in draft for company %s: subject=%r",
                company["id"], subject,
            )
            return False

        # HP要約があれば companies テーブルにも保存
        if hp_summary:
            with self.db.connect() as conn:
                conn.execute(
                    "UPDATE companies SET hp_summary = ?, personalization_hints = ? WHERE id = ?",
                    (hp_summary[:2000], data.get("personalization_hint", ""), company["id"]),
                )

        self.queue.enqueue(
            track="c",
            item_type="dm",
            payload={
                "to_company_id": company["id"],
                "to_website": company["website_url"],
                "subject": subject,
                "body": body,
                "personalization_hint": data.get("personalization_hint", ""),
            },
        )
        return True

    def _update_status(self, company_id: int, status: str) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE companies SET status = ? WHERE id = ?", (status, company_id)
            )

    @staticmethod
    def _has_unfilled_placeholders(text: str) -> bool:
        return any(p.search(text) for p in PLACEHOLDER_PATTERNS)
