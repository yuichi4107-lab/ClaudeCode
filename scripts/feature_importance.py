#!/usr/bin/env python3
"""特徴重要度解析: モデルなが何を最も重視しているかを分析"""

import pandas as pd
import numpy as np
import joblib
from pathlib import Path


def analyze_feature_importance(model_name: str = "nankan_v1", target: str = "win"):
    """特徴重要度を解析してランク付けする"""
    
    # モデルを読み込む
    model_path = Path(f"data/models/{model_name}_{target}.joblib")
    if not model_path.exists():
        print(f"Error: Model not found at {model_path}")
        return
    
    model = joblib.load(model_path)
    
    # CalibratedClassifierCV から estimator を取得
    if hasattr(model, "estimator"):
        # CalibratedClassifierCV の場合
        pipeline = model.estimator
    else:
        pipeline = model
    
    # パイプラインから LGBMClassifier を取得
    if hasattr(pipeline, "named_steps"):
        # Pipeline の場合
        lgb_model = pipeline.named_steps.get("clf")
    elif hasattr(pipeline, "steps"):
        # 古い API の場合
        lgb_model = [step[1] for step in pipeline.steps if hasattr(step[1], "feature_importances_")]
        lgb_model = lgb_model[0] if lgb_model else None
    else:
        lgb_model = pipeline if hasattr(pipeline, "feature_importances_") else None
    
    if lgb_model is None or not hasattr(lgb_model, "feature_importances_"):
        print(f"Error: Unable to extract LGBMClassifier from model")
        return
    
    importances = lgb_model.feature_importances_
    feature_names = lgb_model.feature_names_in_
    
    # DataFrame に整形
    importance_df = pd.DataFrame({
        "feature": feature_names,
        "importance": importances,
    })
    importance_df = importance_df.sort_values("importance", ascending=False).reset_index(drop=True)
    importance_df["rank"] = range(1, len(importance_df) + 1)
    importance_df["cumsum"] = importance_df["importance"].cumsum()
    importance_df["cumsum_pct"] = (importance_df["cumsum"] / importance_df["importance"].sum()) * 100
    
    return importance_df


def main():
    print("=" * 80)
    print("特徴重要度解析")
    print("=" * 80)
    
    # 1着モデルの分析
    print("\n【1着モデル（Win）の特徴重要度】")
    win_importance = analyze_feature_importance("nankan_v1", "win")
    if win_importance is not None:
        print(f"\n上位20特徴:")
        print(win_importance.head(20).to_string(index=False))
        
        # 累積重要度80%に必要な特徴数
        top_80_idx = (win_importance["cumsum_pct"] <= 80).sum()
        print(f"\n累積重要度80%に必要な特徴数: {top_80_idx} / {len(win_importance)}")
        print(f"  (全体の {top_80_idx / len(win_importance) * 100:.1f}%)")
        
        # 低重要度特徴の確認
        low_importance_features = win_importance[win_importance["importance"] < win_importance["importance"].quantile(0.25)]
        print(f"\n低重要度特徴（下位25%）: {len(low_importance_features)} 個")
        if len(low_importance_features) > 0:
            print("  以下の特徴は削除候補:")
            print(f"    {', '.join(low_importance_features['feature'].head(10).tolist())}")
    
    # 2着モデルの分析
    print("\n" + "=" * 80)
    print("【2着モデル（Place）の特徴重要度】")
    place_importance = analyze_feature_importance("nankan_v1", "place")
    if place_importance is not None:
        print(f"\n上位20特徴:")
        print(place_importance.head(20).to_string(index=False))
        
        # 累積重要度80%に必要な特徴数
        top_80_idx = (place_importance["cumsum_pct"] <= 80).sum()
        print(f"\n累積重要度80%に必要な特徴数: {top_80_idx} / {len(place_importance)}")
        print(f"  (全体の {top_80_idx / len(place_importance) * 100:.1f}%)")
        
        # 低重要度特徴の確認
        low_importance_features = place_importance[place_importance["importance"] < place_importance["importance"].quantile(0.25)]
        print(f"\n低重要度特徴（下位25%）: {len(low_importance_features)} 個")
        if len(low_importance_features) > 0:
            print("  以下の特徴は削除候補:")
            print(f"    {', '.join(low_importance_features['feature'].head(10).tolist())}")
    
    # 両モデルで共通に重要な特徴
    print("\n" + "=" * 80)
    print("【両モデルで共通に重要な特徴】")
    if win_importance is not None and place_importance is not None:
        win_top10 = set(win_importance.head(10)["feature"])
        place_top10 = set(place_importance.head(10)["feature"])
        common_top = win_top10 & place_top10
        print(f"上位10に両方に含まれる特徴（{len(common_top)}個）:")
        for feat in sorted(list(common_top)):
            win_rank = win_importance[win_importance["feature"] == feat].index[0] + 1
            place_rank = place_importance[place_importance["feature"] == feat].index[0] + 1
            print(f"  {feat}: Win順位 {win_rank}, Place順位 {place_rank}")
    
    # 改善提案
    print("\n" + "=" * 80)
    print("【改善提案】")
    print("""
1. 低重要度特徴の削除:
   - 下位25%の特徴を削除してモデルを再学習
   - 計算効率の向上 & オーバーフィッティング低減
   
2. 特徴エンジニアリング:
   - 高重要度特徴の二次相互作用項を追加（e.g., horse_rating * num_races）
   - 騎手や馬場の複合特徴を追加
   
3. データ品質向上:
   - 欠損値が多い特徴の取得ロジック改善
   - 外れ値検出と処理の追加
   
4. モデル戦略:
   - 高重要度特徴に特化したシンプルなモデルを並行開発
   - アンサンブル学習で複数モデルを統合
    """)


if __name__ == "__main__":
    main()
