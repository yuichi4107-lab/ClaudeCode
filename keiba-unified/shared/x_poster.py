"""X(Twitter)自動投稿モジュール - 競馬予想のGeminiリライト + X投稿

設計方針 (2026-04-26 改修):
- スレッド (reply_chain) は **使わない** — X側の自動スパム/Bot抑制で
  4本目以降が `403 Forbidden: You are not permitted to perform this action`
  になる事象を回避するため、すべて独立した単発投稿として連続実行する。
- 長文は X の文字数制限 (重み280) を踏まえて chunk に分割する。日本語2ウェイト計算。
- chunk 間は 10 秒 sleep（連投スパム判定回避）。
- 1個失敗しても残りの chunk は試行する（grace continue）。
- 総数 > 1 の場合は末尾に「 (N/M)」を付与する（重複コンテンツ判定の保険）。
"""

import os
import json
import time
import logging
import requests
from requests_oauthlib import OAuth1

logger = logging.getLogger(__name__)

# Gemini API設定（ai-news-systemの.envから読む）
_GEMINI_API_KEY = None
_GEMINI_MODEL = "gemini-2.5-flash"
_GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models"

# X API設定（config/settings.pyから読む）
_x_auth = None

# X 単発ツイートの重み上限（X仕様 280、ページ番号余白を引いた安全側）
X_MAX_WEIGHT = 280
X_CHUNK_MAX_WEIGHT = 260  # ページ番号 " (NN/NN)" 最大10ウェイト分の余白
X_CHUNK_SLEEP_SECONDS = 10  # chunk間の sleep（spam判定回避）


def _load_gemini_key():
    """Gemini APIキーをロード（ai-news-systemの.envから）"""
    global _GEMINI_API_KEY
    if _GEMINI_API_KEY:
        return _GEMINI_API_KEY

    # 環境変数を優先
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        _GEMINI_API_KEY = key
        return key

    # ai-news-systemの.envからフォールバック
    env_path = "/opt/ai-news-system/.env"
    try:
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("GEMINI_API_KEY="):
                    _GEMINI_API_KEY = line.split("=", 1)[1].strip().strip('"').strip("'")
                    return _GEMINI_API_KEY
    except FileNotFoundError:
        logger.warning("Gemini .env not found: %s", env_path)
    return None


def _get_x_auth():
    """X API OAuth1認証を取得"""
    global _x_auth
    if _x_auth:
        return _x_auth

    try:
        from config.settings import (
            X_API_KEY, X_API_KEY_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET
        )
    except ImportError:
        logger.warning("X API設定が config/settings.py に見つかりません")
        return None

    if not all([X_API_KEY, X_API_KEY_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET]):
        logger.warning("X API認証情報が未設定です")
        return None

    _x_auth = OAuth1(X_API_KEY, X_API_KEY_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET)
    return _x_auth


