#!/usr/bin/env python3
"""特徴重要度解析（実用版）: 実際の特徴名を表示"""

import pandas as pd
import numpy as np
import joblib
from pathlib import Path

# NUMERIC_FEATURES の定義（builder.py から抽出）
NUMERIC_FEATURES = [
    "horse_last1_finish",
    "horse_last3_avg_finish",
    "horse_last5_win_rate",
    "horse_last5_top3_rate",
    "horse_career_win_rate",
    "horse_days_since_last",
    "horse_same_venue_win_rate",
    "horse_same_dist_win_rate",
    "horse_speed_index_last1",
    "horse_speed_index_last3",
    "horse_weight_change",
    "jockey_win_rate_overall",
    "jockey_win_rate_venue",
    "jockey_horse_pair_wins",
    "field_size",
    "distance",
    "gate_number",
    "horse_number",
    "weight_carried",
    "horse_weight",
    "popularity_rank",
    "venue_enc",
    "track_type_enc",
    "track_cond_enc",
    "race_number",
]


def analyze_feature_importance(model_name: str = "nankan_v1", target: str = "win"):
    """特徴重要度を解析してランク付けする"""
    
    # モデルを読み込む
    model_path = Path(f"data/models/{model_name}_{target}.joblib")
    if not model_path.exists():
        print(f"Error: Model not found at {model_path}")
        return None
    
    model = joblib.load(model_path)
    
    # CalibratedClassifierCV から estimator を取得
    if hasattr(model, "estimator"):
        pipeline = model.estimator
    else:
        pipeline = model
    
    # パイプラインから LGBMClassifier を取得
    if hasattr(pipeline, "named_steps"):
        lgb_model = pipeline.named_steps.get("clf")
    elif hasattr(pipeline, "steps"):
        lgb_model = [step[1] for step in pipeline.steps if hasattr(step[1], "feature_importances_")]
        lgb_model = lgb_model[0] if lgb_model else None
    else:
        lgb_model = pipeline if hasattr(pipeline, "feature_importances_") else None
    
    if lgb_model is None or not hasattr(lgb_model, "feature_importances_"):
        return None
    
    importances = lgb_model.feature_importances_
    feature_names = lgb_model.feature_names_in_
    
    # DataFrame に整形（実際の特徴名にマッピング）
    importance_df = pd.DataFrame({
        "feature_name": [NUMERIC_FEATURES[i] if f"Column_{i}" in feature_names else f for i, f in enumerate(feature_names)],
        "importance": importances,
    })
    
    # Column_* 形式の場合は、そのインデックスからマッピング
    if importance_df["feature_name"].iloc[0].startswith("Column_"):
        importance_df["feature_name"] = [NUMERIC_FEATURES[int(f.split("_")[1])] for f in feature_names]
    
    importance_df = importance_df.sort_values("importance", ascending=False).reset_index(drop=True)
    importance_df["rank"] = range(1, len(importance_df) + 1)
    importance_df["cumsum"] = importance_df["importance"].cumsum()
    importance_df["cumsum_pct"] = (importance_df["cumsum"] / importance_df["importance"].sum()) * 100
    
    return importance_df


