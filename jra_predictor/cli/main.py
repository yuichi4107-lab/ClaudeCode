import argparse
import logging
import sys
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def _parse_date(s: str) -> str:
    """'YYYYMMDD' または 'YYYY-MM-DD' を 'YYYY-MM-DD' に正規化する。"""
    s = s.replace("-", "")
    return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"


VENUE_CHOICES = [
    "sapporo", "hakodate", "fukushima", "niigata",
    "tokyo", "nakayama", "chukyo", "kyoto", "hanshin", "kokura",
    "all",
]


def run_scrape(args) -> None:
    from tqdm import tqdm
    from jra_predictor.scraper.race_list import RaceListScraper
    from jra_predictor.scraper.race_result import RaceResultScraper
    from jra_predictor.scraper.horse_history import HorseHistoryScraper
    from jra_predictor.storage.database import init_db
    from jra_predictor.storage.repository import Repository
    from jra_predictor.config.settings import VENUE_CODES, CACHE_DIR

    init_db()
    repo = Repository()
    use_cache = not getattr(args, "no_cache", False)

    race_list_scraper = RaceListScraper(use_cache=use_cache, cache_dir=CACHE_DIR)
    result_scraper = RaceResultScraper(use_cache=use_cache, cache_dir=CACHE_DIR)
    history_scraper = HorseHistoryScraper(use_cache=use_cache, cache_dir=CACHE_DIR)

    venue_code = None
    if hasattr(args, "venue") and args.venue != "all":
        venue_code = VENUE_CODES.get(args.venue)

    # 対象レースIDを収集
    race_ids = []
    if hasattr(args, "date") and args.date:
        date_str = args.date.replace("-", "")
        race_ids = race_list_scraper.get_race_ids_for_date(date_str, venue_code)
    elif hasattr(args, "from_date") and args.from_date:
        from_dt = datetime.strptime(_parse_date(args.from_date), "%Y-%m-%d")
        to_dt = datetime.strptime(_parse_date(args.to_date), "%Y-%m-%d")
        current = from_dt.replace(day=1)
        while current <= to_dt:
            ids = race_list_scraper.get_race_ids_for_month(current.year, current.month)
            race_ids.extend(ids)
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)
        # 範囲外を除外
        race_ids = [
            r for r in race_ids
            if from_dt <= datetime.strptime(
                f"{r[0:4]}-{r[6:8]}-{r[8:10]}", "%Y-%m-%d"
            ) <= to_dt
        ]

    race_ids = list(set(race_ids))
    print(f"スクレイピング対象: {len(race_ids)} レース")

    new_horse_ids = set()
    for race_id in tqdm(race_ids, desc="Races"):
        try:
            data = result_scraper.scrape(race_id)
            repo.upsert_race(data["race_info"])
            for entry in data["entries"]:
                if entry.get("horse_id"):
                    repo.upsert_horse(entry["horse_id"], entry.get("horse_name", ""))
                    if not repo.horse_history_exists(entry["horse_id"]):
                        new_horse_ids.add(entry["horse_id"])
                if entry.get("jockey_id"):
                    repo.upsert_jockey(entry["jockey_id"], entry.get("jockey_name", ""))
            repo.upsert_entries(data["entries"])
            for payout in data.get("payouts", []):
                repo.upsert_payout(
                    payout["race_id"], payout["bet_type"],
                    payout["combination"], payout["payout"]
                )
        except Exception as e:
            logging.warning("Failed to scrape race %s: %s", race_id, e)

    print(f"馬の過去成績取得: {len(new_horse_ids)} 頭")
    for horse_id in tqdm(new_horse_ids, desc="Horse histories"):
        try:
            rows = history_scraper.scrape(horse_id)
            repo.upsert_horse_history(horse_id, rows)
        except Exception as e:
            logging.warning("Failed to scrape horse %s: %s", horse_id, e)

    print("スクレイピング完了")