def _call_gemini(prompt: str, text: str) -> str | None:
    """Gemini APIでテキストをリライトする"""
    api_key = _load_gemini_key()
    if not api_key:
        logger.error("Gemini APIキーが取得できません")
        return None

    url = f"{_GEMINI_ENDPOINT}/{_GEMINI_MODEL}:generateContent?key={api_key}"
    payload = {
        "contents": [{
            "parts": [{"text": f"{prompt}\n\n{text}"}]
        }],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 8192,
        }
    }

    try:
        resp = requests.post(url, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (requests.RequestException, KeyError, IndexError) as e:
        logger.error("Gemini API呼び出し失敗: %s", e)
        return None


def _post_tweet(text: str) -> str | None:
    """X APIに1ツイートを投稿する。成功時はtweet_idを返す。

    NOTE: reply_chain（スレッド）はX側のスパム抑制で 4本目以降が 403 に
    なるため使用禁止。常に独立した単発ツイートとして投稿する。
    """
    auth = _get_x_auth()
    if not auth:
        return None

    payload = {"text": text}

    try:
        resp = requests.post(
            "https://api.twitter.com/2/tweets",
            json=payload,
            auth=auth,
            timeout=15,
        )
        resp.raise_for_status()
        tweet_id = resp.json().get("data", {}).get("id")
        logger.info("X投稿完了: tweet_id=%s", tweet_id)
        return tweet_id
    except requests.RequestException as e:
        logger.error("X投稿エラー: %s", e)
        if hasattr(e, "response") and e.response is not None:
            logger.error("  詳細: %s", e.response.text)
        return None


# =====================================================================
# 文字数ウェイト計算 + chunk 分割（共通ヘルパー）
# =====================================================================

def _x_weight(text: str) -> int:
    """X投稿の文字数ウェイトを計算する（半角=1, 全角=2 の簡易版）。

    X の正式仕様では Latin/Spacing/Symbols は 1, それ以外（CJK等）は 2 で重み付け。
    日本語コンテンツ向けに簡略化: ASCII (cp < 128) を 1、それ以外を 2。
    """
    return sum(1 if ord(c) < 128 else 2 for c in text)


def _split_chunk_by_lines(segment: str, max_weight: int) -> list[str]:
    """1セグメントが max_weight を超える場合、改行単位でさらに分割する。

    1行も max_weight を超えるような極端ケースは強制的に文字単位カット。
    """
    if _x_weight(segment) <= max_weight:
        return [segment]

    chunks: list[str] = []
    buf = ""
    for line in segment.split("\n"):
        if not line.strip():
            # 空行も保持（既存 buf の段落区切りとして）
            candidate = (buf + "\n" + line) if buf else line
            if _x_weight(candidate) <= max_weight:
                buf = candidate
            else:
                if buf:
                    chunks.append(buf)
                buf = line
            continue

        # 1行単独で超える場合は文字単位で強制カット
        if _x_weight(line) > max_weight:
            if buf:
                chunks.append(buf)
                buf = ""
            piece = ""
            for ch in line:
                if _x_weight(piece + ch) > max_weight:
                    chunks.append(piece)
                    piece = ch
                else:
                    piece += ch
            if piece:
                buf = piece
            continue

        candidate = (buf + "\n" + line) if buf else line
        if _x_weight(candidate) <= max_weight:
            buf = candidate
        else:
            if buf:
                chunks.append(buf)
            buf = line

    if buf:
        chunks.append(buf)
    return chunks


def _chunk_for_x(text: str, max_weight: int = X_CHUNK_MAX_WEIGHT) -> list[str]:
    """Geminiリライト結果を X単発ツイート用 chunk に分割する。

    1) 「---」で論理セグメントに分割（Geminiが「概要」「1レース1ブロック」境界を提示する前提）
    2) **セグメント境界は絶対に跨がない**（1レースを跨ぐ結合をしない）
    3) 各セグメント内に限り、max_weight 内で複数行を結合
    4) 1セグメントが max_weight を超える場合のみ、そのセグメント内で改行単位分割
    """
    if not text:
        return []

    raw_segments = [s.strip() for s in text.split("---") if s.strip()]
    if not raw_segments:
        return []

    final_chunks: list[str] = []
    for seg in raw_segments:
        # セグメント自体が max_weight 内に収まれば即採用（最善ケース）
        if _x_weight(seg) <= max_weight:
            final_chunks.append(seg)
            continue

        # 超える場合のみ改行単位で分割し、同セグメント内に限り隣接結合
        pieces = _split_chunk_by_lines(seg, max_weight)
        buf = ""
        for piece in pieces:
            if not buf:
                buf = piece
                continue
            candidate = buf + "\n\n" + piece
            if _x_weight(candidate) <= max_weight:
                buf = candidate
            else:
                final_chunks.append(buf)
                buf = piece
        if buf:
            final_chunks.append(buf)

    return final_chunks


def _attach_page_marker(chunks: list[str]) -> list[str]:
    """総数 > 1 のとき各chunk末尾に「 (N/M)」を付与する（重複判定回避の保険）。"""
    total = len(chunks)
    if total <= 1:
        return chunks
    out: list[str] = []
    for i, chunk in enumerate(chunks, start=1):
        marker = f" ({i}/{total})"
        # 安全側: マーカー込みでも X_MAX_WEIGHT を超えないようガード
        weight = _x_weight(chunk) + _x_weight(marker)
        if weight > X_MAX_WEIGHT:
            # 想定外（chunk生成時にX_CHUNK_MAX_WEIGHTでマージン確保済み）が念の為
            logger.warning(
                "chunk %d/%d がマーカー込みで重み %d を超過、マーカー無しで投稿します",
                i, total, X_MAX_WEIGHT
            )
            out.append(chunk)
        else:
            out.append(chunk + marker)
    return out


def _post_tweet_chunks(
    chunks: list[str],
    dry_run: bool,
    sleep_seconds: int = X_CHUNK_SLEEP_SECONDS,
    label: str = "post",
) -> tuple[int, int]:
    """単発ツイートを連続投稿する（reply_chain なし、chunk間 sleep、grace continue）。

    Returns:
        (成功数, 総数)
    """
    total = len(chunks)
    if total == 0:
        logger.warning("[%s] chunk が空です", label)
        return (0, 0)

    chunks = _attach_page_marker(chunks)

    if dry_run:
        logger.info("=== X投稿ドライラン (%s, %d件) ===", label, total)
        for i, chunk in enumerate(chunks, start=1):
            logger.info("[%d/%d weight=%d]\n%s\n", i, total, _x_weight(chunk), chunk)
        return (total, total)

    success = 0
    for i, chunk in enumerate(chunks, start=1):
        tweet_id = _post_tweet(chunk)  # 単発投稿（reply_to なし）
        if tweet_id:
            success += 1
            logger.info("[%s] %d/%d 投稿完了 tweet_id=%s", label, i, total, tweet_id)
        else:
            logger.error("[%s] %d/%d 投稿失敗 — 続行します", label, i, total)
        # 最後以外は次の投稿前に sleep
        if i < total:
            time.sleep(sleep_seconds)

    logger.info("[%s] 投稿結果: %d/%d 成功", label, success, total)
    return (success, total)


# =====================================================================
# モーニング予想 → X 単発ツイート連投（chunk分割）
# =====================================================================

MORNING_PROMPT = """以下をX用の連続投稿テキストに整形してください。

【最重要】入力に登場する注目レース（◎○▲が付いているレース）は、**1件残らず全部** 出力すること。途中で打ち切らない。

【絶対ルール】
- 1ブロックは X単発ツイート相当（半角=1/全角=2 の重みで合計260以内）に必ず収める
- 1ブロック目は概要（日付・全R数・注目R数・配信時刻など短く）
- 2ブロック目以降は1レース1ブロック（注目レース全件、漏れなく）
- 各ブロックは必ず「---」で区切る
- 購入金額(円)は消す、オッズは残す、◎○▲は残す
- ブロック末尾のハッシュタグは **#競馬予想 #JRA の2個のみ**（増やさない）

【1レースブロックの圧縮フォーマット例（重み260厳守）】
*福島10R 尾瀬特別* (14:40) 品質0.84
◎3セボンサデ 3.0倍 / ○14ジュンラト 7.1倍 / ▲1ギマール 8.1倍
三連複:
1-3-14 17倍
2-3-14 23倍
1-2-3 26倍
3-14-15 30倍
3-8-14 30倍
1-3-15 34倍
2-3-15 46倍
3-8-15 59倍
#競馬予想 #JRA

【ポイント】
- 馬名は7文字以内に短縮可
- 買い目は1点1行、「1-3-14 17倍」形式（スペース・≈・小数点を全部削る）
- 三連複8点・馬連5点ともに全買い目を載せる
- ◎○▲ は1行にまとめる（"/" 区切り）

【出力】
完成形のみ。前置きや「以下の通りです」等の説明は不要。"""


def post_morning_to_x(telegram_text: str, dry_run: bool = False) -> bool:
    """モーニング予想をGeminiでリライトし、X に単発ツイートを連続投稿する。

    スレッド reply_chain は使わず、各 chunk を独立した単発ツイートとして
    10 秒間隔で投稿する。失敗しても残り chunk は試行する。

    Returns:
        投稿が1件以上成功すれば True、全滅なら False
    """
    try:
        rewritten = _call_gemini(MORNING_PROMPT, telegram_text)
        if not rewritten:
            logger.error("モーニング予想のリライト失敗")
            return False
        logger.debug("morning rewritten (%d chars):\n%s", len(rewritten), rewritten)

        chunks = _chunk_for_x(rewritten)
        if not chunks:
            logger.error("モーニング予想のchunk生成結果が空です")
            return False

        success, total = _post_tweet_chunks(chunks, dry_run=dry_run, label="morning")
        return success > 0

    except Exception as e:
        logger.error("モーニングX投稿で予期しないエラー: %s", e)
        return False


# =====================================================================
# 直前予想 → X単発ツイート（1レース1投稿、短文なのでchunk分割は通常不要）
# =====================================================================

LIVE_PROMPT = """以下の競馬予想を、X投稿用の短文に整形してください。

条件:
先頭に「🏇」
「投資」「金額」「≈配当」はすべて削除
本命・対抗・単穴は ◎ ○ ▲ で表記
買い目は番号だけを並べる
見出しは「阪神2R 3歳未勝利」のように簡潔に
距離は「ダ1800m」「芝1600m」のように省略
発走時刻は「発走 10:15」
出力は完成文のみ
コメントや分析は付けない
最後にハッシュタグを付ける"""


def post_live_to_x(telegram_text: str, dry_run: bool = False) -> bool:
    """直前予想をGeminiでリライトし、Xに単発投稿する。

    1レース分の短文だが、保険として X 文字数を超える場合は chunk 分割。
    """
    try:
        # 見送りレースはX投稿しない
        if "見送り" in telegram_text:
            logger.info("見送りレース — X投稿スキップ")
            return True

        rewritten = _call_gemini(LIVE_PROMPT, telegram_text)
        if not rewritten:
            logger.error("直前予想のリライト失敗")
            return False
        logger.debug("live rewritten (%d chars):\n%s", len(rewritten), rewritten)

        chunks = _chunk_for_x(rewritten)
        if not chunks:
            logger.error("直前予想のchunk生成結果が空です")
            return False

        success, _total = _post_tweet_chunks(chunks, dry_run=dry_run, label="live")
        return success > 0

    except Exception as e:
        logger.error("直前予想X投稿で予期しないエラー: %s", e)
        return False


# =====================================================================
# 穴予想（Longshot Wide）→ X 単発ツイート連投（chunk分割）
# =====================================================================

LONGSHOT_PROMPT = """以下の競馬穴予想を、X投稿用の短文（280字以内）に整形してください。

条件:
先頭に「🎯 穴予想」
「人気薄軸のワイド3点流し」を含める
1レース1行で簡潔に: 「阪神9R 軸③ヒコシグレ(7人気) 相手④⑩⑫」のように
丸数字（①②③...）はそのまま残す
馬名は短縮してよい
最後にハッシュタグ（#競馬予想 #穴予想 #AI競馬）
境界線（━）は削除
出力は完成文のみ、分析コメント不要"""


def post_longshot_to_x(telegram_text: str, dry_run: bool = False) -> bool:
    """穴予想（Longshot Wide）をGeminiでリライトし、X に単発ツイートを連続投稿する。

    レース数が多い時は chunk 分割（5レースごと程度）。chunk間 10秒 sleep。
    """
    try:
        rewritten = _call_gemini(LONGSHOT_PROMPT, telegram_text)
        if not rewritten:
            logger.error("穴予想のリライト失敗")
            return False
        logger.debug("longshot rewritten (%d chars):\n%s", len(rewritten), rewritten)

        chunks = _chunk_for_x(rewritten)
        if not chunks:
            logger.error("穴予想のchunk生成結果が空です")
            return False

        success, _total = _post_tweet_chunks(chunks, dry_run=dry_run, label="longshot")
        return success > 0

    except Exception as e:
        logger.error("穴予想X投稿で予期しないエラー: %s", e)
        return False
