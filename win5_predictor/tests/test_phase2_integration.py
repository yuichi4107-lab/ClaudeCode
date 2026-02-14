"""Phase 2 スクレイパーの統合テスト"""

import sys
from pathlib import Path

# プロジェクトパスを追加
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def test_imports():
    """各モジュールのインポートテスト"""
    print("\n=== Testing Module Imports ===")

    try:
        from config.settings import (
            NETKEIBA_BASE_URL,
            REQUEST_INTERVAL_SEC,
            DB_PATH,
        )

        print("✓ config.settings imported successfully")
        print(f"  NETKEIBA_BASE_URL: {NETKEIBA_BASE_URL}")
        print(f"  REQUEST_INTERVAL_SEC: {REQUEST_INTERVAL_SEC}")
        print(f"  DB_PATH: {DB_PATH}")
    except ImportError as e:
        print(f"✗ Failed to import config.settings: {e}")
        return False

    try:
        from database.connection import Database
        from database.models import Race, RaceResult

        print("✓ database modules imported successfully")
    except ImportError as e:
        print(f"✗ Failed to import database modules: {e}")
        return False

    try:
        from scraper.base import BaseScraper
        from scraper.race_list import RaceListScraper
        from scraper.race_result import RaceResultScraper
        from scraper.win5_target import Win5TargetScraper

        print("✓ scraper modules imported successfully")
    except ImportError as e:
        print(f"✗ Failed to import scraper modules: {e}")
        return False

    return True


def test_database_initialization():
    """データベース初期化テスト"""
    print("\n=== Testing Database Initialization ===")

    try:
        from database.connection import Database

        # メモリ内DBを使用してテスト
        db = Database(db_path=":memory:")
        db.initialize()
        db.run_migrations()

        conn = db.get_connection()
        cursor = conn.cursor()

        # テーブル一覧を取得
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [row[0] for row in cursor.fetchall()]

        print(f"✓ Database initialized. Found {len(tables)} tables:")
        for table in tables:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
            print(f"  - {table:20s} ({count} rows)")

        conn.close()
        return True

    except Exception as e:
        print(f"✗ Database initialization failed: {e}")
        return False


def test_base_scraper():
    """BaseScraper のテスト"""
    print("\n=== Testing BaseScraper ===")

    try:
        from scraper.base import BaseScraper

        scraper = BaseScraper(use_cache=False)
        print("✓ BaseScraper initialized")

        # parse テスト
        html = "<html><body><h1>Test</h1></body></html>"
        soup = scraper.parse(html)
        assert soup.h1 is not None
        assert soup.h1.string == "Test"
        print("✓ parse() works correctly")

        # キャッシュパス生成テスト
        cache_path = scraper._cache_path("https://example.com/test")
        assert cache_path.suffix == ".html"
        print("✓ _cache_path() works correctly")

        return True

    except Exception as e:
        print(f"✗ BaseScraper test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_race_result_scraper():
    """RaceResultScraper のテスト"""
    print("\n=== Testing RaceResultScraper ===")

    try:
        from scraper.race_result import RaceResultScraper
        from datetime import date

        scraper = RaceResultScraper(use_cache=False)
        print("✓ RaceResultScraper initialized")

        # サンプルHTMLでのパーステスト
        sample_html = """
        <html>
        <h1 class="racedata">東京スプリント</h1>
        <div class="racedata">
            <p class="smalltxt">2026/02/15 東京競馬場</p>
            <p><span>芝右 1200m 良 晴</span></p>
        </div>
        <div class="RaceData02">10万円,80万円</div>
        <div class="RaceData02">3歳以上 定量</div>
        <table class="race_table_01">
            <tr>
                <td>1</td><td>1</td><td>1</td>
                <td><a href="/horse/123456/">ナスカ</a></td>
                <td>牡4</td><td>58.0</td>
                <td><a href="/jockey/456/">武豊</a></td>
                <td>1:10.5</td><td>-</td><td></td><td></td>
                <td>38.1</td><td>2.2</td><td>1</td>
                <td></td><td></td><td></td>
                <td></td><td></td>
                <td><a href="/trainer/789/">平尾師</a></td>
            </tr>
        </table>
        </html>
        """

        soup = scraper.parse(sample_html)
        race = scraper._parse_race_info(soup, "202602150108")
        assert race is not None
        assert race.race_id == "202602150108"
        assert race.race_date == date(2026, 2, 15)
        assert race.distance == 1200
        print("✓ _parse_race_info() works correctly")

        results = scraper._parse_results_table(soup, "202602150108")
        assert len(results) > 0
        assert results[0].horse_name == "ナスカ"
        print("✓ _parse_results_table() works correctly")

        return True

    except Exception as e:
        print(f"✗ RaceResultScraper test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_venue_codes():
    """競馬場コード定義テスト"""
    print("\n=== Testing Venue Codes ===")

    try:
        from config.venues import VENUE_CODE

        print(f"✓ VENUE_CODE loaded. {len(VENUE_CODE)} venues:")
        for code, name in sorted(VENUE_CODE.items()):
            print(f"  {code}: {name}")

        return True

    except Exception as e:
        print(f"✗ Venue codes test failed: {e}")
        return False


def run_all_tests():
    """全テストを実行"""
    print("\n" + "=" * 60)
    print("Phase 2 Scraper Integration Tests")
    print("=" * 60)

    tests = [
        test_imports,
        test_database_initialization,
        test_base_scraper,
        test_race_result_scraper,
        test_venue_codes,
    ]

    results = []
    for test in tests:
        try:
            result = test()
            results.append((test.__name__, result))
        except Exception as e:
            print(f"\n✗ {test.__name__} crashed: {e}")
            import traceback

            traceback.print_exc()
            results.append((test.__name__, False))

    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {name}")

    passed = sum(1 for _, r in results if r)
    total = len(results)
    print(f"\nTotal: {passed}/{total} tests passed")

    return all(r for _, r in results)


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
