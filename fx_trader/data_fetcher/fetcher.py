"""市場データ取得・DB保存を統合する DataFetcher"""

import logging
from datetime import datetime, timezone

from fx_trader.config import settings
from fx_trader.data_fetcher.oanda_client import OandaClient
from fx_trader.storage.repository import Repository

logger = logging.getLogger(__name__)


class DataFetcher:
    """OANDA APIからデータを取得してDBに保存"""

    def __init__(self, repo: Repository = None, client: OandaClient = None):
        self.repo = repo or Repository()
        self.client = client or OandaClient()

    def fetch_candles(
        self,
        instrument: str,
        granularity: str = "H1",
        from_date: str = None,
        to_date: str = None,
        count: int = None,
    ) -> int:
        """ローソク足を取得してDBに保存

        Args:
            instrument: 通貨ペア (例: "USD_JPY")
            granularity: 足の種類
            from_date: 開始日 (YYYY-MM-DD or RFC3339)
            to_date: 終了日
            count: 取得本数（from_date未指定時）

        Returns:
            保存した本数
        """
        # from_date が指定されていなければ、DB内の最新から続きを取得
        if not from_date:
            latest = self.repo.get_latest_candle_time(instrument, granularity)
            if latest:
                from_date = latest
                logger.info("Resuming from %s for %s/%s", from_date, instrument, granularity)

        try:
            if from_date and to_date:
                from_time = self._to_rfc3339(from_date)
                to_time = self._to_rfc3339(to_date)
                candles = self.client.get_candles_range(instrument, granularity, from_time, to_time)
            elif from_date:
                from_time = self._to_rfc3339(from_date)
                candles = self.client.get_candles(instrument, granularity, from_time=from_time, count=count or 5000)
            else:
                candles = self.client.get_candles(instrument, granularity, count=count or 500)

            if candles:
                self.repo.upsert_candles(candles)
                logger.info("Saved %d candles for %s/%s", len(candles), instrument, granularity)

            self.repo.log_fetch({
                "instrument": instrument,
                "granularity": granularity,
                "from_time": from_date,
                "to_time": to_date,
                "candle_count": len(candles),
                "status": "success",
                "error_msg": None,
            })

            return len(candles)

        except Exception as e:
            logger.error("Failed to fetch candles for %s/%s: %s", instrument, granularity, e)
            self.repo.log_fetch({
                "instrument": instrument,
                "granularity": granularity,
                "from_time": from_date,
                "to_time": to_date,
                "candle_count": 0,
                "status": "error",
                "error_msg": str(e),
            })
            raise

    def fetch_all_instruments(
        self,
        granularity: str = "H1",
        from_date: str = None,
        to_date: str = None,
        instruments: list[str] = None,
    ) -> dict[str, int]:
        """複数通貨ペアのデータを一括取得

        Returns:
            dict: {instrument: candle_count}
        """
        targets = instruments or settings.DEFAULT_INSTRUMENTS
        results = {}

        for inst in targets:
            logger.info("Fetching %s/%s ...", inst, granularity)
            try:
                count = self.fetch_candles(inst, granularity, from_date, to_date)
                results[inst] = count
            except Exception as e:
                logger.error("Skipping %s: %s", inst, e)
                results[inst] = 0

        return results

    @staticmethod
    def _to_rfc3339(date_str: str) -> str:
        """日付文字列をRFC3339形式に変換"""
        if "T" in date_str:
            return date_str  # 既にRFC3339
        # YYYY-MM-DD → RFC3339
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.000000000Z")
