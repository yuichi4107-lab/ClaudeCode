"""cron: 毎日03:30 に実行。new 企業のDM下書きを生成して approval_queue に投入する。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import anthropic
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from core.config import Config
from core.db import Database
from tracks.c_outbound.personalizer import Personalizer


class SimpleHPFetcher:
    """シンプルなHP要約: <title> + <meta description> + <body> 先頭400字"""

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


def main() -> int:
    load_dotenv()
    cfg = Config.load()
    db = Database(cfg.db_path)
    claude = anthropic.Anthropic(api_key=cfg.anthropic_api_key)
    sender_info = {
        "owner_company": cfg.owner_company,
        "owner_title": cfg.owner_title,
        "owner_name": cfg.owner_name,
        "owner_contact_email": cfg.owner_contact_email,
        "owner_website": cfg.owner_website,
    }
    personalizer = Personalizer(
        db=db,
        claude_client=claude,
        hp_fetcher=SimpleHPFetcher(),
        sender_info=sender_info,
    )
    processed = personalizer.process_new_companies(batch_size=50)
    print(f"[OK] drafted {processed} DMs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
