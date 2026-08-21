"""Google Maps Places API (New) から T2 セグメント（士業・制作会社）のリストを取得する。

Legacy Places API が新規プロジェクトで有効化できないため、REST 直接叩きで Places API (New)
の Text Search エンドポイントを利用する。
"""
from __future__ import annotations

import logging
from typing import Iterable, Protocol

import requests

from core.db import Database

logger = logging.getLogger(__name__)


T2_SEARCH_QUERIES = [
    "税理士事務所",
    "社労士事務所",
    "行政書士事務所",
    "司法書士事務所",
    "弁護士事務所",
    "会計事務所",
    "ウェブ制作会社",
    "デザイン事務所",
    "広告代理店",
    "コンサルティング会社",
]


class PlacesClient(Protocol):
    """Places API (New) クライアント。テストでは MagicMock で差し替える。"""

    def search_text(
        self, *, query: str, location: tuple[float, float], radius_m: int
    ) -> list[dict]:
        ...


class PlacesApiNewClient:
    """Places API (New) の Text Search を叩く HTTP クライアント。"""

    ENDPOINT = "https://places.googleapis.com/v1/places:searchText"
    FIELD_MASK = (
        "places.id,places.displayName,places.websiteUri,"
        "places.formattedAddress,places.types"
    )

    def __init__(self, api_key: str, timeout: int = 15):
        self.api_key = api_key
        self.timeout = timeout

    def search_text(
        self, *, query: str, location: tuple[float, float], radius_m: int
    ) -> list[dict]:
        body = {
            "textQuery": query,
            "locationBias": {
                "circle": {
                    "center": {"latitude": location[0], "longitude": location[1]},
                    "radius": float(radius_m),
                }
            },
            "languageCode": "ja",
            "maxResultCount": 20,
        }
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": self.FIELD_MASK,
        }
        r = requests.post(self.ENDPOINT, json=body, headers=headers, timeout=self.timeout)
        r.raise_for_status()
        raw_places = r.json().get("places", [])
        return [self._normalize(p) for p in raw_places]

    @staticmethod
    def _normalize(p: dict) -> dict:
        return {
            "place_id": p.get("id", ""),
            "name": (p.get("displayName") or {}).get("text", ""),
            "website": p.get("websiteUri") or "",
            "formatted_address": p.get("formattedAddress", ""),
            "types": p.get("types", []),
        }


class ListBuilder:
    def __init__(self, db: Database, places_client: PlacesClient):
        self.db = db
        self.places = places_client

    def fetch_t2(
        self,
        *,
        query: str,
        location: tuple[float, float],
        max_results: int = 20,
        radius_m: int = 5000,
    ) -> int:
        """`query` で Places Text Search を行い、DB に新規登録した件数を返す。"""
        results = self.places.search_text(
            query=query, location=location, radius_m=radius_m
        )

        inserted = 0
        for place in results[:max_results]:
            website = place.get("website")
            if not website:
                continue
            if self._insert(
                name=place.get("name", ""),
                website=website,
                address=place.get("formatted_address", ""),
                industry=self._infer_industry(place.get("types", [])),
            ):
                inserted += 1
        logger.info(
            "fetch_t2: query=%s inserted=%d/%d", query, inserted, len(results)
        )
        return inserted

    def _insert(self, *, name: str, website: str, address: str, industry: str) -> bool:
        try:
            with self.db.connect() as conn:
                conn.execute(
                    "INSERT INTO companies (source, segment, company_name, website_url, "
                    "location, industry) VALUES ('google_maps', 't2_pro_service', ?, ?, ?, ?)",
                    (name, website, address, industry),
                )
            return True
        except Exception as e:
            if "UNIQUE" in str(e):
                return False
            raise

    @staticmethod
    def _infer_industry(types: Iterable[str]) -> str:
        types_set = set(types)
        if "lawyer" in types_set:
            return "lawyer"
        if "accounting" in types_set:
            return "accounting"
        return ",".join(sorted(types_set))[:200]
