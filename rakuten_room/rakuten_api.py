"""楽天ウェブサービス(openapi.rakuten.co.jp)クライアント。

2026年の新API仕様に対応:
  - エンドポイントは openapi.rakuten.co.jp 配下(旧 app.rakuten.co.jp は廃止)
  - applicationId + accessKey の2点認証
  - Webアプリケーション型のアプリはReferer/Originチェックがあるため、
    「許可されたWebサイト」に登録したドメインをヘッダーで送る必要がある

認証情報は環境変数から読む(コードに直書きしない):
  RAKUTEN_APP_ID          アプリID (UUID形式)
  RAKUTEN_ACCESS_KEY      アクセスキー (pk_...)
  RAKUTEN_ALLOWED_DOMAIN  「許可されたWebサイト」に登録したドメイン (例: example.com)
  RAKUTEN_AFFILIATE_ID    楽天アフィリエイトID (任意。指定すると affiliateUrl が返る)
"""
import json
import os
import time
import urllib.parse
import urllib.request

RANKING_URL = "https://openapi.rakuten.co.jp/ichibaranking/api/IchibaItem/Ranking/20220601"
SEARCH_URL = "https://openapi.rakuten.co.jp/ichibams/api/IchibaItem/Search/20220601"
REQUEST_INTERVAL_SEC = 1.0

_last_request_at = 0.0


class RakutenApiError(RuntimeError):
    pass


def _credentials() -> dict:
    app_id = os.environ.get("RAKUTEN_APP_ID")
    access_key = os.environ.get("RAKUTEN_ACCESS_KEY")
    if not app_id or not access_key:
        raise RakutenApiError(
            "環境変数 RAKUTEN_APP_ID / RAKUTEN_ACCESS_KEY を設定してください"
        )
    params = {"applicationId": app_id, "accessKey": access_key, "format": "json"}
    affiliate_id = os.environ.get("RAKUTEN_AFFILIATE_ID")
    if affiliate_id:
        params["affiliateId"] = affiliate_id
    return params


def _request(url: str, params: dict) -> dict:
    global _last_request_at
    wait = REQUEST_INTERVAL_SEC - (time.time() - _last_request_at)
    if wait > 0:
        time.sleep(wait)

    domain = os.environ.get("RAKUTEN_ALLOWED_DOMAIN", "example.com")
    query = {**_credentials(), **params}
    req = urllib.request.Request(
        f"{url}?{urllib.parse.urlencode(query)}",
        headers={
            "Referer": f"https://{domain}/",
            "Origin": f"https://{domain}",
            "User-Agent": "rakuten-room-tool/1.0",
        },
    )
    _last_request_at = time.time()
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300]
        raise RakutenApiError(f"HTTP {e.code}: {body}") from e


def fetch_ranking(genre_id: str = None, page: int = 1, **extra) -> list:
    """ジャンル別売れ筋ランキングを取得する(1ページ30件、pageは1〜34)。"""
    params = {"page": page, **extra}
    if genre_id:
        params["genreId"] = genre_id
    data = _request(RANKING_URL, params)
    return [row.get("Item", row) for row in data.get("Items", [])]


def search_items(**params) -> list:
    """商品検索。sort例: '-reviewCount', '-affiliateRate', '-updateTimestamp'"""
    data = _request(SEARCH_URL, params)
    return [row.get("Item", row) for row in data.get("Items", [])]
