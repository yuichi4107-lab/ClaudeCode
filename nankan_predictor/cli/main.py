import argparse
import logging
import sys
from datetime import datetime, timedelta

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def _parse_date(s: str) -> str:
    """'YYYYMMDD' または 'YYYY-MM-DD' を 'YYYY-MM-DD' に正規化する。"""
    s = s.replace("-", "")
    return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"


def run_scrape(args) -> None:
    from tqdm import tqdm
    from nankan_predictor.scraper.race_list import RaceListScraper
    from nankan_predictor.scraper.race_result import RaceResultScraper
    from nankan_predictor.scraper.horse_history import HorseHistoryScraper
    from nankan_predictor.storage.database import init_db
    from nankan_predictor.storage.repository import Repository
    from nankan_predictor.config.settings import VENUE_CODES, CACHE_DIR, USE_CACHE

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
            # 翌月へ
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
            # 外部キー制約のため馬・騎手を先に登録してからエントリを保存
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
    from nankan_predictor.storage.repository import Repository
    from nankan_predictor.features.builder import FeatureBuilder
    from nankan_predictor.model.trainer import ModelTrainer
    from nankan_predictor.model.registry import save_model

    repo = Repository()
    builder = FeatureBuilder(repo)

    from_date = _parse_date(args.from_date)
    to_date = _parse_date(args.to_date)
    model_name = getattr(args, "model_name", "nankan_v1")
    trainer = ModelTrainer()

    # --- 1着モデル ---
    print(f"[1/2] 1着モデル学習中... ({from_date} ~ {to_date})")
    X_win, y_win = builder.build_training_set(from_date, to_date, target="win")
    print(f"  サンプル: {len(X_win)}, 1着率: {y_win.mean():.1%}")
    win_model = trainer.train(X_win, y_win)
    save_model(win_model, f"{model_name}_win", {
        "from_date": from_date, "to_date": to_date,
        "target": "win", "positive_rate": float(y_win.mean()),
    })

    # --- 2着モデル ---
    print(f"[2/2] 2着モデル学習中...")
    X_place, y_place = builder.build_training_set(from_date, to_date, target="place")
    print(f"  サンプル: {len(X_place)}, 2着率: {y_place.mean():.1%}")
    place_model = trainer.train(X_place, y_place)
    save_model(place_model, f"{model_name}_place", {
        "from_date": from_date, "to_date": to_date,
        "target": "place", "positive_rate": float(y_place.mean()),
    })

    print("学習完了")


def run_predict(args) -> None:
    from nankan_predictor.scraper.race_list import RaceListScraper
    from nankan_predictor.scraper.race_entry import RaceEntryScraper
    from nankan_predictor.storage.database import init_db
    from nankan_predictor.storage.repository import Repository
    from nankan_predictor.features.builder import FeatureBuilder
    from nankan_predictor.model.predictor import ModelPredictor
    from nankan_predictor.config.settings import VENUE_CODES, CACHE_DIR

    init_db()
    repo = Repository()
    model_name = getattr(args, "model_name", "nankan_v1")
    top_n = getattr(args, "top_n", 3)

    venue_code = None
    if hasattr(args, "venue") and args.venue != "all":
        venue_code = VENUE_CODES.get(args.venue)

    race_list_scraper = RaceListScraper(use_cache=False, cache_dir=CACHE_DIR)
    entry_scraper = RaceEntryScraper(use_cache=False, cache_dir=CACHE_DIR)
    builder = FeatureBuilder(repo)
    predictor = ModelPredictor(model_name)

    if hasattr(args, "race_id") and args.race_id:
        race_ids = [args.race_id]
    elif hasattr(args, "date") and args.date:
        date_str = args.date.replace("-", "")
        race_ids = race_list_scraper.get_race_ids_for_date(date_str, venue_code)
    else:
        print("--race-id または --date を指定してください")
        sys.exit(1)

    for race_id in race_ids:
        try:
            data = entry_scraper.scrape(race_id)
            race_info = data["race_info"]
            entries = data["entries"]
            if not entries:
                continue

            df = builder.build_prediction_rows(race_id, entries, race_info)
            ranked = predictor.predict_exacta(df, top_n=top_n)

            venue = race_info.get("venue_name", race_id[4:6])
            race_num = race_info.get("race_number", "?")
            dist = race_info.get("distance", "?")
            track = race_info.get("track_type", "")
            cond = race_info.get("track_condition", "")
            field_size = len(entries)

            print(f"\nRace {race_id} - {venue}競馬場 第{race_num}R "
                  f"{track}{dist}m {cond} ({field_size}頭)")
            print(f"馬単予想 上位{top_n}組み合わせ:")

            for rank, row in ranked.iterrows():
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
        except Exception as e:
            logging.warning("Failed to predict race %s: %s", race_id, e)


