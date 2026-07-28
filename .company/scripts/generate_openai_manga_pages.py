import argparse
import base64
import csv
import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path

from openai import OpenAI


PROJECT_ROOT = Path(r"G:\マイドライブ\YNFactory-cc")
BOOK_ROOT = PROJECT_ROOT / ".company" / "outputs" / "ebooks-manga" / "chatgpt55-now-only-manga"
CSV_ROOT = BOOK_ROOT / "panels" / "comicle_scene_split" / "csv"
TEMPLATE_ROOT = BOOK_ROOT / "共通テンプレ"
OUTPUT_ROOT = BOOK_ROOT / "pages_openai_generated"

CSV_FILES = [
    "scene_04_p023-029_ch2_cases_steps12.csv",
    "scene_05_p030-034_ch2_steps34_objections.csv",
    "scene_07_p043-049_ch3_tests_usecases.csv",
    "scene_08_p050-052_ch3_return_timing.csv",
    "scene_09_p053-060_ch4_workflow_basic.csv",
    "scene_10_p061-065_ch4_prompts_examples.csv",
    "scene_11_p066-072_ch4_failures_improvement.csv",
    "scene_12_p073-080_ch5_strategy_first.csv",
    "scene_13_p081-088_ch5_strategy_second.csv",
    "scene_14_p089-092_ending_conclusion.csv",
    "scene_15_p093-096_supplement_ch2_ch3.csv",
    "scene_16_p097-103_supplement_ch4.csv",
    "scene_17_p104-107_supplement_ch5_action.csv",
    "scene_18_p108-115_recap_first.csv",
    "scene_19_p116-117_recap_second.csv",
    "scene_20_p118-120_author_book_info.csv",
]

CHARACTER_REFS = [
    TEMPLATE_ROOT / "高橋ミナ.png",
    TEMPLATE_ROOT / "佐伯レン.png",
    TEMPLATE_ROOT / "真田ユイ.png",
]


def load_api_key() -> str:
    key = os.environ.get("OPENAI_API_KEY")
    if key:
        return key

    bashrc = Path.home() / ".bashrc"
    if bashrc.exists():
        text = bashrc.read_text(encoding="utf-8", errors="ignore")
        match = re.search(
            r"(?:export\s+)?OPENAI_API_KEY\s*=\s*['\"]?([^'\"\s]+)",
            text,
        )
        if match:
            return match.group(1)

    raise RuntimeError("OPENAI_API_KEY is not set and was not found in ~/.bashrc")


def read_rows():
    for csv_name in CSV_FILES:
        csv_path = CSV_ROOT / csv_name
        with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                page = str(row["ページ番号"]).strip()
                template_name = str(row["使用するコマ割りテンプレ"]).strip()
                yield csv_name, page, template_name, row


def output_name(csv_name: str, page: str) -> str:
    scene = csv_name.split("_", 3)
    scene_id = f"{scene[0]}_{scene[1]}" if len(scene) >= 2 else Path(csv_name).stem
    return f"{scene_id}_p{int(page):03d}.png"


def build_prompt(row: dict, page: str, template_name: str) -> str:
    source_prompt = row["漫画作成のプロンプト"].replace('"""', "''")
    text_json = row.get("コマ別テキストJSON", "").replace('"""', "''")
    if template_name == "テキストページ":
        return f"""
あなたは商業出版向けの日本語書籍ページを制作するデザイナーです。
縦長2:3の白背景ページに、下記の日本語テキストだけを読みやすく配置してください。

ページ番号: {page}

重要ルール:
- フルカラーだが、白背景と黒文字を基調にした清潔な書籍ページ。
- 余計な英語、透かし、署名、ロゴ、ページ番号、装飾過多は禁止。
- 指定された本文以外の文字を追加しない。
- 文字は日本語として自然で読みやすく、行間を広めにする。

CSVプロンプト:
{source_prompt}
""".strip()

    return f"""
あなたは商業出版向けの日本語ビジネス漫画を制作する作画担当です。
添付1枚目のコマ割りテンプレートをページ全体のレイアウトとして厳密に使い、各白枠の中だけに絵を描いてください。
添付の人物参照画像にある3名の外見を維持してください。人物の顔、髪型、服装、年齢感、体型を安定させてください。

ページ番号: {page}
使用テンプレート: {template_name}

重要ルール:
- フルカラー、日本のアニメ・マンガ調、クリーンな線画、明るいデジタル彩色。
- 実写風、フォトリアル、3D、油彩風は禁止。
- テンプレートの黒枠、余白、縦長2:3のページ構成を保つ。
- 吹き出しと四角いナレーション枠は、指定された台詞とナレーションだけを日本語で読みやすく入れる。
- 【】で囲まれた語は感情や状況の指示であり、画像内の文字として描かない。
- 余計な英語、透かし、署名、ロゴ、ページ番号、説明文を描かない。
- 図解やフローチャートだけのページにせず、漫画の場面として成立させる。

CSVプロンプト:
{source_prompt}

配置すべきテキストJSON:
{text_json}
""".strip()