def run_train(args) -> None:
    from jra_predictor.storage.repository import Repository
    from jra_predictor.features.builder import FeatureBuilder
    from jra_predictor.model.trainer import ModelTrainer
    from jra_predictor.model.registry import save_model

    repo = Repository()
    builder = FeatureBuilder(repo)

    from_date = _parse_date(args.from_date)
    to_date = _parse_date(args.to_date)
    model_name = getattr(args, "model_name", "jra_v1")
    trainer = ModelTrainer()

    # --- 1着モデル (馬単用) ---
    print(f"[1/3] 1着モデル学習中... ({from_date} ~ {to_date})")
    X_win, y_win = builder.build_training_set(from_date, to_date, target="win")
    print(f"  サンプル: {len(X_win)}, 1着率: {y_win.mean():.1%}")
    win_model = trainer.train(X_win, y_win)
    save_model(win_model, f"{model_name}_win", {
        "from_date": from_date, "to_date": to_date,
        "target": "win", "positive_rate": float(y_win.mean()),
        "features": list(X_win.columns),
    })

    # --- 2着モデル (馬単用) ---
    print(f"[2/3] 2着モデル学習中...")
    X_place, y_place = builder.build_training_set(from_date, to_date, target="place")
    print(f"  サンプル: {len(X_place)}, 2着率: {y_place.mean():.1%}")
    place_model = trainer.train(X_place, y_place)
    save_model(place_model, f"{model_name}_place", {
        "from_date": from_date, "to_date": to_date,
        "target": "place", "positive_rate": float(y_place.mean()),
        "features": list(X_place.columns),
    })

    # --- 3着以内モデル (三連複用) ---
    print(f"[3/3] 3着以内モデル学習中...")
    X_top3, y_top3 = builder.build_training_set(from_date, to_date, target="top3")
    print(f"  サンプル: {len(X_top3)}, 3着以内率: {y_top3.mean():.1%}")
    top3_model = trainer.train(X_top3, y_top3)
    save_model(top3_model, f"{model_name}_top3", {
        "from_date": from_date, "to_date": to_date,
        "target": "top3", "positive_rate": float(y_top3.mean()),
        "features": list(X_top3.columns),
    })

    print("学習完了（馬単 + 三連複）")


