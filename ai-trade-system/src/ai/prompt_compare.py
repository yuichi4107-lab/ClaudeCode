"""
プロンプト比較テスト: 複数プロンプトをサンプル画像で比較する
"""
import os
import sys
import json
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from ai.gemini_client import setup_gemini, load_prompt, parse_detection_result
from PIL import Image

CHARTS_DIR = os.path.join(os.path.dirname(__file__), "../../data/charts")


def compare_prompts(prompt_names, sample_indices=None, sample_count=20):
    """複数プロンプトを同じ画像セットで比較"""
    model = setup_gemini()

    # サンプル画像選択
    all_files = sorted([f for f in os.listdir(CHARTS_DIR) if f.endswith(".png") and not f.startswith("_")])

    if sample_indices:
        samples = [all_files[i] for i in sample_indices if i < len(all_files)]
    else:
        step = max(1, len(all_files) // sample_count)
        samples = all_files[::step][:sample_count]

    print(f"Comparing {len(prompt_names)} prompts on {len(samples)} images")
    print(f"Prompts: {prompt_names}")
    print()

    results = {p: [] for p in prompt_names}

    for i, filename in enumerate(samples):
        img_path = os.path.join(CHARTS_DIR, filename)
        img = Image.open(img_path)

        print(f"[{i+1}/{len(samples)}] {filename}:", end="")

        for pname in prompt_names:
            prompt = load_prompt(pname)
            try:
                response = model.generate_content([prompt, img])
                detected = parse_detection_result(response.text.strip())
            except Exception as e:
                print(f" ERR({pname})", end="")
                detected = -1

            results[pname].append({"file": filename, "detected": detected})
            print(f"  {pname}={'Y' if detected==1 else 'N'}", end="")
            time.sleep(0.5)

        print()

    # サマリー
    print("\n" + "=" * 60)
    print("COMPARISON SUMMARY")
    print("=" * 60)
    for pname in prompt_names:
        det = sum(1 for r in results[pname] if r["detected"] == 1)
        total = len(results[pname])
        print(f"  {pname}: {det}/{total} detected ({det/total*100:.0f}%)")

    # 詳細テーブル
    print("\n" + "-" * 60)
    header = "File".ljust(20) + "".join(p[-12:].rjust(14) for p in prompt_names)
    print(header)
    print("-" * 60)
    for i, filename in enumerate(samples):
        row = filename.ljust(20)
        for pname in prompt_names:
            val = results[pname][i]["detected"]
            row += ("YES" if val == 1 else "no" if val == 0 else "ERR").rjust(14)
        print(row)

    return results


if __name__ == "__main__":
    prompts = [
        "double_bottom",           # v1 (現行)
        "double_bottom_v2_strict",
        "double_bottom_v3_neckline",
        "double_bottom_v4_conservative",
    ]
    compare_prompts(prompts, sample_count=20)
