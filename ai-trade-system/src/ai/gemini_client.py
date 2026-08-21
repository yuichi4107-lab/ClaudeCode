"""
ステップ2: Gemini APIを使ったチャートパターン画像判定
"""
import os
import json
import time
import google.generativeai as genai
from PIL import Image
from dotenv import load_dotenv

# .env読み込み（プロジェクトルートから）
load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env"))

PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "prompts")


def setup_gemini():
    """Gemini APIの初期設定"""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY が .env に設定されていません")
    genai.configure(api_key=api_key)
    return genai.GenerativeModel("gemini-2.5-flash")


def load_prompt(pattern_name="double_bottom"):
    """プロンプトファイルを読み込む"""
    prompt_path = os.path.join(PROMPTS_DIR, f"{pattern_name}.txt")
    if not os.path.exists(prompt_path):
        raise FileNotFoundError(f"プロンプトファイルが見つかりません: {prompt_path}")
    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read()


def judge_chart_image(image_path, pattern_name="double_bottom", model=None):
    """
    1枚のチャート画像をGeminiで判定する。

    Args:
        image_path: チャート画像のパス
        pattern_name: 判定するパターン名（prompts/下のファイル名）
        model: Geminiモデルインスタンス（Noneなら新規作成）
    Returns:
        dict: {"detected": 0 or 1, "raw_response": str}
    """
    if model is None:
        model = setup_gemini()

    prompt = load_prompt(pattern_name)
    img = Image.open(image_path)

    response = model.generate_content([prompt, img])
    raw_text = response.text.strip()

    # JSONを抽出
    detected = parse_detection_result(raw_text)

    return {
        "detected": detected,
        "raw_response": raw_text,
        "image": os.path.basename(image_path),
        "pattern": pattern_name,
    }


def parse_detection_result(text):
    """
    Geminiの応答からdetected値を抽出する。
    JSONが崩れている場合にも対応。
    """
    # まずJSON直接パース
    try:
        data = json.loads(text)
        return int(data.get("detected", 0))
    except (json.JSONDecodeError, ValueError):
        pass

    # JSON部分を探す
    import re
    match = re.search(r'\{[^}]*"detected"\s*:\s*(\d)[^}]*\}', text)
    if match:
        return int(match.group(1))

    # "1" or "0" だけの場合
    text_clean = text.strip().strip("`").strip()
    if text_clean in ("1", "0"):
        return int(text_clean)

    # パースできない場合は0（未検出）
    print(f"  Warning: Could not parse response: {text[:100]}")
    return 0


def judge_batch(image_paths, pattern_name="double_bottom", delay=1.0):
    """
    複数画像を順次判定する。

    Args:
        image_paths: 画像パスのリスト
        pattern_name: パターン名
        delay: API呼び出し間の待機秒数（レート制限対策）
    Returns:
        list of dict
    """
    model = setup_gemini()
    results = []

    print(f"Judging {len(image_paths)} images for pattern: {pattern_name}")

    for i, path in enumerate(image_paths):
        try:
            result = judge_chart_image(path, pattern_name, model)
            results.append(result)

            status = "DETECTED" if result["detected"] == 1 else "---"
            print(f"  [{i+1}/{len(image_paths)}] {result['image']}: {status}")

        except Exception as e:
            print(f"  [{i+1}/{len(image_paths)}] ERROR: {e}")
            results.append({
                "detected": 0,
                "raw_response": f"ERROR: {e}",
                "image": os.path.basename(path),
                "pattern": pattern_name,
                "error": True,
            })

        # レート制限対策
        if i < len(image_paths) - 1:
            time.sleep(delay)

    detected_count = sum(1 for r in results if r["detected"] == 1)
    print(f"\nDone: {detected_count}/{len(results)} detected")

    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Judge chart pattern with Gemini")
    parser.add_argument("image", help="Chart image path (or directory)")
    parser.add_argument("--pattern", default="double_bottom", help="Pattern name")
    parser.add_argument("--delay", type=float, default=1.0, help="Delay between API calls (sec)")
    args = parser.parse_args()

    if os.path.isdir(args.image):
        # ディレクトリ指定 → 中のPNG全部
        paths = sorted([
            os.path.join(args.image, f)
            for f in os.listdir(args.image)
            if f.endswith(".png") and not f.startswith("_")
        ])
        results = judge_batch(paths, args.pattern, args.delay)

        # 結果保存
        out_path = os.path.join(args.image, f"_results_{args.pattern}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"Results saved: {out_path}")
    else:
        result = judge_chart_image(args.image, args.pattern)
        print(json.dumps(result, indent=2, ensure_ascii=False))
