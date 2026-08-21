"""ペース指数・脚質分類モジュール"""

import re
import statistics
from typing import Dict, List, Optional

from src.utils.constants import RUNNING_STYLES
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class PaceIndexCalculator:
    """ペース指数の算出と脚質分類を行う"""

    def compute_pace_index(
        self,
        corner_positions_str: Optional[str],
        finish_time: Optional[float],
        final_3f: Optional[float],
    ) -> Optional[float]:
        """ペース指数を算出する。

        前半の走行比率を算出:
        pace_index = (finish_time - final_3f) / finish_time * 100

        高い値 = 前半に速く走っている (ハイペース)
        """
        if finish_time is None or final_3f is None:
            return None
        if finish_time <= 0 or final_3f <= 0:
            return None
        if final_3f >= finish_time:
            return None
        return (finish_time - final_3f) / finish_time * 100.0

    @staticmethod
    def parse_corner_positions(corner_positions_str: Optional[str]) -> List[int]:
        """コーナー通過順位文字列をパースしてリストにする。

        例: "5-5-3-2" -> [5, 5, 3, 2]
        """
        if not corner_positions_str:
            return []
        positions = []
        for part in re.split(r"[-,]", corner_positions_str.strip()):
            part = part.strip()
            # 括弧付き表記 "5(6)" のような場合は最初の数字を使う
            match = re.match(r"(\d+)", part)
            if match:
                positions.append(int(match.group(1)))
        return positions

    def classify_running_style(
        self, corner_positions_list: List[int]
    ) -> int:
        """コーナー通過順位から脚質を分類する。

        4コーナー (最後のコーナー) の位置を基準にする。
        avg <= 3: 逃げ(1), avg <= 6: 先行(2), avg <= 10: 差し(3), else: 追込(4)
        """
        if not corner_positions_list:
            return RUNNING_STYLES["差し"]  # デフォルト

        # 最終コーナー (最後の要素) を使用
        last_corner = corner_positions_list[-1]

        if last_corner <= 3:
            return RUNNING_STYLES["逃げ"]
        elif last_corner <= 6:
            return RUNNING_STYLES["先行"]
        elif last_corner <= 10:
            return RUNNING_STYLES["差し"]
        else:
            return RUNNING_STYLES["追込"]

    def compute_features(
        self, horse_id: str, before_date: str, db_manager=None
    ) -> Dict[str, Optional[float]]:
        """ペース指数関連の特徴量を算出する。

        Returns:
            pace_index_last3: 直近3レースの平均ペース指数
            running_style: 脚質分類コード (直近3レースの最頻値)
        """
        result: Dict[str, Optional[float]] = {
            "pace_index_last3": None,
            "running_style": None,
        }

        if db_manager is None:
            return result

        sql = """
            SELECT rr.corner_positions, rr.finish_time, rr.final_3f
            FROM race_results rr
            JOIN races r ON rr.race_id = r.race_id
            WHERE rr.horse_id = ?
              AND r.race_date < ?
              AND rr.finish_time IS NOT NULL
            ORDER BY r.race_date DESC
            LIMIT 5
        """
        with db_manager._connect() as conn:
            rows = conn.execute(sql, (horse_id, before_date)).fetchall()

        if not rows:
            return result

        pace_indices = []
        styles = []

        for row in rows:
            pi = self.compute_pace_index(
                row["corner_positions"], row["finish_time"], row["final_3f"]
            )
            if pi is not None:
                pace_indices.append(pi)

            positions = self.parse_corner_positions(row["corner_positions"])
            if positions:
                styles.append(self.classify_running_style(positions))

        if pace_indices:
            last3 = pace_indices[:3]
            result["pace_index_last3"] = sum(last3) / len(last3)

        if styles:
            # 最頻値を採用
            result["running_style"] = float(max(set(styles), key=styles.count))

        return result
