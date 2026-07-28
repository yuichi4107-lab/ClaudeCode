#!/usr/bin/env python3
"""
KDP表紙画像ジェネレーター
OpenAI gpt-image-2 (images.edit) を使って、キャラクターのリファレンス画像を元に
2:3 縦長 (1024x1536) PNG の書籍表紙を生成する。

Usage:
  python generate_cover.py \\
    --prompt-file path/to/cover_prompt.txt \\
    --char-refs path/to/chara_main.png path/to/chara_sub.png \\
    --out path/to/KDP出版用/cover.png

Requirements:
  - OPENAI_API_KEY environment variable
  - pip install openai
"""

import argparse
import base64
import os
import sys
from pathlib import Path


HARD_RULE = (
    "◆【絶対最優先】必ず日本のアニメ・マンガ調のイラストで描いてください。"
    "実写風・フォトリアル風は禁止です。\n\n"
)


def parse_args():
    p = argparse.ArgumentParser(description="Generate KDP cover image with gpt-image-2")
    p.add_argument("--prompt-file", required=True, help="Path to cover prompt text file (UTF-8)")
    p.add_argument("--char-refs", required=True, nargs="+", help="One or more character reference PNGs")
    p.add_argument("--out", required=True, help="Output PNG path")
    p.add_argument("--size", default="1024x1536", help="Image size (default: 1024x1536, 2:3 portrait)")
    p.add_argument("--quality", default="high", choices=["low", "medium", "high", "auto"])
    p.add_argument("--model", default="gpt-image-2", help="Model name (default: gpt-image-2)")
    return p.parse_args()


def main():
    args = parse_args()

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY is not set.", file=sys.stderr)
        sys.exit(1)

    prompt_path = Path(args.prompt_file)
    if not prompt_path.is_file():
        print(f"ERROR: prompt file not found: {prompt_path}", file=sys.stderr)
        sys.exit(1)

    char_paths = [Path(p) for p in args.char_refs]
    for cp in char_paths:
        if not cp.is_file():
            print(f"ERROR: character reference not found: {cp}", file=sys.stderr)
            sys.exit(1)
        if cp.suffix.lower() != ".png":
            print(f"WARNING: character reference is not .png: {cp}", file=sys.stderr)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    prompt_body = prompt_path.read_text(encoding="utf-8").strip()
    full_prompt = HARD_RULE + prompt_body

    try:
        from openai import OpenAI
    except ImportError:
        print("ERROR: openai package not installed. Run: pip install openai", file=sys.stderr)
        sys.exit(1)

    client = OpenAI(api_key=api_key)

    char_files = [open(p, "rb") for p in char_paths]
    try:
        image_arg = char_files[0] if len(char_files) == 1 else char_files

        print(f"[INFO] Generating cover via {args.model} ({args.size}, quality={args.quality})...")
        print(f"[INFO] Character refs: {[str(p) for p in char_paths]}")

        result = client.images.edit(
            model=args.model,
            image=image_arg,
            prompt=full_prompt,
            size=args.size,
            quality=args.quality,
            n=1,
        )
    finally:
        for f in char_files:
            try:
                f.close()
            except Exception:
                pass

    b64 = result.data[0].b64_json
    img_bytes = base64.b64decode(b64)
    out_path.write_bytes(img_bytes)
    print(f"[OK] Cover saved: {out_path} ({len(img_bytes)} bytes)")


if __name__ == "__main__":
    main()
