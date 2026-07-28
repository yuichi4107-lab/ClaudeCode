"""指定company_id 1社だけ personalizer を再実行（ワンショット）。

使い方:
    SALES_OPS_DB_PATH=/opt/sales-ops/data/sales_ops.db \
    ./venv/bin/python scripts/retry_single.py <company_id>
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import anthropic
from dotenv import load_dotenv

from core.config import Config
from core.db import Database
from tracks.c_outbound.personalizer import Personalizer

# personalizer の logger.warning を可視化
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: retry_single.py <company_id>", file=sys.stderr)
        return 2
    target_id = int(sys.argv[1])

    load_dotenv()
    cfg = Config.load()
    db = Database(cfg.db_path)

    # run_personalizer.py と同じ SimpleHPFetcher
    import requests
    from bs4 import BeautifulSoup

    class SimpleHPFetcher:
        def fetch_summary(self, url: str) -> str:
            try:
                r = requests.get(
                    url, timeout=10,
                    headers={"User-Agent": "Mozilla/5.0 SalesOps/1.0"},
                )
                r.raise_for_status()
                soup = BeautifulSoup(r.text, "html.parser")
                title = soup.title.get_text(strip=True) if soup.title else ""
                desc_tag = soup.find("meta", attrs={"name": "description"})
                desc = desc_tag.get("content", "") if desc_tag else ""
                body = soup.get_text(" ", strip=True)[:400] if soup.body else ""
                return f"{title} / {desc} / {body}".strip()
            except Exception:
                return ""

    claude = anthropic.Anthropic(api_key=cfg.anthropic_api_key)
    sender_info = {
        "owner_company": cfg.owner_company,
        "owner_title": cfg.owner_title,
        "owner_name": cfg.owner_name,
        "owner_contact_email": cfg.owner_contact_email,
        "owner_website": cfg.owner_website,
    }
    personalizer = Personalizer(
        db=db, claude_client=claude, hp_fetcher=SimpleHPFetcher(),
        sender_info=sender_info,
    )

    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM companies WHERE id = ?", (target_id,)
        ).fetchone()
    if row is None:
        print(f"company_id={target_id} not found", file=sys.stderr)
        return 1
    company = dict(row)

    # まず status を new に戻す
    with db.connect() as conn:
        conn.execute(
            "UPDATE companies SET status = 'new' WHERE id = ?", (target_id,)
        )

    print(f"[INFO] processing company_id={target_id} name={company.get('company_name')!r}")
    ok = personalizer._process_one(company)
    personalizer._update_status(target_id, "drafted" if ok else "needs_retry")
    print(f"[RESULT] ok={ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
