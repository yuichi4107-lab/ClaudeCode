from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class LedgerEvent:
    event: str
    product_url: str
    row_number: int | None = None
    status: str | None = None
    message: str | None = None
    created_at: str = ""

    @classmethod
    def create(
        cls,
        event: str,
        product_url: str,
        row_number: int | None = None,
        status: str | None = None,
        message: str | None = None,
    ) -> "LedgerEvent":
        created_at = datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(timespec="seconds")
        return cls(event=event, product_url=product_url, row_number=row_number, status=status, message=message, created_at=created_at)


class Ledger:
    def __init__(self, path: Path):
        self.path = path

    def append(self, event: LedgerEvent) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(event), ensure_ascii=False) + "\n")
