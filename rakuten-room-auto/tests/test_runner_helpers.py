from __future__ import annotations

from rakuten_room_auto.config import load_config
from rakuten_room_auto.replenish import (
    build_description,
    clean_item_title,
    contains_exaggerated_claim,
    is_duplicate_product,
    is_same_shop_variant,
    product_similarity,
)
from rakuten_room_auto.runner import (
    collect_all_urls,
    collect_completed_urls,
    count_pipeline_rows,
    short_error,
    validate_product_url_format,
)
from rakuten_room_auto.sheets import SheetTable


def test_short_error_compacts_message():
    message = short_error(RuntimeError("line1\nline2  line3"))
    assert message == "line1 line2 line3"


def test_clean_item_title_removes_promo_noise():
    title = "【マラソン限定!5%OFFクーポン】 高反発 マットレス 三つ折り 送料無料 ポイント10倍"
    name = clean_item_title(title)
    assert "クーポン" not in name
    assert "送料無料" not in name
    assert "マットレス" in name


def test_clean_item_title_removes_exaggerated_claims():
    title = "【楽天1位】No.1 業界最高 圧倒的 人気 収納ボックス 折りたたみ"
    name = clean_item_title(title)
    assert "No.1" not in name
    assert "業界最高" not in name
    assert "圧倒的" not in name
    assert "収納ボックス" in name
    description = build_description("楽天総合1位 6年連続No.1 最強 マットレス 高反発", 0)
    assert not contains_exaggerated_claim(description)
    assert "マットレス" in description


def test_build_description_falls_back_when_title_is_all_noise():
    description = build_description("【限定】No.1 最強 圧倒的 奇跡", 0)
    assert not contains_exaggerated_claim(description)
    assert description


def test_build_description_rotates_and_limits():
    title = "【限定】収納ボックス 折りたたみ ふた付き"
    first = build_description(title, 0, max_chars=180)
    second = build_description(title, 1, max_chars=180)
    assert first != second
    assert "収納ボックス" in first
    assert len(first) <= 180


def test_count_pipeline_rows_counts_only_pending_statuses():
    config = load_config()
    columns = config.sheet.columns
    values = [
        [columns["product_url"], columns["status"]],
        ["https://item.rakuten.co.jp/shop/a/", config.statuses.unposted],
        ["https://item.rakuten.co.jp/shop/b/", config.statuses.approval_pending],
        ["https://item.rakuten.co.jp/shop/c/", config.statuses.approved],
        ["https://item.rakuten.co.jp/shop/d/", ""],
        ["https://item.rakuten.co.jp/shop/e/", config.statuses.completed],
        ["https://item.rakuten.co.jp/shop/f/", config.statuses.needs_review],
        ["", config.statuses.unposted],
    ]
    table = SheetTable.from_values(values)
    assert count_pipeline_rows(table, config) == 4
    assert len(collect_all_urls(table, config)) == 6


def test_product_similarity_detects_same_product():
    # 実際にROOMでかぶった2商品の紹介文（同一商品とみなすべき）
    glove_a = "使い捨てニトリル手袋100枚入り。料理や掃除、ウイルス対策などマルチに活躍する高品質グローブです。"
    glove_b = "ニトリル手袋100枚入り。丈夫で破れにくい高品質タイプ。掃除や料理、DIYに欠かせません。"
    assert product_similarity(glove_a, glove_b) >= 0.25
    # 別商品（同じ収納カテゴリでも同一とみなすべきでない）
    box = "収納ボックス 収納ケース チェスト 折りたたみ 収納 ふた付き キャスター付き"
    closet = "クローゼットが劇的に片付く！ライクイットの収納ケースでスッキリ整理整頓"
    assert product_similarity(box, closet) < 0.25
    pillow = "枕 枕カバー 付 ヒツジのいらない枕 ギフト 実用的 健康グッズ"
    blanket = "NERUS 正規品 とろとろケット 洗える 掛け布団"
    assert product_similarity(pillow, blanket) < 0.25


