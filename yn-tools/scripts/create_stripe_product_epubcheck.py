"""Stripe（テスト or 本番）に epubcheck ツールの Product/Price を作成し、
適切な ids JSON ファイル（stripe_product_ids.json または stripe_live_product_ids.json）にマージ保存する。

実行方法:
    cd yn-tools
    python scripts/create_stripe_product_epubcheck.py
    # → STRIPE_SECRET_KEY を .env から自動読込
    #   sk_test_xxx → stripe_product_ids.json
    #   sk_live_xxx → stripe_live_product_ids.json

冪等: 既に slug が存在し price_id があればスキップ。

対象ツール:
    37. epubcheck - EPUBバリデーター (KDP出版前チェック、100円/月)
"""

import json
import os
import sys
from pathlib import Path

import stripe

ROOT = Path(__file__).resolve().parent.parent

TOOL = {
    "slug": "epubcheck",
    "name": "YN Tools - EPUBバリデーター",
    "description": "KDP出版前のEPUB破損・規格違反・表紙画像・フォント埋め込み・固定レイアウトを17項目で即時チェック。出版申請のリジェクトを未然に防ぎます。",
}

UNIT_AMOUNT = 100  # JPY
INTERVAL = "month"


def load_existing(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def save(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def detect_mode(api_key: str) -> tuple[str, Path]:
    """API キーから test/live を判定し、保存先 JSON を返す。"""
    if api_key.startswith("sk_test_"):
        return "test", ROOT / "stripe_product_ids.json"
    if api_key.startswith("sk_live_"):
        return "live", ROOT / "stripe_live_product_ids.json"
    raise ValueError(f"不明な API キープレフィックス: {api_key[:10]}...")


def get_api_key() -> str | None:
    api_key = os.environ.get("STRIPE_API_KEY") or os.environ.get("STRIPE_SECRET_KEY")
    if api_key:
        return api_key
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("STRIPE_SECRET_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def main() -> int:
    api_key = get_api_key()
    if not api_key:
        print("ERROR: STRIPE_SECRET_KEY が見つかりません。.env か環境変数を設定してください。", file=sys.stderr)
        return 1

    mode, ids_file = detect_mode(api_key)
    print(f"[mode] {mode}  (保存先: {ids_file.name})")

    stripe.api_key = api_key
    existing = load_existing(ids_file)

    slug = TOOL["slug"]
    if slug in existing and existing[slug].get("price_id"):
        print(f"[skip] {slug}: 既に登録済み (product={existing[slug]['product_id']} / price={existing[slug]['price_id']})")
        print("\n=== 既存ID ===")
        print(f'  product_id: {existing[slug]["product_id"]}')
        print(f'  price_id:   {existing[slug]["price_id"]}')
        return 0

    print(f"[create] {slug}: {TOOL['name']}")
    product = stripe.Product.create(
        name=TOOL["name"],
        description=TOOL["description"],
        metadata={"slug": slug, "yn_tools": "true"},
    )
    price = stripe.Price.create(
        product=product.id,
        unit_amount=UNIT_AMOUNT,
        currency="jpy",
        recurring={"interval": INTERVAL},
    )
    existing[slug] = {"product_id": product.id, "price_id": price.id}
    save(ids_file, existing)
    print(f"  -> product={product.id}")
    print(f"  -> price={price.id}")

    print(f"\n=== 完了 ({mode} mode) ===")
    print(f"  product_id: {product.id}")
    print(f"  price_id:   {price.id}")
    print(f"  saved to:   {ids_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