def main():
    print("=" * 100)
    print("特徴重要度解析（詳細版）— モデルが何を最も重視しているか")
    print("=" * 100)
    
    # 1着モデルの分析
    print("\n【1着モデル（Win）の特徴重要度】")
    win_importance = analyze_feature_importance("nankan_v1", "win")
    if win_importance is not None:
        print(f"\n上位15特徴:")
        top_15 = win_importance.head(15)[["rank", "feature_name", "importance", "cumsum_pct"]]
        print(top_15.to_string(index=False))
        
        # 累積重要度80%に必要な特徴数
        top_80_idx = (win_importance["cumsum_pct"] <= 80).sum()
        print(f"\n✓ 累積重要度80%に必要な特徴数: {top_80_idx} / {len(win_importance)}")
        print(f"  (全体の {top_80_idx / len(win_importance) * 100:.1f}% を削減可能)")
        
        # トップ3の詳解説
        print(f"\n【トップ3特徴の詳細分析】")
        for idx in range(3):
            row = win_importance.iloc[idx]
            feat = row["feature_name"]
            importance = row["importance"]
            pct = row["cumsum_pct"]
            
            explanation = {
                "jockey_horse_pair_wins": "騎手と馬のペア成績が最強の予測要因。同じ騎手に乗る馬の過去成績が重要。",
                "horse_days_since_last": "馬の休国日数（調教期間）。休暇から戻った直後かどうかが勝敗に大きく影響。",
                "horse_last1_finish": "直前レースのフィニッシュ（順位）。前回のパフォーマンスが次走の参考になる。",
                "horse_last3_avg_finish": "直近3レースの平均順位。安定性と実力の指標。",
                "distance": "レース距離。馬には得意な距離があり、距離適性が勝敗を左右。",
            }.get(feat, "（詳細説明は割愛）")
            
            print(f"{idx+1}位) {feat}")
            print(f"     重要度: {importance:.0f} (累積: {pct:.1f}%)")
            print(f"     解釈: {explanation}")
    
    # 2着モデルの分析
    print("\n" + "=" * 100)
    print("【2着モデル（Place）の特徴重要度】")
    place_importance = analyze_feature_importance("nankan_v1", "place")
    if place_importance is not None:
        print(f"\n上位15特徴:")
        top_15 = place_importance.head(15)[["rank", "feature_name", "importance", "cumsum_pct"]]
        print(top_15.to_string(index=False))
        
        # 累積重要度80%に必要な特徴数
        top_80_idx = (place_importance["cumsum_pct"] <= 80).sum()
        print(f"\n✓ 累積重要度80%に必要な特徴数: {top_80_idx} / {len(place_importance)}")
        print(f"  (全体の {top_80_idx / len(place_importance) * 100:.1f}% を削減可能)")
    
    # 両モデルで共通に重要な特徴
    print("\n" + "=" * 100)
    print("【両モデルで共通に重要な特徴 — 普遍的な予測因子】")
    if win_importance is not None and place_importance is not None:
        win_top10 = set(win_importance.head(10)["feature_name"])
        place_top10 = set(place_importance.head(10)["feature_name"])
        common_top = win_top10 & place_top10
        print(f"\n上位10に両方に含まれる特徴（{len(common_top)}個）:")
        for feat in sorted(list(common_top)):
            win_rank = win_importance[win_importance["feature_name"] == feat]["rank"].values[0]
            place_rank = place_importance[place_importance["feature_name"] == feat]["rank"].values[0]
            print(f"  • {feat:.<35} Win順位 {win_rank:2d}, Place順位 {place_rank:2d}")
    
    # 改善案の提示
    print("\n" + "=" * 100)
    print("【予測精度改善の提案】")
    print("""
【1】 低重要度特徴の削除 → モデルの簡素化・高速化
  • 下位25%の低ランク特徴を削除してモデルを再学習
  • 計算時間短縮 & オーバーフィッティング低減
  • 推奨削除候補: horse_weight, popularity_rank, track_cond_enc など
  
【2】 特徴エンジニアリング → 予測精度向上
  • 高重要度特徴の相互作用項を追加
    例1) jockey_horse_pair_wins × horse_same_venue_win_rate
         = 特定馬場での同一ペアの相性
    例2) horse_last5_win_rate × distance
         = 得意な距離での勝率
    例3) horse_speed_index_last1 × field_size
         = 馬の実力と競争相手のレベル
  
  • 新しい複合特徴の候補
    - 「騎手の平均的な乗り手（技量）× 馬の実力」
    - 「レース難度（出走頭数 & 平均クラス）」
    - 「馬の疲労度（最近のレース間隔 & 連続出走数）」
  
【3】 データ品質向上 → 学習効率改善
  • 欠損値が多い特徴の取得ロジックを改善
    - jockey_horse_pair_wins の計算がより多くのペアを対象に
    - horse_speed_index_last3 の欠損削減（タイムデータの充実）
  • 外れ値検出・処理の追加
    - 異常に高い/低い特徴値の削除またはキャップ
  
【4】 モデル構造改善 → 汎化性能向上
  • 高重要度特徴に特化したシンプルモデルを並行開発
    - 例: jockey_horse_pair_wins, distance, horse_last1_finish の3特徴だけで
      ベースラインモデルを構築して精度比較
  
  • アンサンブル学習
    - 複数の異なるモデル（LGB, XGBoost, ニューラルネット）を組み合わせ
    - スタッキング: メタ予測器に入力
  
【5】 戦略調整 → ROI 改善
  • 高確度予測のフィルタリング強化
    - jockey_horse_pair_wins > 中央値 AND distance 適性あり など
    - 複数条件を満たす高確度情報の組み合わせ
  
  • 賭け戦術の変更
    - コンボ購入（複数レースの組合せ購入）で払戻倍率向上を狙う
    - 的中率は低いが回収率が高い複合式（WINs など）への切り替え
    """)


if __name__ == "__main__":
    main()