def test_is_same_shop_variant():
    assert is_same_shop_variant(
        "https://item.rakuten.co.jp/tenkapas/glove001/", "https://item.rakuten.co.jp/tenkapas/glove002/"
    )
    assert not is_same_shop_variant(
        "https://item.rakuten.co.jp/shop-a/glove001/", "https://item.rakuten.co.jp/shop-b/glove001/"
    )
    assert not is_same_shop_variant(
        "https://item.rakuten.co.jp/tenkapas/glove001/", "https://item.rakuten.co.jp/tenkapas/apron5/"
    )


def test_fallback_descriptions_are_not_treated_as_duplicates():
    # 別商品だが、どちらも誇大表現のみのタイトルでフォールバック文言に落ちるケース。
    # フォールバック同士の完全一致で誤って同一商品と判定されてはならない
    from rakuten_room_auto.replenish import FALLBACK_NAME

    desc_a = build_description("【限定】No.1 最強 圧倒的 奇跡", 0)
    desc_b = build_description("究極 至高 完璧 絶対 万能", 1)
    assert FALLBACK_NAME in desc_a and FALLBACK_NAME in desc_b  # 前提: 両方フォールバック
    assert product_similarity(desc_a, desc_b) < 0.28
    existing = [("https://item.rakuten.co.jp/shop-a/pillow1/", desc_a)]
    assert not is_duplicate_product("https://item.rakuten.co.jp/shop-b/box1/", desc_b, existing)


def test_is_duplicate_product_combines_url_and_text_rules():
    existing = [("https://item.rakuten.co.jp/tenkapas/glove001/", "使い捨てニトリル手袋100枚入り。料理や掃除に。")]
    # 同ショップ型番違い（紹介文が全く違ってもURLルールで検出）
    assert is_duplicate_product("https://item.rakuten.co.jp/tenkapas/glove002/", "別の紹介文", existing)
    # 別ショップでも紹介文が同一商品なら検出
    assert is_duplicate_product(
        "https://item.rakuten.co.jp/other-shop/nitrile100/", "ニトリル手袋100枚入り。丈夫で破れにくい高品質タイプ。掃除や料理に。", existing
    )
    # 無関係な商品は通す
    assert not is_duplicate_product(
        "https://item.rakuten.co.jp/other-shop/pillow1/", "ヒツジのいらない枕 健康グッズ ギフト", existing
    )


def test_validate_product_url_format():
    assert validate_product_url_format("https://item.rakuten.co.jp/shop/item-a/") is None
    assert validate_product_url_format("https://books.rakuten.co.jp/rb/12345/") is None
    assert "楽天のURL" in validate_product_url_format("https://example.com/item/")
    assert "形式が不正" in validate_product_url_format("item.rakuten.co.jp/shop/item-a/")
    assert "楽天のURL" in validate_product_url_format("https://rakuten.co.jp.evil.com/item/")


def test_browser_error_messages_are_japanese():
    import ast
    import inspect
    import re

    from rakuten_room_auto import browser

    source = inspect.getsource(browser)
    japanese = re.compile(r"[ぁ-んァ-ン一-龥]")
    tree = ast.parse(source)
    raised: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
            for arg in node.exc.args:
                literals = [
                    part.value
                    for part in ast.walk(arg)
                    if isinstance(part, ast.Constant) and isinstance(part.value, str)
                ]
                if any(text.strip() for text in literals):
                    raised.append("".join(literals))
    assert raised, "raise文のメッセージが見つかりません"
    non_japanese = [msg for msg in raised if not japanese.search(msg)]
    assert not non_japanese, f"日本語化されていないエラーメッセージ: {non_japanese}"


def test_collect_completed_urls_only_completed_rows():
    config = load_config()
    columns = config.sheet.columns
    values = [
        [columns["product_url"], columns["status"]],
        ["https://item.rakuten.co.jp/shop/item-a/", config.statuses.completed],
        ["https://item.rakuten.co.jp/shop/item-b/", config.statuses.approved],
        ["", config.statuses.completed],
    ]
    table = SheetTable.from_values(values)
    assert collect_completed_urls(table, config) == {"https://item.rakuten.co.jp/shop/item-a/"}