def generate_one(client: OpenAI, prompt: str, refs: list[Path], output_path: Path, model: str, quality: str):
    if refs:
        image_files = [p.open("rb") for p in refs]
        try:
            result = client.images.edit(
                model=model,
                image=image_files,
                prompt=prompt,
                size="1024x1536",
                quality=quality,
                n=1,
            )
        finally:
            for f in image_files:
                f.close()
    else:
        result = client.images.generate(
            model=model,
            prompt=prompt,
            size="1024x1536",
            quality=quality,
            n=1,
        )

    data = result.data or []
    if not data or not getattr(data[0], "b64_json", None):
        raise RuntimeError("No image returned by API")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(base64.b64decode(data[0].b64_json))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=os.environ.get("OPENAI_IMAGE_MODEL", "gpt-image-2"))
    parser.add_argument("--quality", default=os.environ.get("OPENAI_IMAGE_QUALITY", "medium"))
    parser.add_argument("--max-pages", type=int, default=0)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    rows = list(read_rows())
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    run_log = OUTPUT_ROOT / "generation_log.jsonl"

    missing = [p for p in CHARACTER_REFS if not p.exists()]
    for _, _, template_name, _ in rows:
        if template_name == "テキストページ":
            continue
        template_path = TEMPLATE_ROOT / f"{template_name}.jpg"
        if not template_path.exists():
            missing.append(template_path)
    if missing:
        for p in missing[:20]:
            print(f"ERROR missing reference: {p}")
        return 1

    print(f"TARGET_PAGES={len(rows)}")
    print(f"OUTPUT={OUTPUT_ROOT}")
    print(f"MODEL={args.model} QUALITY={args.quality}")
    if args.dry_run:
        return 0

    client = OpenAI(api_key=load_api_key())
    done = skipped = failed = 0

    for index, (csv_name, page, template_name, row) in enumerate(rows, start=1):
        if args.max_pages and index > args.max_pages:
            break

        out_path = OUTPUT_ROOT / output_name(csv_name, page)
        if out_path.exists() and not args.force:
            skipped += 1
            print(f"SKIP {index:03d}/{len(rows)} page={page} file={out_path.name}")
            continue

        refs = [] if template_name == "テキストページ" else [TEMPLATE_ROOT / f"{template_name}.jpg", *CHARACTER_REFS]
        prompt = build_prompt(row, page, template_name)
        record = {
            "timestamp": dt.datetime.now().isoformat(timespec="seconds"),
            "csv": csv_name,
            "page": page,
            "template": template_name,
            "output": str(out_path),
        }

        try:
            generate_one(client, prompt, refs, out_path, args.model, args.quality)
            done += 1
            record["status"] = "ok"
            print(f"OK   {index:03d}/{len(rows)} page={page} file={out_path.name}")
        except Exception as exc:
            failed += 1
            record["status"] = "error"
            record["error"] = str(exc)
            print(f"FAIL {index:03d}/{len(rows)} page={page} error={exc}")

        with run_log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        time.sleep(1)

    print(f"SUMMARY ok={done} skipped={skipped} failed={failed}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
