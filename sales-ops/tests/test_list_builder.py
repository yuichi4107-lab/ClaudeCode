from unittest.mock import MagicMock

import pytest

from core.db import Database, init_schema
from tracks.c_outbound.list_builder import ListBuilder, T2_SEARCH_QUERIES


@pytest.fixture
def db(tmp_db_path):
    d = Database(tmp_db_path)
    init_schema(d)
    return d


def _make_mock_places(places):
    """normalize 済みの place dict のリストを返す PlacesClient モック。"""
    client = MagicMock()
    client.search_text.return_value = places
    return client


def test_fetch_t2_inserts_new_companies(db):
    fake_places = [
        {
            "place_id": "pid_a",
            "name": "A税理士事務所",
            "website": "https://a-tax.example.com",
            "formatted_address": "東京都千代田区1-1",
            "types": ["accounting", "point_of_interest"],
        },
        {
            "place_id": "pid_b",
            "name": "B社労士事務所",
            "website": "https://b-sr.example.com",
            "formatted_address": "東京都新宿区2-2",
            "types": ["lawyer", "point_of_interest"],
        },
    ]
    builder = ListBuilder(db=db, places_client=_make_mock_places(fake_places))
    inserted = builder.fetch_t2(query="税理士 東京", location=(35.68, 139.76), max_results=10)

    assert inserted == 2
    with db.connect() as conn:
        rows = conn.execute("SELECT company_name, website_url, segment FROM companies").fetchall()
    assert len(rows) == 2
    assert {r["company_name"] for r in rows} == {"A税理士事務所", "B社労士事務所"}
    assert all(r["segment"] == "t2_pro_service" for r in rows)


def test_fetch_t2_skips_duplicates(db):
    fake_places = [
        {
            "place_id": "pid_a",
            "name": "A税理士事務所",
            "website": "https://a-tax.example.com",
            "formatted_address": "東京都",
            "types": ["accounting"],
        }
    ]
    builder = ListBuilder(db=db, places_client=_make_mock_places(fake_places))
    first = builder.fetch_t2(query="税理士", location=(35.68, 139.76), max_results=10)
    second = builder.fetch_t2(query="税理士", location=(35.68, 139.76), max_results=10)

    assert first == 1
    assert second == 0  # 重複スキップ


def test_fetch_t2_skips_without_website(db):
    fake_places = [
        {
            "place_id": "pid_a",
            "name": "HP無し事務所",
            "website": "",  # website 空
            "formatted_address": "東京都",
            "types": ["accounting"],
        }
    ]
    builder = ListBuilder(db=db, places_client=_make_mock_places(fake_places))
    assert builder.fetch_t2(query="税理士", location=(35.68, 139.76), max_results=10) == 0


def test_t2_search_queries_covers_core_segments():
    joined = " | ".join(T2_SEARCH_QUERIES)
    for must in ["税理士", "社労士", "行政書士", "司法書士", "デザイン", "ウェブ制作"]:
        assert must in joined


def test_places_api_new_client_normalize():
    """PlacesApiNewClient._normalize が期待通りの形式に変換する。"""
    from tracks.c_outbound.list_builder import PlacesApiNewClient

    raw = {
        "id": "places/CHIJxxx",
        "displayName": {"text": "山田税理士事務所", "languageCode": "ja"},
        "websiteUri": "https://yamada-tax.example.com",
        "formattedAddress": "東京都千代田区丸の内1-1",
        "types": ["accounting", "point_of_interest"],
    }
    normalized = PlacesApiNewClient._normalize(raw)
    assert normalized == {
        "place_id": "places/CHIJxxx",
        "name": "山田税理士事務所",
        "website": "https://yamada-tax.example.com",
        "formatted_address": "東京都千代田区丸の内1-1",
        "types": ["accounting", "point_of_interest"],
    }


def test_places_api_new_client_normalize_missing_fields():
    """必須フィールド欠落時も空文字にフォールバックする。"""
    from tracks.c_outbound.list_builder import PlacesApiNewClient

    normalized = PlacesApiNewClient._normalize({})
    assert normalized == {
        "place_id": "",
        "name": "",
        "website": "",
        "formatted_address": "",
        "types": [],
    }
