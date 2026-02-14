"""データ収集パイプライン"""

import logging
from datetime import date, timedelta

from tqdm import tqdm

from database.connection import db
from database.repository import Repository
from scraper.horse_profile import HorseProfileScraper
from scraper.jockey_trainer import JockeyTrainerScraper
from scraper.odds import OddsScraper
from scraper.race_list import RaceListScraper
from scraper.race_result import RaceResultScraper
from scraper.win5_target import Win5TargetScraper

logger = logging.getLogger(__name__)


class DataCollector:
    """データ収集パイプラインの統合管理"""

    def __init__(self, use_cache: bool = True):
        self.repo = Repository()
        self.race_list_scraper = RaceListScraper(use_cache=use_cache)
        self.race_result_scraper = RaceResultScraper(use_cache=use_cache)
        self.horse_scraper = HorseProfileScraper(use_cache=use_cache)
        self.jockey_trainer_scraper = JockeyTrainerScraper(use_cache=use_cache)
        self.odds_scraper = OddsScraper(use_cache=use_cache)
        self.win5_scraper = Win5TargetScraper(use_cache=use_cache)

    def collect_date(self, target_date: date, collect_profiles: bool = True):
        """1日分のデータを収集する"""
        logger.info("Collecting data for %s", target_date)

        # レースID一覧を取得
        race_ids = self.race_list_scraper.get_race_ids_by_date(target_date)
        if not race_ids:
            logger.info("No races found on %s", target_date)
            return

        collected_horse_ids = set()
        collected_jockey_ids = set()
        collected_trainer_ids = set()

        for race_id in tqdm(race_ids, desc=str(target_date)):
            # レース結果取得・保存
            race, results = self.race_result_scraper.scrape(race_id)
            if race:
                self.repo.upsert_race(race)
            if results:
                self.repo.bulk_upsert_race_results(results)

                if collect_profiles:
                    for r in results:
                        # 馬のプロフィール
                        if r.horse_id and r.horse_id not in collected_horse_ids:
                            horse = self.horse_scraper.scrape(r.horse_id)
                            if horse:
                                self.repo.upsert_horse(horse)
                            collected_horse_ids.add(r.horse_id)

                        # 騎手
                        if r.jockey_id and r.jockey_id not in collected_jockey_ids:
                            jockey = self.jockey_trainer_scraper.scrape_jockey(
                                r.jockey_id
                            )
                            if jockey:
                                self.repo.upsert_jockey(jockey)
                            collected_jockey_ids.add(r.jockey_id)

                        # 調教師
                        if r.trainer_id and r.trainer_id not in collected_trainer_ids:
                            trainer = self.jockey_trainer_scraper.scrape_trainer(
                                r.trainer_id
                            )
                            if trainer:
                                self.repo.upsert_trainer(trainer)
                            collected_trainer_ids.add(r.trainer_id)

        # Win5情報(日曜のみ)
        if target_date.weekday() == 6:  # 日曜
            win5 = self.win5_scraper.scrape(target_date)
            if win5:
                self.repo.upsert_win5_event(win5)

        logger.info(
            "Collected %d races, %d horses on %s",
            len(race_ids),
            len(collected_horse_ids),
            target_date,
        )

    def collect_range(
        self,
        start: date,
        end: date,
        collect_profiles: bool = True,
        weekends_only: bool = True,
    ):
        """日付範囲のデータを収集する"""
        db.initialize()

        current = start
        total_days = (end - start).days + 1
        collected = 0

        with tqdm(total=total_days, desc="Collecting") as pbar:
            while current <= end:
                if not weekends_only or current.weekday() in (5, 6):
                    try:
                        self.collect_date(
                            current, collect_profiles=collect_profiles
                        )
                        collected += 1
                    except Exception as e:
                        logger.error("Failed on %s: %s", current, e)

                current += timedelta(days=1)
                pbar.update(1)

        logger.info("Collection complete: %d days processed", collected)

    def collect_odds(self, race_ids: list[str]):
        """複数レースのオッズを収集する"""
        for race_id in tqdm(race_ids, desc="Odds"):
            odds = self.odds_scraper.get_all_odds(race_id)
            for o in odds:
                self.repo.save_odds(
                    race_id=race_id,
                    horse_number=o["horse_number"],
                    timestamp=o["timestamp"],
                    win_odds=o["win_odds"],
                    place_odds_min=o.get("place_odds_min"),
                    place_odds_max=o.get("place_odds_max"),
                )

    def collect_win5_history(self, start: date, end: date):
        """Win5過去データを収集する(日曜のみ)"""
        db.initialize()
        current = start
        while current <= end:
            if current.weekday() == 6:  # 日曜
                try:
                    win5 = self.win5_scraper.scrape(current)
                    if win5:
                        self.repo.upsert_win5_event(win5)
                except Exception as e:
                    logger.error("Failed Win5 on %s: %s", current, e)
            current += timedelta(days=1)
