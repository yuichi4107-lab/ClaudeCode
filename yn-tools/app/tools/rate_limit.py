"""シンプルなインメモリIPレート制限（外部ライブラリ不要）"""

import time
from collections import defaultdict

# {ip: [timestamp, timestamp, ...]}
_requests: dict[str, list[float]] = defaultdict(list)


def check_rate_limit(ip: str, max_requests: int = 5, window_sec: int = 60) -> str | None:
    """レート制限チェック。超過時はエラーメッセージを返す。問題なければNone。"""
    now = time.time()
    cutoff = now - window_sec

    # 古いエントリを除去
    _requests[ip] = [t for t in _requests[ip] if t > cutoff]

    if len(_requests[ip]) >= max_requests:
        return f"リクエストが多すぎます。{window_sec}秒後に再試行してください。"

    _requests[ip].append(now)
    return None


def get_client_ip(request) -> str:
    """リクエストからクライアントIPを取得"""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
