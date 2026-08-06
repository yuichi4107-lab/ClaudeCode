"""商品データからROOM投稿文を自動生成するモジュール。

同じ文面の量産はいいねが付きにくい(analyze_room.py の分析結果)ため、
商品ごとに決定的に異なるパターンを選んで文章を組み立てる。
商品コードのハッシュでパターンを固定するので、同じ商品には常に同じ文が生成され、
再実行で文面がブレない。
"""
import hashlib
import re

_BRACKETS = re.compile(r"【[^】]*】|\[[^\]]*\]|［[^］]*］|＼[^／]*／|〔[^〕]*〕|\([^)]*\)|（[^）]*）")
_SPACES = re.compile(r"[\s/｜|]+")


def short_name(item_name: str, max_len: int = 26) -> str:
    """商品名からセール文言などの飾りを除き、先頭の意味のある部分を取り出す。"""
    cleaned = _BRACKETS.sub(" ", item_name or "")
    tokens = [t for t in _SPACES.split(cleaned) if t]
    out = ""
    for t in tokens:
        if out and len(out) + len(t) + 1 > max_len:
            break
        out = f"{out} {t}".strip()
    return out or (item_name or "")[:max_len]


def _pick(patterns: list, key: str, salt: str) -> str:
    digest = hashlib.md5(f"{salt}:{key}".encode()).digest()
    return patterns[digest[0] % len(patterns)]


def compose_post(item: dict, surge_label: str = "") -> str:
    """商品情報から投稿文(完成形)を生成する。"""
    name = short_name(item.get("itemName") or "")
    genre = (item.get("_genre_name") or "").split("・")[0]
    rank = item.get("rank")
    price = int(item.get("itemPrice") or 0)
    review_count = int(item.get("reviewCount") or 0)
    review_avg = item.get("reviewAverage")
    key = item.get("itemCode") or item.get("itemUrl") or name

    openers = [
        f"{name}、いま{genre}ジャンルのランキング{rank}位に入っている人気商品です。",
        f"{genre}ジャンルで売れている{name}をチェックしました。",
        f"最近気になっている{name}。ランキングでも{rank}位と好調みたいです。",
        f"{name}が楽天ランキング上位に入っていたのでご紹介。",
    ]
    if surge_label and "急上昇" in surge_label:
        openers = [
            f"{name}、ランキング急上昇中で注目度が上がっています。",
            f"いま伸びてる{name}。順位が一気に上がってきました。",
        ]

    reviews = []
    if review_count >= 100 and review_avg:
        reviews = [
            f"レビュー{review_count:,}件で評価★{review_avg}と安定の人気ぶり。",
            f"★{review_avg}({review_count:,}件)と口コミ評価も高めです。",
            f"{review_count:,}件のレビューが付いていて、評価は★{review_avg}。",
        ]
    elif review_count > 0 and review_avg:
        reviews = [f"レビュー評価は★{review_avg}({review_count}件)。"]

    prices = [
        f"価格は{price:,}円。",
        f"{price:,}円と手に取りやすい価格です。" if price < 5000 else f"価格は{price:,}円。",
    ]

    closers = [
        "気になった方はレビューもチェックしてみてください。",
        "お買い物マラソンのリスト入り候補にどうぞ。",
        "使い勝手が良さそうなので候補に入れました。",
        "セールのタイミングで狙うのも良さそうです。",
    ]

    parts = [_pick(openers, key, "o")]
    if reviews:
        parts.append(_pick(reviews, key, "r"))
    parts.append(_pick(prices, key, "p"))
    parts.append(_pick(closers, key, "c"))
    return "\n".join(parts)
