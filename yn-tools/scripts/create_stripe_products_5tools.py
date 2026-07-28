"""Stripe本番に5新ツール商品を作成し、Product/Price IDを取得して
stripe_live_product_ids.json にマージ保存する。

実行方法:
    cd yn-tools
    STRIPE_API_KEY=sk_live_xxxxx python scripts/create_stripe_products_5tools.py

または .env を読みたい場合:
    python scripts/create_stripe_products_5tools.py

対象ツール（display_order 32-36, 各100円/月）:
    32. jobposting  - 求人票ジェネレーター
    33. dataclean   - データクリーニングツール
    34. imgbatch    - 画像一括加工ツール
    35. stepmail    - ステップメール作成
    36. legalgen    - 契約書・利用規約自動作成
"""

import json
import os
import sys
from pathlib import Path

import stripe

ROOT = Path(__file__).resolve().parent.parent
IDS_FILE = ROOT / "stripe_live_product_ids.json"

NEW_TOOLS = [
    {"slug": "jobposting", "name": "YN Tools - 求人票ジェネレーター",       "description": "9業種テンプレートから Indeed/タウンワーク/ハローワーク形式の求人票をAI生成"},
    {"slug": "dataclean",  "name": "YN Tools - データクリーニングツール",   "description": "CSV/Excelの重複削除・表記揺れ統一・差分プレビュー"},
    {"slug": "imgbatch",   "name": "YN Tools - 画像一括加工ツール",          "description": "D&DでSNS9プリセットリサイズ・背景除去(rembg)・ZIP一括ダウンロード"},
    {"slug": "stepmail",   "name": "YN Tools - ステップメール作成ツール",     "description": "8種ビジネス目的からステップメールシリーズをAI一括生成・個別編集"},
    {"slug": "legalgen",   "name": "YN Tools - 契約書・利用規約自動作成",     "description": "7種の契約書/利用規約をAI生成。Word/PDF出力対応"},
]

UNIT_AMOUNT = 100  # JPY
INTERVAL = "month"


def load_existing() -> dict:
    if IDS_FILE.exists():
        return json.loads(IDS_FILE.read_text(encoding="utf-8"))
    return {}


def save(data: dict) -> None:
    IDS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    api_key = os.environ.get("STRIPE_API_KEY") or os.environ.get("STRIPE_SECRET_KEY")
    if not api_key:
        # try loading from .env
        env_path = ROOT / ".env"
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("STRIPE_SECRET_KEY="):
                    api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break

    if not api_key:
        print("ERROR: STRIPE_API_KEY が見つかりません。環境変数 or .env を設定してください。", file=sys.stderr)
        return 1

    if not api_key.startswith("sk_live_"):
        print(f"WARNING: live key ではありません ({api_key[:8]}...). 続行しますか？ [y/N]: ", end="")
        if input().strip().lower() != "y":
            return 1

    stripe.api_key = api_key
    existing = load_existing()

    for tool in NEW_TOOLS:
        slug = tool["slug"]
        if slug in existing and existing[slug].get("price_id"):
            print(f"[skip] {slug}: already exists (product={existing[slug]['product_id']})")
            continue

        print(f"[create] {slug}: {tool['name']}")
        product = stripe.Product.create(
            name=tool["name"],
            description=tool["description"],
            metadata={"slug": slug, "yn_tools": "true"},
        )
        price = stripe.Price.create(
            product=product.id,
            unit_amount=UNIT_AMOUNT,
            currency="jpy",
            recurring={"interval": INTERVAL},
        )
        existing[slug] = {"product_id": product.id, "price_id": price.id}
        save(existing)
        print(f"  -> product={product.id}  price={price.id}")

    print("\n=== 完了。新規 5 ツールの ID ===")
    for tool in NEW_TOOLS:
        slug = tool["slug"]
        ids = existing.get(slug, {})
        print(f'  ToolDefinition(slug="{slug}", ..., stripe_product_id="{ids.get("product_id")}", stripe_price_id="{ids.get("price_id")}")')
    return 0


if __name__ == "__main__":
    sys.exit(main())
