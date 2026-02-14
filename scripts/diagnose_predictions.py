#!/usr/bin/env python3
"""予測結果の診断: モデルが何を出力しているか確認"""

import pandas as pd
from datetime import datetime, timedelta

from nankan_predictor.storage.repository import Repository
from nankan_predictor.features.builder import FeatureBuilder
from nankan_predictor.model.predictor import ModelPredictor

def diagnose():
    repo = Repository()
    builder = FeatureBuilder(repo)
    predictor = ModelPredictor("nankan_v1")
    
    # 直近30日のレースを取得
    to_date = datetime.now().strftime("%Y-%m-%d")
    from_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    
    entries_df = repo.get_entries_in_range(from_date, to_date)
    print(f"Entries retrieved: {len(entries_df)} rows")
    
    if len(entries_df) == 0:
        print("No entries found!")
        return
    
    # 最初のレースをサンプルに診断
    first_race_id = entries_df.groupby("race_id").first().index[0]
    print(f"\nSampling race_id: {first_race_id}")
    
    race_data = entries_df[entries_df["race_id"] == first_race_id].to_dict("records")
    race_info = entries_df[entries_df["race_id"] == first_race_id].iloc[0].to_dict()
    
    print(f"Horses in race: {len(race_data)}")
    print(f"Horse numbers: {[h.get('horse_number') for h in race_data]}")
    
    # 特徴を構築
    X_race = builder.build_prediction_rows(first_race_id, race_data, race_info)
    print(f"\nFeatures shape: {X_race.shape}")
    print(f"Feature columns: {list(X_race.columns)[:10]}...")  # first 10
    print(f"NaN counts:\n{X_race.isna().sum().sum()} total NaNs")
    
    # 予測
    win_probs = predictor.predict_win_probs(X_race)
    place_probs = predictor.predict_place_probs(X_race)
    
    print(f"\nWin probabilities (top 3):")
    for i, prob in enumerate(sorted(enumerate(win_probs), key=lambda x: -x[1])[:3]):
        idx, p = prob
        horse_num = race_data[idx].get("horse_number")
        print(f"  Horse {horse_num}: {p:.4f}")
    
    print(f"\nPlace probabilities (top 3):")
    for i, prob in enumerate(sorted(enumerate(place_probs), key=lambda x: -x[1])[:3]):
        idx, p = prob
        horse_num = race_data[idx].get("horse_number")
        print(f"  Horse {horse_num}: {p:.4f}")
    
    # 全組み合わせ
    combos = predictor.predict_exacta(X_race, top_n=5)
    print(f"\nTop 5 Exacta combos:")
    print(combos)
    
    # 払戻金を確認
    top_combo = combos.iloc[0]
    first_num = int(top_combo["first_horse_number"])
    second_num = int(top_combo["second_horse_number"])
    payout = repo.get_exacta_payout(first_race_id, first_num, second_num)
    
    print(f"\nPayout for {first_num}-{second_num}: {payout}")
    
    # レースの実際の結果を回数で確認
    actual_entries = entries_df[entries_df["race_id"] == first_race_id]
    print(f"\nActual entry data (first 3):")
    print(actual_entries[["horse_number", "finish_position", "horse_name"]].head(3))

if __name__ == "__main__":
    diagnose()
