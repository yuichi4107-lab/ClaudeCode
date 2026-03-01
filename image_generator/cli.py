"""バッチ画像生成の CLI エントリーポイント.

使い方:
    # 単一画像
    python -m image_generator generate "かわいい猫のイラスト"

    # 複数画像（カンマ区切り）
    python -m image_generator generate "猫のイラスト" "犬のイラスト" "鳥のイラスト"

    # JSONファイルで一括指定
    python -m image_generator batch prompts.json

    # オプション指定
    python -m image_generator generate "風景画" --aspect-ratio 16:9 --output-dir ./output
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from image_generator.config import (
    DEFAULT_ASPECT_RATIO,
    DEFAULT_MODEL,
    DEFAULT_OUTPUT_DIR,
    MAX_CONCURRENT_REQUESTS,
    SUPPORTED_ASPECT_RATIOS,
)
from image_generator.generator import (
    BatchImageGenerator,
    ImageGenerator,
    ImageRequest,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="image_generator",
        description="NanoBanana2 (Gemini 3.1 Flash Image) バッチ画像生成ツール",
    )
    parser.add_argument(
        "--api-key", default=None,
        help="Gemini API キー (未指定時は環境変数 GEMINI_API_KEY を使用)",
    )
    parser.add_argument(
        "--model", default=DEFAULT_MODEL,
        help=f"使用モデル (デフォルト: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--output-dir", default=DEFAULT_OUTPUT_DIR,
        help=f"出力ディレクトリ (デフォルト: {DEFAULT_OUTPUT_DIR})",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- generate: プロンプトを直接指定 ---
    gen_parser = subparsers.add_parser(
        "generate", help="プロンプトを直接指定して画像生成",
    )
    gen_parser.add_argument(
        "prompts", nargs="+",
        help="生成する画像のプロンプト（複数指定可）",
    )
    gen_parser.add_argument(
        "--aspect-ratio", default=DEFAULT_ASPECT_RATIO,
        choices=SUPPORTED_ASPECT_RATIOS,
        help=f"アスペクト比 (デフォルト: {DEFAULT_ASPECT_RATIO})",
    )
    gen_parser.add_argument(
        "--style", default="",
        help="全プロンプトに共通のスタイル指示 (例: 'anime style', 'watercolor')",
    )
    gen_parser.add_argument(
        "--max-concurrent", type=int, default=MAX_CONCURRENT_REQUESTS,
        help=f"最大同時リクエスト数 (デフォルト: {MAX_CONCURRENT_REQUESTS})",
    )

    # --- batch: JSONファイルで一括指定 ---
    batch_parser = subparsers.add_parser(
        "batch", help="JSONファイルから一括生成",
    )
    batch_parser.add_argument(
        "json_file", help="リクエスト定義JSONファイルのパス",
    )
    batch_parser.add_argument(
        "--max-concurrent", type=int, default=MAX_CONCURRENT_REQUESTS,
        help=f"最大同時リクエスト数 (デフォルト: {MAX_CONCURRENT_REQUESTS})",
    )

    return parser


def run_generate(args: argparse.Namespace) -> None:
    """直接プロンプト指定で画像生成."""
    requests = [
        ImageRequest(
            prompt=prompt,
            aspect_ratio=args.aspect_ratio,
            style_prefix=args.style,
        )
        for prompt in args.prompts
    ]

    if len(requests) == 1:
        gen = ImageGenerator(
            api_key=args.api_key,
            model=args.model,
            output_dir=args.output_dir,
        )
        result = gen.generate(requests[0])
        _print_results([result])
    else:
        batch_gen = BatchImageGenerator(
            api_key=args.api_key,
            model=args.model,
            output_dir=args.output_dir,
            max_concurrent=args.max_concurrent,
        )
        results = batch_gen.generate_batch(requests)
        _print_results(results)


def run_batch(args: argparse.Namespace) -> None:
    """JSONファイルからバッチ生成.

    JSONフォーマット:
    [
        {
            "prompt": "かわいい猫",
            "filename": "cat.png",           // 省略可
            "aspect_ratio": "1:1",           // 省略可
            "style_prefix": "anime style"    // 省略可
        },
        ...
    ]
    """
    json_path = Path(args.json_file)
    if not json_path.exists():
        logger.error("ファイルが見つかりません: %s", json_path)
        sys.exit(1)

    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        logger.error("JSONはリスト形式である必要があります。")
        sys.exit(1)

    requests = []
    for item in data:
        if isinstance(item, str):
            requests.append(ImageRequest(prompt=item))
        elif isinstance(item, dict):
            requests.append(ImageRequest(
                prompt=item["prompt"],
                filename=item.get("filename"),
                aspect_ratio=item.get("aspect_ratio", DEFAULT_ASPECT_RATIO),
                style_prefix=item.get("style_prefix", ""),
            ))
        else:
            logger.warning("不正なエントリをスキップ: %s", item)

    if not requests:
        logger.error("有効なリクエストがありません。")
        sys.exit(1)

    logger.info("バッチ生成開始: %d 件のリクエスト", len(requests))
    start = time.time()

    batch_gen = BatchImageGenerator(
        api_key=args.api_key,
        model=args.model,
        output_dir=args.output_dir,
        max_concurrent=args.max_concurrent,
    )
    results = batch_gen.generate_batch(requests)

    total_time = time.time() - start
    logger.info("バッチ生成完了: 合計 %.1f秒", total_time)
    _print_results(results)


def _print_results(results: list) -> None:
    """結果サマリーを表示."""
    print("\n" + "=" * 60)
    print("画像生成結果")
    print("=" * 60)

    success_count = 0
    for i, result in enumerate(results, 1):
        status = "OK" if result.success else "NG"
        prompt_short = result.request.prompt[:50]
        if result.success:
            success_count += 1
            print(f"  [{status}] {i}. {prompt_short}")
            print(f"        -> {result.filepath} ({result.duration_sec:.1f}秒)")
        else:
            print(f"  [{status}] {i}. {prompt_short}")
            print(f"        エラー: {result.error}")

    print("-" * 60)
    print(f"成功: {success_count}/{len(results)}")
    print("=" * 60)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "generate":
        run_generate(args)
    elif args.command == "batch":
        run_batch(args)


if __name__ == "__main__":
    main()