def run_predict(args) -> None:
    from math import comb
    from jra_predictor.scraper.race_list import RaceListScraper
    from jra_predictor.scraper.race_entry import RaceEntryScraper
    from jra_predictor.storage.database import init_db
    from jra_predictor.storage.repository import Repository
    from jra_predictor.features.builder import FeatureBuilder
    from jra_predictor.model.predictor import ModelPredictor
    from jra_predictor.model.strategy import (
        score_exacta_race, score_trio_race, score_trio_box_race,
        select_races, print_race_selection,
    )
    from jra_predictor.config.settings import VENUE_CODES, VENUE_NAMES_JP, CACHE_DIR

    init_db()
    repo = Repository()
    model_name = getattr(args, "model_name", "jra_v1")
    top_n = getattr(args, "top_n", 3)
    bet_type = getattr(args, "bet_type", "exacta")
    max_races = getattr(args, "max_races", 0)  # 0 = 全レース
    min_confidence = getattr(args, "min_confidence", 0.0)
    box_size = getattr(args, "box", 0)

    venue_code = None
    if hasattr(args, "venue") and args.venue != "all":
        venue_code = VENUE_CODES.get(args.venue)

    race_list_scraper = RaceListScraper(use_cache=False, cache_dir=CACHE_DIR)
    entry_scraper = RaceEntryScraper(use_cache=False, cache_dir=CACHE_DIR)
    builder = FeatureBuilder(repo)
    predictor = ModelPredictor(model_name, bet_types=[bet_type])

    if hasattr(args, "race_id") and args.race_id:
        race_ids = [args.race_id]
    elif hasattr(args, "date") and args.date:
        date_str = args.date.replace("-", "")
        race_ids = race_list_scraper.get_race_ids_for_date(date_str, venue_code)
    else:
        print("--race-id または --date を指定してください")
        sys.exit(1)

    # まず全レースの予測と自信度を計算
    race_results = []
    for race_id in race_ids:
        try:
            data = entry_scraper.scrape(race_id)
            race_info = data["race_info"]
            entries = data["entries"]
            if not entries:
                continue

            df = builder.build_prediction_rows(race_id, entries, race_info)
            field_size = len(entries)

            if bet_type == "trio" and box_size > 0:
                # ボックスモード
                box_result = predictor.predict_trio_box(df, box_size=box_size)
                all_probs = sorted(
                    [h["top3_prob"] for h in box_result["selected_horses"]]
                    + [0.0] * max(0, field_size - box_size),
                    reverse=True,
                )
                # 全馬のP(top3)を取得してスコアリング
                import numpy as np
                all_top3 = predictor.predict_top3_probs(df)
                all_top3_sorted = sorted(all_top3.tolist(), reverse=True)
                score = score_trio_box_race(
                    box_result["selected_horses"], box_size, field_size, all_top3_sorted,
                )
                score["race_id"] = race_id
                score["venue"] = race_info.get("venue_name", VENUE_NAMES_JP.get(race_id[4:6], ""))
                score["race_number"] = race_info.get("race_number", "?")
                score["race_info"] = race_info
                score["box_result"] = box_result
                race_results.append(score)
            elif bet_type == "trio":
                ranked = predictor.predict_trio(df, top_n=max(top_n, 5))
                score = score_trio_race(ranked, field_size)
                score["race_id"] = race_id
                score["venue"] = race_info.get("venue_name", VENUE_NAMES_JP.get(race_id[4:6], ""))
                score["race_number"] = race_info.get("race_number", "?")
                score["race_info"] = race_info
                score["ranked"] = ranked
                race_results.append(score)
            else:
                ranked = predictor.predict_exacta(df, top_n=max(top_n, 5))
                score = score_exacta_race(ranked, field_size)
                score["race_id"] = race_id
                score["venue"] = race_info.get("venue_name", VENUE_NAMES_JP.get(race_id[4:6], ""))
                score["race_number"] = race_info.get("race_number", "?")
                score["race_info"] = race_info
                score["ranked"] = ranked
                race_results.append(score)
        except Exception as e:
            logging.warning("Failed to predict race %s: %s", race_id, e)

    # 選択的モード: 自信度上位のレースのみ出力
    if max_races > 0:
        selected = select_races(race_results, max_races=max_races, min_confidence=min_confidence)
        print_race_selection(selected, bet_type=bet_type, box_size=box_size)
        output_races = selected
    else:
        output_races = race_results

    # 予測結果を出力
    for score in output_races:
        race_id = score["race_id"]
        race_info = score["race_info"]

        venue = race_info.get("venue_name", race_id[4:6])
        race_num = race_info.get("race_number", "?")
        dist = race_info.get("distance", "?")
        track = race_info.get("track_type", "")
        cond = race_info.get("track_condition", "")
        field_size = score.get("field_size", "?")

        conf_str = f" [自信度: {score['confidence_score']:.2f}]"
        print(f"\nRace {race_id} - {venue}競馬場 第{race_num}R "
              f"{track}{dist}m {cond} ({field_size}頭){conf_str}")

        if bet_type == "trio" and box_size > 0:
            # ボックス出力
            box_result = score["box_result"]
            n_tickets = box_result["n_tickets"]
            print(f"三連複 {box_size}頭BOX ({n_tickets}点):")
            print(f"  選出馬:")
            for h in box_result["selected_horses"]:
                print(f"    {int(h['horse_number']):>2} {h['horse_name']:<12} P(top3)={h['top3_prob']:.3f}")
            print(f"  購入組み合わせ:")
            for _, row in box_result["box_combos"].iterrows():
                h1 = int(row["horse1_number"])
                h2 = int(row["horse2_number"])
                h3 = int(row["horse3_number"])
                print(f"    {h1}-{h2}-{h3}")
        elif bet_type == "trio":
            ranked = score["ranked"]
            display_ranked = ranked.head(top_n)
            print(f"三連複予想 上位{top_n}組み合わせ:")
            for rank, row in display_ranked.iterrows():
                h1 = int(row.get("horse1_number", 0))
                h1n = row.get("horse1_name", "不明")
                h2 = int(row.get("horse2_number", 0))
                h2n = row.get("horse2_name", "不明")
                h3 = int(row.get("horse3_number", 0))
                h3n = row.get("horse3_name", "不明")
                prob = row.get("trio_prob", 0)
                print(
                    f"  {rank}位: {h1}-{h2}-{h3}  "
                    f"({h1n}, {h2n}, {h3n})  "
                    f"P={prob:.4f}"
                )
        else:
            ranked = score["ranked"]
            display_ranked = ranked.head(top_n)
            print(f"馬単予想 上位{top_n}組み合わせ:")
            for rank, row in display_ranked.iterrows():
                fn = int(row.get("first_horse_number", 0))
                fn_name = row.get("first_horse_name", "不明")
                sn = int(row.get("second_horse_number", 0))
                sn_name = row.get("second_horse_name", "不明")
                prob = row.get("exacta_prob", 0)
                print(
                    f"  {rank}位: {fn}→{sn}  "
                    f"({fn_name} → {sn_name})  "
                    f"P={prob:.4f}"
                )


