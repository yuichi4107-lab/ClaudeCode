"""
FX フォワードテスト スケジューラ

ローソク足確定タイミングでシグナル生成をトリガーするスケジューラ。

スケジュール:
    - 1h足: 毎時00分+5分（例: 10:05, 11:05, ...）
    - 4h足: 4時間ごと+5分（例: 00:05, 04:05, 08:05, 12:05, 16:05, 20:05）
    - 1d足: 毎日00:05 UTC

+5分のオフセットはローソク足確定を待つため。

設計方針:
    - 標準ライブラリのみで実装（schedule 等の外部ライブラリ不使用）
    - time.sleep ベースのシンプルなループ
    - 各タイミングでコールバック関数を呼び出す
    - 呼び出し側は timeframe と callback のペアをリストで渡す
"""

import logging
import time
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# ローソク足確定待ちオフセット（分）
CANDLE_CLOSE_OFFSET_MINUTES: int = 5

# 4h足が確定するUTC時刻の時（hour）リスト
FOUR_HOUR_CLOSE_HOURS: List[int] = [0, 4, 8, 12, 16, 20]

# スリープ間隔（秒）- チェック精度と CPU 負荷のバランス
SLEEP_INTERVAL_SECONDS: int = 30


class ForwardScheduler:
    """
    ローソク足確定タイミングでシグナル生成をトリガーするスケジューラ。

    スケジュール（UTC基準）:
        - 1h足: 毎時00分+5分（HH:05:00）
        - 4h足: 4時間ごと+5分（00:05, 04:05, 08:05, 12:05, 16:05, 20:05）
        - 1d足: 毎日00:05 UTC

    使い方:
        def my_callback(timeframe: str):
            print(f"Signal scan for {timeframe}")

        scheduler = ForwardScheduler()
        scheduler.add_callback("1h", my_callback)
        scheduler.add_callback("4h", my_callback)
        scheduler.add_callback("1d", my_callback)
        scheduler.run()  # Ctrl+C で停止

    コールバック関数のシグネチャ:
        def callback(timeframe: str) -> None
    """

    def __init__(self):
        # timeframe -> List[callback] のマップ
        self._callbacks: Dict[str, List[Callable[[str], None]]] = {
            "1h": [],
            "4h": [],
            "1d": [],
        }
        # 最後にトリガーした時刻を記録（重複トリガー防止）
        self._last_triggered: Dict[str, Optional[datetime]] = {
            "1h": None,
            "4h": None,
            "1d": None,
        }
        self._running: bool = False

    def add_callback(self, timeframe: str, callback: Callable[[str], None]) -> None:
        """
        指定時間足にコールバックを登録する。

        Args:
            timeframe: "1h", "4h", "1d" のいずれか
            callback: 呼び出す関数。引数は timeframe (str)

        Raises:
            ValueError: サポートされていない timeframe を指定した場合
        """
        if timeframe not in self._callbacks:
            raise ValueError(
                f"サポートされていない timeframe: {timeframe}. "
                f"使用可能: {list(self._callbacks.keys())}"
            )
        self._callbacks[timeframe].append(callback)
        logger.debug("コールバック登録: timeframe=%s", timeframe)

    def should_trigger_1h(self, now: datetime) -> bool:
        """
        1h足トリガー条件: 毎時05分（UTC）。

        Args:
            now: 現在時刻（UTC aware datetime）

        Returns:
            bool: トリガーすべきなら True
        """
        if now.minute != CANDLE_CLOSE_OFFSET_MINUTES:
            return False
        # 同じ時刻で2回トリガーしない（HH:05の分内に複数回チェックが入る場合）
        last = self._last_triggered["1h"]
        if last is not None:
            # 同じ時間の05分ならスキップ
            if last.hour == now.hour and last.date() == now.date():
                return False
        return True

    def should_trigger_4h(self, now: datetime) -> bool:
        """
        4h足トリガー条件: 00:05, 04:05, 08:05, 12:05, 16:05, 20:05 UTC。

        Args:
            now: 現在時刻（UTC aware datetime）

        Returns:
            bool: トリガーすべきなら True
        """
        if now.hour not in FOUR_HOUR_CLOSE_HOURS:
            return False
        if now.minute != CANDLE_CLOSE_OFFSET_MINUTES:
            return False
        # 重複チェック
        last = self._last_triggered["4h"]
        if last is not None:
            if last.hour == now.hour and last.date() == now.date():
                return False
        return True

    def should_trigger_1d(self, now: datetime) -> bool:
        """
        1d足トリガー条件: 毎日00:05 UTC。

        Args:
            now: 現在時刻（UTC aware datetime）

        Returns:
            bool: トリガーすべきなら True
        """
        if now.hour != 0:
            return False
        if now.minute != CANDLE_CLOSE_OFFSET_MINUTES:
            return False
        # 重複チェック
        last = self._last_triggered["1d"]
        if last is not None:
            if last.date() == now.date():
                return False
        return True

    def _trigger(self, timeframe: str, now: datetime) -> None:
        """
        指定時間足のコールバックを全て呼び出す。

        Args:
            timeframe: トリガーする時間足
            now: 現在時刻
        """
        ts_str = now.strftime("%Y-%m-%d %H:%M:%S")
        logger.info("[%s] Triggering %s signal scan", ts_str, timeframe)
        print(f"[{ts_str}] Triggering {timeframe} signal scan")

        self._last_triggered[timeframe] = now

        for callback in self._callbacks[timeframe]:
            try:
                callback(timeframe)
            except Exception as exc:
                logger.error(
                    "[%s] %s コールバックでエラーが発生しました: %s",
                    ts_str, timeframe, exc, exc_info=True
                )

    def check_and_trigger(self, now: Optional[datetime] = None) -> List[str]:
        """
        現在時刻を確認してトリガーすべき時間足のコールバックを実行する。

        Args:
            now: 確認する時刻。None の場合は現在のUTC時刻を使用。

        Returns:
            List[str]: トリガーした timeframe のリスト
        """
        if now is None:
            now = datetime.now(timezone.utc)

        triggered = []

        # 1d -> 4h -> 1h の順にチェック（日足が最優先）
        if self.should_trigger_1d(now):
            self._trigger("1d", now)
            triggered.append("1d")

        if self.should_trigger_4h(now):
            self._trigger("4h", now)
            triggered.append("4h")

        if self.should_trigger_1h(now):
            self._trigger("1h", now)
            triggered.append("1h")

        return triggered

    def run(self, stop_event=None) -> None:
        """
        スケジューラのメインループを開始する。

        Ctrl+C または stop_event.set() で停止。

        Args:
            stop_event: threading.Event。セットされたらループを終了する。
                        None の場合は KeyboardInterrupt のみで停止。
        """
        self._running = True
        logger.info("ForwardScheduler 起動（SLEEP_INTERVAL=%ds）", SLEEP_INTERVAL_SECONDS)
        print(f"ForwardScheduler 起動 (チェック間隔: {SLEEP_INTERVAL_SECONDS}秒)")
        print("停止するには Ctrl+C を押してください")

        try:
            while self._running:
                if stop_event is not None and stop_event.is_set():
                    logger.info("stop_event を検知してスケジューラを停止します")
                    break

                self.check_and_trigger()

                time.sleep(SLEEP_INTERVAL_SECONDS)

        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt: スケジューラを停止します")
            print("\nForwardScheduler 停止")
        finally:
            self._running = False

    def stop(self) -> None:
        """スケジューラのメインループを停止する。"""
        self._running = False
        logger.info("ForwardScheduler 停止要求")
