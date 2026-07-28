"""cron: 毎日03:00 に実行。T2セグメントの企業リストを取得する。

Places API (New) の REST 直叩きで 3地域 x 10業種 の検索を実行する。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dotenv import load_dotenv

from core.config import Config
from core.db import Database
from tracks.c_outbound.list_builder import (
    ListBuilder,
    PlacesApiNewClient,
    T2_SEARCH_QUERIES,
)


# 東京・大阪・名古屋の中心座標（半径5kmで検索）
TARGET_LOCATIONS = [
    ("東京", (35.6812, 139.7671)),
    ("大阪", (34.6937, 135.5023)),
    ("名古屋", (35.1815, 136.9066)),
]


def main() -> int:
    load_dotenv()
    cfg = Config.load()
    db = Database(cfg.db_path)
    places = PlacesApiNewClient(api_key=cfg.google_maps_api_key)
    builder = ListBuilder(db=db, places_client=places)

    total = 0
    for region_name, loc in TARGET_LOCATIONS:
        for q in T2_SEARCH_QUERIES:
            n = builder.fetch_t2(
                query=f"{q} {region_name}", location=loc, max_results=5
            )
            total += n
    print(f"[OK] fetched {total} new T2 companies")
    return 0


if __name__ == "__main__":
    sys.exit(main())