def run_evaluate(args) -> None:
    import pandas as pd
    from nankan_predictor.storage.repository import Repository
    from nankan_predictor.features.builder import FeatureBuilder
    from nankan_predictor.model.predictor import ModelPredictor
    from nankan_predictor.model.evaluation import evaluate_exacta_roi, print_evaluation

    repo = Repository()
    model_name = getattr(args, "model_name", "nankan_v1")
    from_date = _parse_date(args.from_date)
    to_date = datetime.now().strftime("%Y-%m-%d")

    builder = FeatureBuilder(repo)
    predictor = ModelPredictor(model_name)

    print(f"評価期間: {from_date} ~ {to_date}")
    entries_df = repo.get_entries_in_range(from_date, to_date)
    if len(entries_df) == 0:
        print("評価データがありません。先にスクレイピングを実行してください。")
        return

    all_combos = []
    for race_id, group in entries_df.groupby("race_id"):
        X_race = builder.build_prediction_rows(race_id, group.to_dict("records"), group.iloc[0].to_dict())
        combos = predictor.predict_exacta(X_race, top_n=1)
        combos["race_id"] = race_id
        all_combos.append(combos)

    predictions_df = pd.concat(all_combos, ignore_index=True)
    result = evaluate_exacta_roi(predictions_df, repo)
    print_evaluation(result)


def main():
    parser = argparse.ArgumentParser(
        prog="nankan",
        description="南関東 地方競馬 単勝予想システム",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # scrape
    p_scrape = sub.add_parser("scrape", help="過去レースデータを収集する")
    p_scrape.add_argument("--date", help="特定日付 YYYYMMDD または YYYY-MM-DD")
    p_scrape.add_argument("--from-date", dest="from_date", help="開始日")
    p_scrape.add_argument("--to-date", dest="to_date", help="終了日")
    p_scrape.add_argument(
        "--venue",
        choices=["oi", "funabashi", "kawasaki", "urawa", "all"],
        default="all",
    )
    p_scrape.add_argument("--no-cache", action="store_true", dest="no_cache")

    # train
    p_train = sub.add_parser("train", help="予測モデルを学習する")
    p_train.add_argument("--from-date", required=True, dest="from_date")
    p_train.add_argument("--to-date", required=True, dest="to_date")
    p_train.add_argument("--model-name", dest="model_name", default="nankan_v1")

    # predict
    p_pred = sub.add_parser("predict", help="出馬表から単勝予想を出力する")
    p_pred.add_argument("--race-id", dest="race_id", help="レースID (例: 202646020601)")
    p_pred.add_argument("--date", help="YYYYMMDD: その日の全レースを予想")
    p_pred.add_argument(
        "--venue",
        choices=["oi", "funabashi", "kawasaki", "urawa", "all"],
        default="all",
    )
    p_pred.add_argument("--model-name", dest="model_name", default="nankan_v1")
    p_pred.add_argument("--top-n", dest="top_n", type=int, default=3)

    # evaluate
    p_eval = sub.add_parser("evaluate", help="バックテストでROIを評価する")
    p_eval.add_argument("--from-date", required=True, dest="from_date")
    p_eval.add_argument("--model-name", dest="model_name", default="nankan_v1")

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
