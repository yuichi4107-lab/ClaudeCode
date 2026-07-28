"""
ステップ1-3 & ステップ3-1: ローソク足チャート画像を自動生成する
- 手動切り出しはHTMLで行う（index.html）
- このスクリプトはバックテスト用に、スライドウィンドウで大量画像を自動生成する
"""
import os
import json
import math
from PIL import Image, ImageDraw

DATA_DIR = os.path.join(os.path.dirname(__file__), "../../data")
CHARTS_DIR = os.path.join(DATA_DIR, "charts")


def load_candles(json_path):
    """JSONファイルからローソク足データを読み込む"""
    with open(json_path, "r") as f:
        return json.load(f)


def draw_candlestick_chart(candles, size=512):
    """
    ローソク足データから正方形のチャート画像を生成する。

    Args:
        candles: OHLCVデータのリスト
        size: 出力画像のサイズ（正方形）
    Returns:
        PIL.Image
    """
    img = Image.new("RGB", (size, size), "#1a1a2e")
    draw = ImageDraw.Draw(img)

    if not candles:
        return img

    padding = {"top": 15, "bottom": 15, "left": 10, "right": 10}
    chart_w = size - padding["left"] - padding["right"]
    chart_h = size - padding["top"] - padding["bottom"]

    n = len(candles)
    candle_w = max(1, chart_w // n - 1)
    gap = max(1, (chart_w - candle_w * n) // max(1, n - 1))

    # 価格レンジ
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    max_price = max(highs)
    min_price = min(lows)
    price_range = max_price - min_price
    if price_range == 0:
        price_range = 1
    pad_price = price_range * 0.05
    max_price += pad_price
    min_price -= pad_price
    price_range = max_price - min_price

    def price_to_y(price):
        return int(padding["top"] + chart_h * (1 - (price - min_price) / price_range))

    # 描画
    for i, c in enumerate(candles):
        x = padding["left"] + i * (candle_w + gap)
        cx = x + candle_w // 2
        is_up = c["close"] >= c["open"]
        color = "#26a69a" if is_up else "#ef5350"

        # ヒゲ
        y_high = price_to_y(c["high"])
        y_low = price_to_y(c["low"])
        draw.line([(cx, y_high), (cx, y_low)], fill=color, width=1)

        # 実体
        y_open = price_to_y(c["open"])
        y_close = price_to_y(c["close"])
        body_top = min(y_open, y_close)
        body_bot = max(y_open, y_close)
        if body_bot - body_top < 1:
            body_bot = body_top + 1
        draw.rectangle([(x, body_top), (x + candle_w, body_bot)], fill=color)

    return img


def generate_sliding_images(
    json_path,
    window_size=50,
    step=5,
    image_size=512,
    output_dir=None,
):
    """
    スライドウィンドウ方式でチャート画像を連続生成する。

    Args:
        json_path: OHLCVデータのJSONパス
        window_size: 1画像に含むローソク足の本数
        step: スライド幅
        image_size: 出力画像サイズ（正方形）
        output_dir: 出力先ディレクトリ
    Returns:
        生成した画像パスとメタデータのリスト
    """
    candles = load_candles(json_path)
    if output_dir is None:
        output_dir = CHARTS_DIR
    os.makedirs(output_dir, exist_ok=True)

    results = []
    total = (len(candles) - window_size) // step + 1
    print(f"Generating {total} chart images (window={window_size}, step={step})...")

    for i in range(0, len(candles) - window_size + 1, step):
        window = candles[i : i + window_size]
        img = draw_candlestick_chart(window, size=image_size)

        filename = f"chart_{i:05d}.png"
        filepath = os.path.join(output_dir, filename)
        img.save(filepath)

        # メタデータ: バックテストで使う
        entry_candle = candles[i + window_size - 1]  # 最後のローソク足
        meta = {
            "index": i,
            "file": filename,
            "start_ts": candles[i].get("datetime", candles[i].get("timestamp")),
            "end_ts": entry_candle.get("datetime", entry_candle.get("timestamp")),
            "entry_price": entry_candle["close"],
        }
        results.append(meta)

        if (len(results) % 50 == 0) or (len(results) == total):
            print(f"  {len(results)}/{total} generated")

    # メタデータ保存
    meta_path = os.path.join(output_dir, "_metadata.json")
    with open(meta_path, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"Metadata saved: {meta_path}")

    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate chart images for backtest")
    parser.add_argument("json_path", help="Path to OHLCV JSON file")
    parser.add_argument("--window", type=int, default=50, help="Candles per image")
    parser.add_argument("--step", type=int, default=5, help="Slide step")
    parser.add_argument("--size", type=int, default=512, help="Image size (px)")
    parser.add_argument("--output", default=None, help="Output directory")
    args = parser.parse_args()

    generate_sliding_images(args.json_path, args.window, args.step, args.size, args.output)
