import logging
from collections import defaultdict
from datetime import datetime

import numpy as np
import pandas as pd

from jra_predictor.storage.repository import Repository
from jra_predictor.config.settings import (
    VENUE_CODES,
    TRACK_CONDITION_ENC,
    TRACK_TYPE_ENC,
    COURSE_DIRECTION_ENC,
    RACE_CLASS_ENC,
)

logger = logging.getLogger(__name__)

NUMERIC_FEATURES = [
    # 馬の過去成績 (20)
    "horse_last1_finish",
    "horse_last3_avg_finish",
    "horse_last5_win_rate",
    "horse_last5_top3_rate",
    "horse_career_win_rate",
    "horse_days_since_last",
    "horse_same_venue_win_rate",
    "horse_same_dist_win_rate",
    "horse_same_track_type_win_rate",
    "horse_speed_index_last1",
    "horse_speed_index_last3",
    "horse_weight_change",
    "horse_avg_last3f",
    "horse_last1_popularity",
    "horse_momentum",
    "horse_career_top3_rate",
    "horse_running_style",         # 走法 (逃げ=0,先行=1,差し=2,追込=3)
    "horse_avg_corner_pos_ratio",  # 平均コーナー通過順位 / 出走頭数
    "horse_win_streak",            # 連勝数
    "horse_class_win_rate",        # 同クラスでの勝率
    # 騎手 (4)
    "jockey_win_rate_overall",
    "jockey_win_rate_venue",
    "jockey_top3_rate_overall",
    "jockey_horse_pair_wins",
    # 調教師 (2)
    "trainer_win_rate",            # 調教師勝率
    "trainer_top3_rate",           # 調教師3着以内率
    # レース情報 (9)
    "field_size",
    "distance",
    "venue_enc",
    "track_type_enc",
    "track_cond_enc",
    "course_direction_enc",
    "race_number",
    "race_class_enc",              # レースクラス (未勝利=1〜オープン=5)
    "race_month",                  # レース月 (1-12)
    # 出走馬情報 (10)
    "gate_number",
    "horse_number",
    "weight_carried",
    "horse_weight",
    "popularity_rank",
    "horse_age",
    "horse_sex_enc",
    "win_odds",                    # 単勝オッズ
    "relative_gate_position",      # 相対枠順 (gate/field_size)
    "weight_per_kg",               # 馬体重あたり斤量比
]

_VENUE_VALUES = list(VENUE_CODES.values())


def _speed_index_vals(distance, finish_time) -> float:
    if distance and finish_time and finish_time > 0:
        return distance / finish_time
    return np.nan


def _parse_first_corner(passing: str) -> int | None:
    """通過順位文字列 "1-2-3-4" から第1コーナー通過順位を返す。"""
    if not passing:
        return None
    import re
    nums = re.findall(r"\d+", str(passing))
    if nums:
        return int(nums[0])
    return None


def _days_between(date_a: str, date_b: str) -> float:
    try:
        da = datetime.strptime(date_a[:10], "%Y-%m-%d")
        db = datetime.strptime(date_b[:10], "%Y-%m-%d")
        return (da - db).days
    except Exception:
        return np.nan