def run_evaluate(args) -> None:
    import pandas as pd
    from jra_predictor.storage.repository import Repository
    from jra_predictor.features.builder import FeatureBuilder
    from jra_predictor.model.predictor import ModelPredictor
    from jra_predictor.model.strategy import (
        score_exacta_race, score_trio_race, score_trio_box_race,
    )
    from jra_predictor.model.evaluation import (
        evaluate_exacta_roi, evaluate_trio_roi,
        evaluate_selective_roi,
        print_evaluation, print_selective_evaluation,
    )

    repo = Repository()
    model_name = getattr(args, "model_name", "jra_v1")
    top_n = getattr(args, "top_n", 1)
    threshold = getattr(args, "threshold", 0.01)
    bet_type = getattr(args, "bet_type", "exacta")
    max_races = getattr(args, "max_races", 0)
    min_confidence = getattr(args, "min_confidence", 0.0)
    box_size = getattr(args, "box", 0)
    from_date = _parse_date(args.from_date)
    to_date = datetime.now().strftime("%Y-%m-%d")

    builder = FeatureBuilder(repo)
    builder.ensure_preloaded()  # メモリにプリロードして高速化
    predictor = ModelPredictor(model_name, bet_types=[bet_type])

    if bet_type == "trio" and box_size > 0:
        from math import comb
        label = f"三連複{box_size}頭BOX({comb(box_size, 3)}点/R)"
    elif bet_type == "trio":
        label = "三連複"
    else:
        label = "馬単"
    mode = "選択的" if max_races > 0 else "全レース"
    print(f"評価期間: {from_date} ~ {to_date} ({label}, {mode})")
    entries_df = repo.get_entries_in_range(from_date, to_date)
    if len(entries_df) == 0:
        print("評価データがありません。先にスクレイピングを実行してください。")
        return

    if max_races > 0:
        # 選択的ベッティング
        race_predictions = []
        for race_id, group in entries_df.groupby("race_id"):
            X_race = builder.build_prediction_rows(
                race_id, group.to_dict("records"), group.iloc[0].to_dict()
            )
            field_size = len(group)
            race_date = f"{race_id[:4]}-{race_id[6:8]}-{race_id[8:10]}"

            if bet_type == "trio" and box_size > 0:
                box_result = predictor.predict_trio_box(X_race, box_size=box_size)
                import numpy as np
                all_top3 = predictor.predict_top3_probs(X_race)
                all_top3_sorted = sorted(all_top3.tolist(), reverse=True)
                score = score_trio_box_race(
                    box_result["selected_horses"], box_size, field_size, all_top3_sorted,
                )
                race_predictions.append({
                    "race_id": race_id,
                    "race_date": race_date,
                    "confidence_score": score["confidence_score"],
                    "box_combos": box_result["box_combos"],
                    "predictions": box_result["box_combos"],
                })
            elif bet_type == "trio":
                preds = predictor.predict_trio(X_race, top_n=10)
                score = score_trio_race(preds, field_size)
                race_predictions.append({
                    "race_id": race_id,
                    "race_date": race_date,
                    "confidence_score": score["confidence_score"],
                    "predictions": preds,
                })
            else:
                preds = predictor.predict_exacta(X_race, top_n=10)
                score = score_exacta_race(preds, field_size)
                race_predictions.append({
                    "race_id": race_id,
                    "race_date": race_date,
                    "confidence_score": score["confidence_score"],
                    "predictions": preds,
                })

        result = evaluate_selective_roi(
            race_predictions, repo,
            bet_type=bet_type,
            max_races_per_day=max_races,
            min_confidence=min_confidence,
            top_n_per_race=top_n,
            box_size=box_size,
        )
        print_selective_evaluation(
            result, bet_type=bet_type,
            max_races=max_races, min_confidence=min_confidence,
            top_n=top_n, box_size=box_size,
        )
    else:
        # 従来の全レース評価
        all_combos = []
        for race_id, group in entries_df.groupby("race_id"):
            X_race = builder.build_prediction_rows(
                race_id, group.to_dict("records"), group.iloc[0].to_dict()
            )
            if bet_type == "trio":
                combos = predictor.predict_trio(X_race, top_n=10)
            else:
                combos = predictor.predict_exacta(X_race, top_n=10)
            combos["race_id"] = race_id
            all_combos.append(combos)

        predictions_df = pd.concat(all_combos, ignore_index=True)

        if bet_type == "trio":
            result = evaluate_trio_roi(predictions_df, repo, top_n=top_n, threshold=threshold)
        else:
            result = evaluate_exacta_roi(predictions_df, repo, top_n=top_n, threshold=threshold)
        print_evaluation(result, bet_type=bet_type, top_n=top_n, threshold=threshold)


