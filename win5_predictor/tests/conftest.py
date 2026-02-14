"""テスト用の共有フィクスチャ"""

import pytest
from pathlib import Path

# プロジェクトルートをパスに追加
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


@pytest.fixture
def sample_race_html():
    """レース結果ページのサンプルHTML"""
    return """
    <!DOCTYPE html>
    <html>
    <head><title>レース結果</title></head>
    <body>
        <h1 class="racedata">バレンタインステークス</h1>
        <div class="racedata">
            <p class="smalltxt">2026/02/15 東京競馬場</p>
            <p><span>芝右 2000m 良 晴</span></p>
        </div>
        <div class="RaceData02">10万円,80万円,50万円</div>
        <div class="RaceData02">3歳以上 定量</div>

        <table class="race_table_01">
            <tr>
                <td>1</td>
                <td><a href="/horse/123456/">ナスカ</a></td>
                <td>1</td>
                <td>1</td>
                <td>牡</td>
                <td>5</td>
                <td>58.0</td>
                <td><a href="/jockey/456/">武豊</a></td>
                <td><a href="/trainer/789/">平尾師</a></td>
                <td>1:59.8</td>
                <td>-</td>
                <td>38.1</td>
                <td>460</td>
                <td>-</td>
                <td>2.2</td>
                <td>1</td>
            </tr>
            <tr>
                <td>2</td>
                <td><a href="/horse/123457/">ウインテンダー</a></td>
                <td>2</td>
                <td>2</td>
                <td>牝</td>
                <td>4</td>
                <td>56.0</td>
                <td><a href="/jockey/457/">C.ルメール</a></td>
                <td><a href="/trainer/790/">尾形師</a></td>
                <td>2:00.1</td>
                <td>-0.3</td>
                <td>39.0</td>
                <td>472</td>
                <td>+4</td>
                <td>3.1</td>
                <td>2</td>
            </tr>
        </table>
    </body>
    </html>
    """


@pytest.fixture
def sample_race_list_html():
    """レース一覧ページのサンプルHTML"""
    return """
    <!DOCTYPE html>
    <html>
    <body>
        <div class="RaceList">
            <a href="/race/202602150105/">東京1R</a>
            <a href="/race/202602150205/">東京2R</a>
            <a href="/race/202602150811/">阪神8R Win5対象</a>
        </div>
    </body>
    </html>
    """


@pytest.fixture
def sample_win5_html():
    """Win5対象レースページのサンプルHTML"""
    return """
    <!DOCTYPE html>
    <html>
    <body>
        <div class="Win5Races">
            <p>2026/02/15 Win5対象レース</p>
            <span>東京8R: 202602150808</span>
            <span>中山8R: 202602150908</span>
            <span>阪神8R: 202602150208</span>
            <span>札幌8R: 202602150108</span>
            <span>福島8R: 202602150308</span>
        </div>
    </body>
    </html>
    """


@pytest.fixture
def in_memory_db():
    """メモリ内SQLiteデータベースフィクスチャ"""
    from database.connection import Database
    db = Database(db_path=":memory:")
    db.initialize()
    return db