class FeatureBuilder:
    """
    race_entries + horse_history_cache + jockeys を結合して
    scikit-learn 用の特徴量 DataFrame を生成する。

    重要: 特徴量生成時は必ず対象レース日付より前のデータのみ使用する
    （未来情報の混入防止）。
    """

    def __init__(self, repo: Repository):
        self.repo = repo
        self._horse_hist_dict = None  # horse_id -> list of tuples
        self._jockey_overall_dict = None  # jockey_id -> list of (race_date, finish_pos)
        self._jockey_venue_dict = None  # (jockey_id, venue_code) -> list of (race_date, finish_pos)
        self._trainer_dict = None  # trainer_name -> list of (race_date, finish_pos)
        self._horse_passing_dict = None  # horse_id -> list of (race_date, first_corner_pos, field_size)

    # ------------------------------------------------------------------ public

    def build_training_set(
        self, from_date: str, to_date: str, target: str = "win",
        exclude_classes: list[str] | None = None,
    ) -> tuple[pd.DataFrame, pd.Series]:
        """
        Returns (X, y):
          X: 特徴量行列（1行=1出走）
          y: ラベル。target="win" -> 1着, "place" -> 2着, "top3" -> 3着以内
        """
        entries_df = self.repo.get_entries_in_range(from_date, to_date, exclude_classes=exclude_classes)
        logger.info(
            "Building features for %d entries (%s ~ %s) target=%s",
            len(entries_df), from_date, to_date, target,
        )

        self._preload_data()

        feature_rows = []
        try:
            from tqdm import tqdm
            iterator = tqdm(entries_df.iterrows(), total=len(entries_df), desc="Features")
        except ImportError:
            iterator = entries_df.iterrows()
        for _, entry in iterator:
            row = self._build_row(entry)
            feature_rows.append(row)

        self._horse_hist_dict = None
        self._jockey_overall_dict = None
        self._jockey_venue_dict = None
        self._jockey_horse_dict = None
        self._horse_last3f_dict = None
        self._trainer_dict = None
        self._horse_passing_dict = None
        self._race_class_dict = None

        df = pd.DataFrame(feature_rows)
        drop_labels = {"is_winner", "is_second", "is_top3"}
        if target == "top3":
            y = df.pop("is_top3").astype(int)
            drop_labels.discard("is_top3")
        elif target == "place":
            y = df.pop("is_second").astype(int)
            drop_labels.discard("is_second")
        else:
            y = df.pop("is_winner").astype(int)
            drop_labels.discard("is_winner")
        for col in drop_labels:
            if col in df.columns:
                df.drop(columns=[col], inplace=True)
        X = df[NUMERIC_FEATURES]

        missing_rate = X.isna().mean()
        threshold = 0.8
        drop_cols = missing_rate[missing_rate > threshold].index.tolist()
        if drop_cols:
            logger.info("Dropping features with missing rate > %.2f: %s", threshold, drop_cols)
            X = X.drop(columns=drop_cols)

        return X, y

    def build_prediction_rows(
        self, race_id: str, entries: list[dict], race_info: dict
    ) -> pd.DataFrame:
        rows = []
        for entry in entries:
            entry_series = pd.Series({**entry, **race_info})
            row = self._build_row(entry_series)
            row["horse_number"] = entry.get("horse_number")
            row["horse_name"] = entry.get("horse_name")
            rows.append(row)

        df = pd.DataFrame(rows)
        for col in NUMERIC_FEATURES:
            if col not in df.columns:
                df[col] = np.nan
        return df

    def ensure_preloaded(self):
        """評価時など、外部から明示的にプリロードを呼ぶ。"""
        if self._horse_hist_dict is None:
            self._preload_data()

    # --------------------------------------------------------------- private

    def _preload_data(self):
        """全馬の過去成績と騎手成績を辞書にプリロード。"""
        logger.info("Preloading data into memory...")
        conn = self.repo._conn()

        # 馬の過去成績をhorse_id別の辞書に格納
        cursor = conn.execute(
            """SELECT horse_id, race_date, venue_name, distance,
                      track_type, finish_position, finish_time,
                      popularity_rank, field_size
               FROM horse_history_cache
               ORDER BY horse_id, race_date DESC"""
        )
        self._horse_hist_dict = defaultdict(list)
        count = 0
        for row in cursor:
            self._horse_hist_dict[row[0]].append({
                "race_date": row[1], "venue_name": row[2],
                "distance": row[3], "track_type": row[4],
                "finish_position": row[5], "finish_time": row[6],
                "popularity_rank": row[7], "field_size": row[8],
            })
            count += 1
        logger.info("  Horse history: %d records, %d horses", count, len(self._horse_hist_dict))

        # 騎手成績をjockey_id別の辞書に格納
        cursor = conn.execute(
            """SELECT e.jockey_id, r.race_date, e.finish_position, r.venue_code
               FROM race_entries e
               JOIN races r ON e.race_id = r.race_id
               WHERE e.finish_position IS NOT NULL
               ORDER BY e.jockey_id, r.race_date"""
        )
        self._jockey_overall_dict = defaultdict(list)
        self._jockey_venue_dict = defaultdict(list)
        count = 0
        for row in cursor:
            jid, rdate, fpos, vc = row
            self._jockey_overall_dict[jid].append((rdate, fpos))
            self._jockey_venue_dict[(jid, vc)].append((rdate, fpos))
            count += 1
        logger.info("  Jockey stats: %d records, %d jockeys", count, len(self._jockey_overall_dict))

        # 騎手-馬ペアの成績を辞書に格納
        cursor = conn.execute(
            """SELECT e.jockey_id, e.horse_id, r.race_date, e.finish_position
               FROM race_entries e
               JOIN races r ON e.race_id = r.race_id
               WHERE e.finish_position IS NOT NULL AND e.horse_id IS NOT NULL
               ORDER BY r.race_date"""
        )
        self._jockey_horse_dict = defaultdict(list)
        for row in cursor:
            jid, hid, rdate, fpos = row
            self._jockey_horse_dict[(jid, hid)].append((rdate, fpos))

        # 上がり3F辞書 (horse_id -> list of (race_date, last_3f_time))
        cursor = conn.execute(
            """SELECT e.horse_id, r.race_date, e.last_3f_time
               FROM race_entries e
               JOIN races r ON e.race_id = r.race_id
               WHERE e.last_3f_time IS NOT NULL AND e.horse_id IS NOT NULL
               ORDER BY e.horse_id, r.race_date DESC"""
        )
        self._horse_last3f_dict = defaultdict(list)
        for row in cursor:
            self._horse_last3f_dict[row[0]].append((row[1], row[2]))

        # 調教師成績辞書 (trainer_name -> list of (race_date, finish_pos))
        cursor = conn.execute(
            """SELECT e.trainer_name, r.race_date, e.finish_position
               FROM race_entries e
               JOIN races r ON e.race_id = r.race_id
               WHERE e.finish_position IS NOT NULL AND e.trainer_name IS NOT NULL
               ORDER BY e.trainer_name, r.race_date"""
        )
        self._trainer_dict = defaultdict(list)
        count = 0
        for row in cursor:
            self._trainer_dict[row[0]].append((row[1], row[2]))
            count += 1
        logger.info("  Trainer stats: %d records, %d trainers", count, len(self._trainer_dict))

        # 通過順位辞書 (horse_id -> list of (race_date, first_corner_pos, field_size))
        cursor = conn.execute(
            """SELECT e.horse_id, r.race_date, e.passing_positions, r.field_size
               FROM race_entries e
               JOIN races r ON e.race_id = r.race_id
               WHERE e.passing_positions IS NOT NULL AND e.horse_id IS NOT NULL
               ORDER BY e.horse_id, r.race_date DESC"""
        )
        self._horse_passing_dict = defaultdict(list)
        for row in cursor:
            # passing_positions: "1-1-1-1" or "2-3-4-5" etc.
            first_pos = _parse_first_corner(row[2])
            if first_pos is not None:
                self._horse_passing_dict[row[0]].append((row[1], first_pos, row[3]))

        # レースクラス辞書 (race_id -> race_class) via horse_history用
        cursor = conn.execute(
            """SELECT r.race_id, r.race_class
               FROM races r
               WHERE r.race_class IS NOT NULL AND r.race_class != ''"""
        )
        self._race_class_dict = {}
        for row in cursor:
            self._race_class_dict[row[0]] = row[1]

        conn.close()

    def _build_row(self, entry: pd.Series) -> dict:
        row = {}
        row.update(self._horse_features(entry))
        row.update(self._jockey_features(entry))
        row.update(self._trainer_features(entry))
        row.update(self._race_features(entry))
        row.update(self._entry_features(entry))
        row["is_winner"] = entry.get("is_winner")
        pos = entry.get("finish_position")
        row["is_second"] = 1 if pos == 2 else (0 if pos is not None else None)
        row["is_top3"] = 1 if (pos is not None and pos <= 3) else (0 if pos is not None else None)
        return row

    def _horse_features(self, entry: pd.Series) -> dict:
        horse_id = entry.get("horse_id")
        race_date = str(entry.get("race_date", ""))
        venue_name = entry.get("venue_name", "")
        distance = entry.get("distance")
        track_type = entry.get("track_type", "")

        null_feats = {
            "horse_last1_finish": np.nan,
            "horse_last3_avg_finish": np.nan,
            "horse_last5_win_rate": np.nan,
            "horse_last5_top3_rate": np.nan,
            "horse_career_win_rate": np.nan,
            "horse_career_top3_rate": np.nan,
            "horse_days_since_last": np.nan,
            "horse_same_venue_win_rate": np.nan,
            "horse_same_dist_win_rate": np.nan,
            "horse_same_track_type_win_rate": np.nan,
            "horse_speed_index_last1": np.nan,
            "horse_speed_index_last3": np.nan,
            "horse_weight_change": entry.get("weight_change", np.nan),
            "horse_avg_last3f": np.nan,
            "horse_last1_popularity": np.nan,
            "horse_momentum": np.nan,
            "horse_running_style": np.nan,
            "horse_avg_corner_pos_ratio": np.nan,
            "horse_win_streak": np.nan,
            "horse_class_win_rate": np.nan,
        }

        if not horse_id or not race_date:
            return null_feats

        # 辞書からO(1)で取得してフィルタ
        if self._horse_hist_dict is not None:
            all_hist = self._horse_hist_dict.get(horse_id, [])
            # already sorted by race_date DESC, filter before_date
            history = [h for h in all_hist if h["race_date"] < race_date][:20]
        else:
            hist_df = self.repo.get_horse_history(horse_id, before_date=race_date, limit=20)
            if hist_df.empty:
                return null_feats
            history = hist_df.to_dict("records")

        if not history:
            return null_feats

        last1 = history[0]
        last3 = history[:3]
        last5 = history[:5]

        # 着順リスト
        all_pos = [h["finish_position"] for h in history if h["finish_position"] is not None]
        l3_pos = [h["finish_position"] for h in last3 if h["finish_position"] is not None]
        l5_pos = [h["finish_position"] for h in last5 if h["finish_position"] is not None]

        # 同会場
        sv_pos = [h["finish_position"] for h in history
                   if h["venue_name"] == venue_name and h["finish_position"] is not None]

        # 同距離（±100m）
        if distance:
            sd_pos = [h["finish_position"] for h in history
                       if h["distance"] is not None and abs(h["distance"] - distance) <= 100
                       and h["finish_position"] is not None]
        else:
            sd_pos = []

        # 同コース種別
        if track_type:
            st_pos = [h["finish_position"] for h in history
                       if h["track_type"] == track_type and h["finish_position"] is not None]
        else:
            st_pos = []

        # スピード指数
        si_last1 = _speed_index_vals(last1.get("distance"), last1.get("finish_time"))
        si_last3 = [_speed_index_vals(h.get("distance"), h.get("finish_time")) for h in last3]
        si_last3_valid = [s for s in si_last3 if not np.isnan(s)]

        # 上がり3F (race_entries の last_3f_time から)
        avg_last3f = np.nan
        if self._horse_last3f_dict is not None:
            l3f_records = self._horse_last3f_dict.get(horse_id, [])
            l3f_vals = [t for d, t in l3f_records if d < race_date][:3]
            if l3f_vals:
                avg_last3f = np.mean(l3f_vals)

        # 前走人気
        last1_pop = last1.get("popularity_rank")

        # モメンタム（直近3走の着順改善度: 負=改善中, 正=悪化中）
        momentum = np.nan
        if len(l3_pos) >= 2:
            # 最新から古い順に着順差の平均: 古い→新しいで着順が下がっていればマイナス
            diffs = [l3_pos[i] - l3_pos[i + 1] for i in range(len(l3_pos) - 1)]
            momentum = np.mean(diffs)

        # 走法・通過順位（辞書から取得）
        running_style = np.nan
        avg_corner_pos_ratio = np.nan
        if self._horse_passing_dict is not None and horse_id:
            pass_records = self._horse_passing_dict.get(horse_id, [])
            pass_before = [(pos, fs) for d, pos, fs in pass_records if d < race_date][:5]
            if pass_before:
                ratios = [pos / max(fs, 1) for pos, fs in pass_before]
                avg_corner_pos_ratio = np.mean(ratios)
                # 走法分類: ratio <= 0.2: 逃げ(0), <= 0.4: 先行(1), <= 0.7: 差し(2), >0.7: 追込(3)
                avg_r = avg_corner_pos_ratio
                if avg_r <= 0.2:
                    running_style = 0
                elif avg_r <= 0.4:
                    running_style = 1
                elif avg_r <= 0.7:
                    running_style = 2
                else:
                    running_style = 3

        # 連勝数
        win_streak = 0
        for p in all_pos:
            if p == 1:
                win_streak += 1
            else:
                break

        # 同クラスでの勝率
        race_class = entry.get("race_class", "")
        class_win_rate = np.nan
        if race_class and history:
            # horse_history_cache にはrace_classがないので、race_nameからクラスを推定
            # 簡易的に: 過去と同等クラスでの成績を使う
            class_pos = all_pos  # フォールバック: 全成績
            if class_pos:
                class_win_rate = sum(1 for p in class_pos if p == 1) / len(class_pos)

        return {
            "horse_last1_finish": last1["finish_position"],
            "horse_last3_avg_finish": np.mean(l3_pos) if l3_pos else np.nan,
            "horse_last5_win_rate": sum(1 for p in l5_pos if p == 1) / len(l5_pos) if l5_pos else np.nan,
            "horse_last5_top3_rate": sum(1 for p in l5_pos if p <= 3) / len(l5_pos) if l5_pos else np.nan,
            "horse_career_win_rate": sum(1 for p in all_pos if p == 1) / len(all_pos) if all_pos else np.nan,
            "horse_career_top3_rate": sum(1 for p in all_pos if p <= 3) / len(all_pos) if all_pos else np.nan,
            "horse_days_since_last": _days_between(race_date, str(last1["race_date"])),
            "horse_same_venue_win_rate": (
                sum(1 for p in sv_pos if p == 1) / len(sv_pos) if sv_pos else np.nan
            ),
            "horse_same_dist_win_rate": (
                sum(1 for p in sd_pos if p == 1) / len(sd_pos) if sd_pos else np.nan
            ),
            "horse_same_track_type_win_rate": (
                sum(1 for p in st_pos if p == 1) / len(st_pos) if st_pos else np.nan
            ),
            "horse_speed_index_last1": si_last1,
            "horse_speed_index_last3": np.mean(si_last3_valid) if si_last3_valid else np.nan,
            "horse_weight_change": entry.get("weight_change", np.nan),
            "horse_avg_last3f": avg_last3f,
            "horse_last1_popularity": last1_pop,
            "horse_momentum": momentum,
            "horse_running_style": running_style,
            "horse_avg_corner_pos_ratio": avg_corner_pos_ratio,
            "horse_win_streak": win_streak,
            "horse_class_win_rate": class_win_rate,
        }

    def _jockey_features(self, entry: pd.Series) -> dict:
        jockey_id = entry.get("jockey_id")
        horse_id = entry.get("horse_id")
        race_date = str(entry.get("race_date", ""))
        venue_code = entry.get("venue_code")

        null_feats = {
            "jockey_win_rate_overall": np.nan,
            "jockey_win_rate_venue": np.nan,
            "jockey_top3_rate_overall": np.nan,
            "jockey_horse_pair_wins": np.nan,
        }

        if not jockey_id or not race_date:
            return null_feats

        # 辞書から取得してフィルタ
        if self._jockey_overall_dict is not None:
            overall = [(d, p) for d, p in self._jockey_overall_dict.get(jockey_id, []) if d < race_date]
            venue_stats = [(d, p) for d, p in self._jockey_venue_dict.get((jockey_id, venue_code), []) if d < race_date]
        else:
            overall_df = self.repo.get_jockey_stats(jockey_id, before_date=race_date)
            venue_df = self.repo.get_jockey_stats(jockey_id, before_date=race_date, venue_code=venue_code)
            overall = list(zip([""] * len(overall_df), overall_df["finish_position"].tolist())) if len(overall_df) > 0 else []
            venue_stats = list(zip([""] * len(venue_df), venue_df["finish_position"].tolist())) if len(venue_df) > 0 else []

        overall_win_rate = (
            sum(1 for _, p in overall if p == 1) / len(overall)
            if overall else np.nan
        )
        venue_win_rate = (
            sum(1 for _, p in venue_stats if p == 1) / len(venue_stats)
            if venue_stats else np.nan
        )
        top3_rate = (
            sum(1 for _, p in overall if p <= 3) / len(overall)
            if overall else np.nan
        )

        # 騎手-馬ペアの過去勝利数
        pair_wins = np.nan
        if self._jockey_horse_dict is not None and horse_id:
            pair_records = [(d, p) for d, p in self._jockey_horse_dict.get((jockey_id, horse_id), []) if d < race_date]
            if pair_records:
                pair_wins = sum(1 for _, p in pair_records if p == 1)

        return {
            "jockey_win_rate_overall": overall_win_rate,
            "jockey_win_rate_venue": venue_win_rate,
            "jockey_top3_rate_overall": top3_rate,
            "jockey_horse_pair_wins": pair_wins,
        }

    def _trainer_features(self, entry: pd.Series) -> dict:
        trainer_name = entry.get("trainer_name")
        race_date = str(entry.get("race_date", ""))

        null_feats = {
            "trainer_win_rate": np.nan,
            "trainer_top3_rate": np.nan,
        }

        if not trainer_name or not race_date:
            return null_feats

        if self._trainer_dict is not None:
            records = [(d, p) for d, p in self._trainer_dict.get(trainer_name, []) if d < race_date]
        else:
            return null_feats

        if not records:
            return null_feats

        wins = sum(1 for _, p in records if p == 1)
        top3 = sum(1 for _, p in records if p <= 3)
        total = len(records)

        return {
            "trainer_win_rate": wins / total,
            "trainer_top3_rate": top3 / total,
        }

    def _race_features(self, entry: pd.Series) -> dict:
        venue_code = entry.get("venue_code", "")
        venue_enc = _VENUE_VALUES.index(venue_code) if venue_code in _VENUE_VALUES else np.nan
        track_type = entry.get("track_type", "")
        track_cond = entry.get("track_condition", "")
        course_dir = entry.get("course_direction", "")
        race_class = entry.get("race_class", "")

        # レース月を抽出
        race_date = str(entry.get("race_date", ""))
        race_month = np.nan
        if len(race_date) >= 7:
            try:
                race_month = int(race_date[5:7])
            except (ValueError, TypeError):
                pass

        return {
            "field_size": entry.get("field_size", np.nan),
            "distance": entry.get("distance", np.nan),
            "venue_enc": venue_enc,
            "track_type_enc": TRACK_TYPE_ENC.get(track_type, np.nan),
            "track_cond_enc": TRACK_CONDITION_ENC.get(track_cond, np.nan),
            "course_direction_enc": COURSE_DIRECTION_ENC.get(course_dir, np.nan),
            "race_number": entry.get("race_number", np.nan),
            "race_class_enc": RACE_CLASS_ENC.get(race_class, np.nan),
            "race_month": race_month,
        }

    def _entry_features(self, entry: pd.Series) -> dict:
        sex = entry.get("horse_sex", "")
        sex_enc = {"牡": 0, "牝": 1, "セ": 2}.get(sex, np.nan)
        gate = entry.get("gate_number", np.nan)
        field_size = entry.get("field_size", np.nan)
        weight_carried = entry.get("weight_carried", np.nan)
        horse_weight = entry.get("horse_weight", np.nan)

        # 相対枠順 (0〜1: 内枠ほど小さい)
        rel_gate = np.nan
        if gate and field_size and field_size > 0:
            try:
                rel_gate = float(gate) / float(field_size)
            except (ValueError, TypeError):
                pass

        # 馬体重あたり斤量比
        w_per_kg = np.nan
        if weight_carried and horse_weight and horse_weight > 0:
            try:
                w_per_kg = float(weight_carried) / float(horse_weight)
            except (ValueError, TypeError):
                pass

        return {
            "gate_number": gate,
            "horse_number": entry.get("horse_number", np.nan),
            "weight_carried": weight_carried,
            "horse_weight": horse_weight,
            "popularity_rank": entry.get("popularity_rank", np.nan),
            "horse_age": entry.get("horse_age", np.nan),
            "horse_sex_enc": sex_enc,
            "win_odds": entry.get("win_odds", np.nan),
            "relative_gate_position": rel_gate,
            "weight_per_kg": w_per_kg,
        }
