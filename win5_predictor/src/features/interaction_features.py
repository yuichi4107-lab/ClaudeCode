"""交互作用特徴量 (~6個)

特徴量間の相互作用を捉える複合特徴量
"""


def build_interaction_features(
    horse_features: dict[str, float],
    jockey_features: dict[str, float],
    race_features: dict[str, float],
    odds_features: dict[str, float],
) -> dict[str, float]:
    """交互作用特徴量を構築する"""
    f: dict[str, float] = {}

    # 馬の実力 × 騎手の実力
    horse_wr = horse_features.get("win_rate_5", 0.0)
    jockey_wr = jockey_features.get("j_win_rate", 0.0)
    f["horse_x_jockey_wr"] = horse_wr * jockey_wr

    # 馬の適性 × レース条件の一致度
    dist_fit = horse_features.get("dist_win_rate", 0.0)
    surface_fit = horse_features.get("surface_win_rate", 0.0)
    f["aptitude_score"] = (dist_fit + surface_fit) / 2.0

    # スピード × クラス(高クラスでのスピード価値)
    speed = horse_features.get("speed_index", 0.0)
    class_code = race_features.get("class_code", 0.0)
    f["speed_x_class"] = speed * (class_code / 10.0) if class_code > 0 else 0.0

    # オッズと実力の乖離(エッジ検出)
    implied_prob = odds_features.get("implied_prob", 0.1)
    model_wr = horse_features.get("win_rate_10", 0.0)
    f["edge_signal"] = model_wr - implied_prob

    # 休養 × 厩舎力(休み明けは厩舎の力量が重要)
    days_rest = horse_features.get("days_since_last", 0.0)
    trainer_wr = 0.0  # builderで統合時にtrainer_featuresから参照
    f["rest_x_trainer"] = (
        (days_rest / 90.0) * trainer_wr if days_rest > 30 else 0.0
    )

    # 枠順 × 頭数(多頭数での外枠不利)
    post_ratio = race_features.get("post_ratio", 0.5)
    n_runners = race_features.get("num_runners", 14.0)
    f["post_x_field"] = post_ratio * (n_runners / 18.0)

    return f