def main():
    parser = argparse.ArgumentParser(
        prog="jra",
        description="JRA 中央競馬 馬単・三連複予想システム",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # scrape
    p_scrape = sub.add_parser("scrape", help="過去レースデータを収集する")
    p_scrape.add_argument("--date", help="特定日付 YYYYMMDD または YYYY-MM-DD")
    p_scrape.add_argument("--from-date", dest="from_date", help="開始日")
    p_scrape.add_argument("--to-date", dest="to_date", help="終了日")
    p_scrape.add_argument("--venue", choices=VENUE_CHOICES, default="all")
    p_scrape.add_argument("--no-cache", action="store_true", dest="no_cache")

    # train
    p_train = sub.add_parser("train", help="予測モデルを学習する（馬単+三連複）")
    p_train.add_argument("--from-date", required=True, dest="from_date")
    p_train.add_argument("--to-date", required=True, dest="to_date")
    p_train.add_argument("--model-name", dest="model_name", default="jra_v1")

    # predict
    p_pred = sub.add_parser("predict", help="出馬表から予想を出力する")
    p_pred.add_argument("--race-id", dest="race_id", help="レースID (例: 202505030801)")
    p_pred.add_argument("--date", help="YYYYMMDD: その日の全レースを予想")
    p_pred.add_argument("--venue", choices=VENUE_CHOICES, default="all")
    p_pred.add_argument("--model-name", dest="model_name", default="jra_v1")
    p_pred.add_argument("--top-n", dest="top_n", type=int, default=3)
    p_pred.add_argument(
        "--bet-type", dest="bet_type", choices=["exacta", "trio"], default="exacta",
        help="馬券種: exacta=馬単, trio=三連複 (デフォルト: exacta)",
    )
    p_pred.add_argument(
        "--max-races", dest="max_races", type=int, default=0,
        help="1日の最大購入レース数 (0=全レース, 推奨: 4〜6)",
    )
    p_pred.add_argument(
        "--min-confidence", dest="min_confidence", type=float, default=0.0,
        help="最低自信度スコア (デフォルト: 0.0)",
    )
    p_pred.add_argument(
        "--box", dest="box", type=int, default=0, choices=[0, 4, 5],
        help="三連複ボックス頭数 (4=4点BOX, 5=10点BOX, 0=通常)",
    )

    # evaluate
    p_eval = sub.add_parser("evaluate", help="バックテストでROIを評価する")
    p_eval.add_argument("--from-date", required=True, dest="from_date")
    p_eval.add_argument("--model-name", dest="model_name", default="jra_v1")
    p_eval.add_argument("--top-n", dest="top_n", type=int, default=1,
                        help="1Rあたり購入組数（デフォルト: 1）")
    p_eval.add_argument("--threshold", dest="threshold", type=float, default=0.01,
                        help="確率閾値（デフォルト: 0.01）")
    p_eval.add_argument(
        "--bet-type", dest="bet_type", choices=["exacta", "trio"], default="exacta",
        help="馬券種: exacta=馬単, trio=三連複 (デフォルト: exacta)",
    )
    p_eval.add_argument(
        "--max-races", dest="max_races", type=int, default=0,
        help="1日の最大購入レース数 (0=全レース評価, 推奨: 4〜6)",
    )
    p_eval.add_argument(
        "--min-confidence", dest="min_confidence", type=float, default=0.0,
        help="最低自信度スコア (デフォルト: 0.0)",
    )
    p_eval.add_argument(
        "--box", dest="box", type=int, default=0, choices=[0, 4, 5],
        help="三連複ボックス頭数 (4=4点BOX, 5=10点BOX, 0=通常)",
    )

    args = parser.parse_args()

    if args.command == "scrape":
        run_scrape(args)
    elif args.command == "train":
        run_train(args)
    elif args.command == "predict":
        run_predict(args)
    elif args.command == "evaluate":
        run_evaluate(args)


if __name__ == "__main__":
    main()
