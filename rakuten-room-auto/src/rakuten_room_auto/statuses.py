from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Statuses:
    unposted: str = "未投稿"
    approval_pending: str = "承認待ち"
    approved: str = "承認済"
    processing: str = "処理中"
    completed: str = "完了"
    needs_review: str = "要確認"
    error: str = "エラー"

    @property
    def prepare_candidates(self) -> set[str]:
        return {"", self.unposted}

    @property
    def run_candidates(self) -> set[str]:
        return {self.approved}

    @property
    def pipeline(self) -> set[str]:
        """今後投稿される見込みの「残りネタ」として数えるステータス。"""
        return {"", self.unposted, self.approval_pending, self.approved}

    @property
    def terminal(self) -> set[str]:
        return {self.completed}
