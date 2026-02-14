"""NAR スクレイパーデータを SQLite に保存するリポジトリ"""

import logging
import sqlite3
from datetime import datetime
from nankan_predictor.storage.database import get_connection

logger = logging.getLogger(__name__)


class NARRepository:
    """NAR データを DB に保存するクラス"""

    def __init__(self, db_path: str = None):
        self.db_path = db_path

    def save_race_and_entries(self, race_details: dict) -> None:
        """NAR から取得したレース詳細と出走馬情報を DB に保存"""
        
        conn = get_connection(self.db_path)
        try:
            # レース情報を保存
            race_id = race_details['race_id']
            conn.execute("""
                INSERT OR REPLACE INTO races 
                (race_id, venue_code, venue_name, race_date, race_number, race_name, field_size, scraped_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                race_id,
                race_details.get('venue_code'),
                race_details.get('venue_name'),
                race_details.get('race_date'),
                race_details.get('race_number'),
                race_details.get('race_name'),
                len(race_details.get('entries', [])),
                datetime.now().isoformat(),
            ))
            
            # 出走馬情報を保存
            for entry in race_details.get('entries', []):
                entry_id = f"{race_id}-{entry['horse_number']}"
                
                # 馬情報をマスタに登録
                if entry.get('horse_id'):
                    conn.execute("""
                        INSERT OR IGNORE INTO horses (horse_id, horse_name)
                        VALUES (?, ?)
                    """, (entry['horse_id'], entry.get('horse_name')))
                
                # 出走馬情報を登録
                conn.execute("""
                    INSERT OR REPLACE INTO race_entries
                    (entry_id, race_id, horse_id, jockey_id, horse_name, jockey_name, 
                     trainer_name, gate_number, horse_number, win_odds)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    entry_id,
                    race_id,
                    entry.get('horse_id'),
                    entry.get('jockey_id'),
                    entry.get('horse_name'),
                    entry.get('jockey'),
                    entry.get('trainer'),
                    entry.get('frame'),
                    entry.get('horse_number'),
                    None,  # win_odds は結果から取得するため、ここでは None
                ))
            
            conn.commit()
            logger.info(f"✅ レース {race_id} と {len(race_details.get('entries', []))} 出走馬を保存")
            
        except Exception as e:
            conn.rollback()
            logger.error(f"❌ データ保存エラー: {e}")
            raise
        finally:
            conn.close()

    def save_race_results(self, race_results: dict) -> None:
        """NAR から取得したレース結果を DB に保存"""
        
        conn = get_connection(self.db_path)
        try:
            race_id = race_results['race_id']
            
            # 結果情報を保存（race_entries のfinish_position, finish_time を更新）
            for result in race_results.get('results', []):
                entry_id = f"{race_id}-{result['horse_number']}"
                
                conn.execute("""
                    UPDATE race_entries
                    SET finish_position = ?,
                        finish_time = ?,
                        win_odds = ?
                    WHERE entry_id = ?
                """, (
                    result.get('finish_order'),
                    result.get('time'),
                    result.get('win_odds'),
                    entry_id,
                ))
            
            # 払戻情報を保存
            for payout_key, payout_amount in race_results.get('payouts', {}).items():
                # payout_key = "win_561" などの形式
                parts = payout_key.split('_')
                if len(parts) == 2:
                    bet_type, combination = parts
                    
                    # 金額をパースする（例："110円220円130円" -> 110）
                    payout_value = self._parse_payout(payout_amount)
                    
                    conn.execute("""
                        INSERT OR REPLACE INTO race_payouts
                        (race_id, bet_type, combination, payout)
                        VALUES (?, ?, ?, ?)
                    """, (
                        race_id,
                        bet_type,
                        combination,
                        payout_value,
                    ))
            
            conn.commit()
            logger.info(f"✅ レース {race_id} の結果 {len(race_results.get('results', []))} 件を保存")
            
        except Exception as e:
            conn.rollback()
            logger.error(f"❌ 結果保存エラー: {e}")
            raise
        finally:
            conn.close()

    def _parse_payout(self, payout_str: str) -> float:
        """払戻文字列から金額を抽出（例：'110円220円100円' -> 110）"""
        try:
            # 「円」で分割して最初の値を取得
            import re
            match = re.match(r'(\d+)', payout_str)
            if match:
                return float(match.group(1))
            return None
        except Exception:
            return None

    def check_race_exists(self, race_id: str) -> bool:
        """レースが既に DB に存在するか確認"""
        conn = get_connection(self.db_path)
        try:
            cursor = conn.execute("SELECT 1 FROM races WHERE race_id = ?", (race_id,))
            return cursor.fetchone() is not None
        finally:
            conn.close()

    def get_race_count(self) -> int:
        """DB に保存されているレース数を返す"""
        conn = get_connection(self.db_path)
        try:
            cursor = conn.execute("SELECT COUNT(*) FROM races")
            return cursor.fetchone()[0]
        finally:
            conn.close()
