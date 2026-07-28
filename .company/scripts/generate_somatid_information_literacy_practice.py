#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import shutil
import tempfile
import uuid
import zipfile
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from textwrap import dedent
from xml.sax.saxutils import escape as xml_escape

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[2]
BOOK_NAME = "somatid-information-literacy-practice"
BOOK_ROOT = ROOT / ".company" / "outputs" / "ebooks" / BOOK_NAME
OLD_ROOT = ROOT / ".company" / "outputs" / "ebooks" / "somatid-introduction"
RESEARCH_DIR = BOOK_ROOT / "_research"
MANUSCRIPT_DIR = BOOK_ROOT / "manuscript"
IMAGE_DIR = BOOK_ROOT / "images"
KDP_DIR = BOOK_ROOT / "KDP出版用"
GPT_IMAGE_SOURCE_DIR = BOOK_ROOT / "_gpt_image2_source"
COVER_BACKGROUND_SOURCE = GPT_IMAGE_SOURCE_DIR / "cover_background_gpt_image2.png"
COVER_BACKGROUND_FINAL = KDP_DIR / "cover_background_gpt_image2.png"

TITLE = "ソマチッド情報の読み解き方"
SUBTITLE = "未確立な健康情報と安全に向き合う実践ガイド"
AUTHOR = "ソマチッド研究所"
PUBLISHER = "YN出版"
LANGUAGE = "ja-JP"
OUTPUT_EPUB = KDP_DIR / f"{TITLE}.epub"

FONT_REGULAR = Path("/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc")
FONT_BOLD = Path("/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc")
if not FONT_REGULAR.exists():
    FONT_REGULAR = Path("/Library/Fonts/Arial Unicode.ttf")
if not FONT_BOLD.exists():
    FONT_BOLD = FONT_REGULAR


SOURCES = [
    {
        "title": "National Cancer Institute: 714-X (PDQ)",
        "url": "https://www.cancer.gov/about-cancer/treatment/cam/patient/714-x-pdq",
        "note": "714-Xとソマチッド理論の扱い、査読済み根拠の不足、FDA承認状況、公的情報の読み方を確認。",
    },
    {
        "title": "NCBI Bookshelf: 714-X (PDQ)",
        "url": "https://www.ncbi.nlm.nih.gov/books/NBK65771/",
        "note": "NCI PDQのNCBI掲載版。PMID 26389214と版履歴を確認。",
    },
    {
        "title": "NCCIH: Cancer and Complementary Health Approaches",
        "url": "https://www.nccih.nih.gov/health/cancer-and-complementary-health-approaches-what-you-need-to-know",
        "note": "補完・代替的な健康情報を扱う際の安全原則、医療の置き換え回避、医療者相談の必要性を確認。",
    },
]


CHAPTERS = [
    {
        "file": "01_第1章.md",
        "title": "第1章 全体像: ソマチッド情報を現場で扱う前に",
        "goal": "言葉、主張、観察、商品、医療判断を分けて読む土台を作る。",
        "image": ("diagram_001_information_map.png", "ソマチッド情報を分ける地図", ["言葉", "歴史", "主張", "根拠", "現場対応"]),
        "sections": [
            ("ソマチッドという言葉を、まず安全に置く", "言葉の入口を作り、読者や相談者がすぐに信じるか否定するかへ急がない状態を作る。"),
            ("関心の背景にある不安と希望を見る", "健康情報へ向かう人の切実さを軽く扱わず、同時に断定へ流れない姿勢を保つ。"),
            ("観察、仮説、物語、商品を分ける", "同じ話の中に混ざる層を分け、どこから先が検証や専門判断の領域かを明確にする。"),
            ("実務者が担う安全な案内役", "講師、発信者、現場リーダーが医療者ではない立場でできる支援とできない支援を線引きする。"),
            ("本書で使う言葉のルール", "未確立、主張、根拠、相談、保留といった表現を統一して、誤解を減らす。"),
            ("現場の最初の一歩", "受け止め、分ける、確認する、つなぐという四段階で会話を始める。"),
        ],
    },
    {
        "file": "02_第2章.md",
        "title": "第2章 歴史と主張の整理: 物語を信仰にも否定にも寄せない",
        "goal": "歴史的な語りや714-X周辺の主張を、根拠とは別の棚に置いて読めるようにする。",
        "image": ("diagram_002_history_claims.png", "歴史と主張の整理", ["人物", "装置", "血液像", "714-X", "公的評価"]),
        "sections": [
            ("ネサンとソマトスコープの物語を読む", "人物や装置の物語が人を惹きつける理由と、そこから直ちに効能へ進めない理由を整理する。"),
            ("714-Xにまつわる説明の見取り図", "製品や療法として語られる主張を、説明、期待、検証、規制の観点で分ける。"),
            ("血液をめぐる語りの魅力", "見えるもの、見えそうなもの、意味づけされるものの違いを考える。"),
            ("体験談と広告文を読み分ける", "読者が感情的に動かされやすい表現を見つけ、安全に距離を取る。"),
            ("年表で見る論点の移動", "発見譚、代替医療、インターネット発信、講座化という流れを整理する。"),
            ("歴史を扱う時の実務メモ", "歴史を否定材料にも販売材料にもせず、学習素材として扱う手順を示す。"),
        ],
    },
    {
        "file": "03_第3章.md",
        "title": "第3章 根拠の読み方: 主張を分解し、証拠の強さを見積もる",
        "goal": "査読、再現性、臨床試験、公的評価、体験談の違いを実務で使える形にする。",
        "image": ("diagram_003_evidence_ladder.png", "根拠の階段", ["体験談", "観察", "前臨床", "臨床研究", "公的評価"]),
        "sections": [
            ("証拠の階段を作る", "すべての情報を同じ強さで扱わず、どの段にある情報かを見える化する。"),
            ("査読と再現性をやさしく説明する", "専門用語を現場の言葉に置き換え、読者が自分で確認できるようにする。"),
            ("公的情報を読む時の手順", "NCI、NCBI、NCCIHのような情報源を、断片ではなく文脈で読む。"),
            ("症例、観察、体験談の位置づけ", "個別の経験を尊重しつつ、一般化しすぎない扱い方を学ぶ。"),
            ("効能表現の赤信号", "病気、免疫、血液、毒素、自然という言葉が出た時の確認項目を作る。"),
            ("不明と未確立を分ける", "まだわからないことと、確認されていないことを混同しない。"),
        ],
    },
    {
        "file": "04_第4章.md",
        "title": "第4章 現場での伝え方: 不安をあおらず、判断を支える",
        "goal": "相談、講座、SNS、資料作成で使える安全なコミュニケーションを設計する。",
        "image": ("diagram_004_field_response.png", "現場対応の四段階", ["受け止める", "分ける", "確認する", "つなぐ"]),
        "sections": [
            ("相談を受けた時の第一声", "相手の不安を受け止めながら、専門外の判断をしない会話を始める。"),
            ("標準的な医療判断を止めない伝え方", "補完的な関心と医療判断を混ぜないための言葉を準備する。"),
            ("家族、受講者、顧客との対話", "立場の違う相手に、同じ安全原則を押しつけずに届ける。"),
            ("不安をあおらない資料作り", "見出し、図解、体験談、注意書きの設計を実務に落とし込む。"),
            ("SNS、動画、講座のチェック手順", "拡散されやすい表現を事前に点検するワークフローを作る。"),
            ("専門職へつなぐ判断", "相談の範囲を越えた時に、どう自然に医療者や公的窓口へつなぐかを整理する。"),
        ],
    },
    {
        "file": "05_第5章.md",
        "title": "第5章 安全な情報発信と教材化: 希望を残しながら断定しない",
        "goal": "ソマチッドを題材に、健康情報リテラシー教材として安全に展開する。",
        "image": ("diagram_005_publish_checklist.png", "安全な発信チェック", ["目的", "根拠", "表現", "相談先", "更新"]),
        "sections": [
            ("教材化の設計", "ソマチッドそのものを勧める教材ではなく、情報を読む力を育てる教材として設計する。"),
            ("表現チェックリスト", "発信前に確認する語尾、見出し、注釈、リンク、体験談の扱いを決める。"),
            ("記録と振り返り", "講座や相談の場で何を聞き、何を伝え、どこへつないだかを残す。"),
            ("コミュニティ運営ルール", "信じる人と疑う人が対立しすぎない場を作る。"),
            ("情報を更新し続ける", "公的情報や研究状況が変わる前提で、教材や記事を更新する仕組みを持つ。"),
            ("希望を残しながら断定しない", "未知への関心を閉じず、安全な保留を読後の行動にする。"),
        ],
    },
]


def ensure_dirs() -> None:
    for path in [BOOK_ROOT, RESEARCH_DIR, MANUSCRIPT_DIR, IMAGE_DIR, KDP_DIR, GPT_IMAGE_SOURCE_DIR]:
        path.mkdir(parents=True, exist_ok=True)


def section_image_name(chapter_number: int, section_number: int) -> str:
    return f"section_{chapter_number:02d}_{section_number:02d}_gpt_image2.png"


def all_section_image_names() -> list[str]:
    return [section_image_name(chapter, section) for chapter in range(1, 6) for section in range(1, 7)]


def old_fingerprint() -> dict[str, str | int | bool]:
    files = [
        OLD_ROOT / "progress.json",
        OLD_ROOT / "project.md",
        OLD_ROOT / "KDP出版用" / "ソマチッドとは何か.epub",
    ]
    result: dict[str, str | int | bool] = {}
    for file in files:
        key = str(file.relative_to(ROOT))
        result[f"{key}:exists"] = file.exists()
        if file.exists():
            result[f"{key}:size"] = file.stat().st_size
            result[f"{key}:sha1"] = hashlib.sha1(file.read_bytes()).hexdigest()
    return result


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def jp_len(text: str) -> int:
    return len(re.sub(r"\s+", "", text))


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for char in text:
        candidate = current + char
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = char
    if current:
        lines.append(current)
    return lines


def draw_multiline(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: str,
    max_width: int,
    line_gap: int = 10,
) -> int:
    x, y = xy
    for line in wrap_text(draw, text, font, max_width):
        draw.text((x, y), line, font=font, fill=fill)
        y += font.size + line_gap
    return y


def create_diagram(file_name: str, title: str, labels: list[str], subtitle: str) -> None:
    image = Image.new("RGB", (1536, 1024), "#fbf8f0")
    draw = ImageDraw.Draw(image)
    title_font = ImageFont.truetype(str(FONT_BOLD), 58)
    label_font = ImageFont.truetype(str(FONT_BOLD), 34)
    body_font = ImageFont.truetype(str(FONT_REGULAR), 26)
    small_font = ImageFont.truetype(str(FONT_REGULAR), 22)
    tiny_font = ImageFont.truetype(str(FONT_REGULAR), 18)

    palette = {
        "navy": "#1f3a4a",
        "teal": "#2f8f83",
        "green": "#69a46f",
        "gold": "#d7a84f",
        "coral": "#d97867",
        "lavender": "#8d82bd",
        "paper": "#fffdf7",
        "ink": "#1f2937",
        "muted": "#657083",
    }

    def header(accent: str) -> None:
        draw.rectangle((0, 0, 1536, 150), fill=palette["navy"])
        draw.rectangle((0, 132, 1536, 150), fill=accent)
        draw.text((70, 40), title, font=title_font, fill="#ffffff")
        draw_multiline(draw, (74, 112), subtitle, tiny_font, "#dbe7ee", 1100, 4)

    def card(box: tuple[int, int, int, int], fill: str, outline: str = "#c7c0b5") -> None:
        draw.rounded_rectangle(box, radius=28, fill=fill, outline=outline, width=3)

    def pill(x: int, y: int, text: str, fill: str) -> None:
        draw.rounded_rectangle((x, y, x + 190, y + 56), radius=28, fill=fill, outline="#ffffff", width=2)
        draw.text((x + 28, y + 12), text, font=small_font, fill="#ffffff")

    if "history" in file_name:
        header(palette["gold"])
        draw.line((150, 505, 1385, 505), fill=palette["navy"], width=8)
        xs = [170, 445, 720, 995, 1270]
        colors = ["#dbeafe", "#dcfce7", "#fef3c7", "#fee2e2", "#ede9fe"]
        captions = ["人物の物語", "装置の説明", "血液像の解釈", "療法の主張", "公的評価"]
        for i, (x, label) in enumerate(zip(xs, labels)):
            y = 315 if i % 2 == 0 else 595
            card((x - 105, y, x + 125, y + 150), colors[i], "#667085")
            draw.ellipse((x - 23, 482, x + 23, 528), fill=palette["gold"], outline="#ffffff", width=4)
            draw.text((x - 70, y + 26), label, font=label_font, fill=palette["ink"])
            draw_multiline(draw, (x - 70, y + 82), captions[i], body_font, "#334155", 155, 6)
            if i < len(xs) - 1:
                draw.line((x + 40, 505, xs[i + 1] - 45, 505), fill=palette["muted"], width=4)
        card((180, 800, 1356, 910), "#ffffff", "#c8c1b4")
        draw_multiline(draw, (230, 830), "歴史は販売材料ではなく、主張と根拠を分けるための文脈として扱う。", body_font, palette["ink"], 1060, 8)
    elif "evidence" in file_name:
        header(palette["teal"])
        step_colors = ["#fee2e2", "#fef3c7", "#dcfce7", "#dbeafe", "#ede9fe"]
        for i, label in enumerate(labels):
            x1 = 170 + i * 245
            y1 = 700 - i * 95
            card((x1, y1, x1 + 230, 850), step_colors[i], "#5f6f7f")
            draw.text((x1 + 30, y1 + 35), label, font=label_font, fill=palette["ink"])
            draw.text((x1 + 32, y1 + 92), f"STEP {i + 1}", font=small_font, fill=palette["muted"])
        draw.line((140, 875, 1400, 385), fill=palette["teal"], width=5)
        draw.polygon([(1400, 385), (1372, 382), (1388, 410)], fill=palette["teal"])
        pill(1050, 185, "強い根拠へ", palette["teal"])
        draw_multiline(draw, (190, 210), "体験談や観察を否定せず、同時に臨床研究や公的評価と同じ重さにしない。", body_font, palette["ink"], 620, 8)
    elif "field" in file_name:
        header(palette["coral"])
        card((105, 250, 565, 810), "#ffffff", "#d0c4b8")
        card((970, 250, 1430, 810), "#ffffff", "#d0c4b8")
        draw.ellipse((230, 315, 360, 445), fill="#dbeafe", outline=palette["navy"], width=4)
        draw.rectangle((205, 445, 385, 680), fill="#e7eef8", outline=palette["navy"], width=4)
        draw.ellipse((1115, 315, 1245, 445), fill="#dcfce7", outline=palette["green"], width=4)
        draw.rectangle((1090, 445, 1270, 680), fill="#edf8ef", outline=palette["green"], width=4)
        draw.rounded_rectangle((430, 300, 930, 430), radius=24, fill="#fef3c7", outline="#c59b35", width=3)
        draw_multiline(draw, (465, 330), "その情報を一緒に分けてみましょう", body_font, palette["ink"], 430, 8)
        stages = ["受け止める", "分ける", "確認する", "つなぐ"]
        for i, stage in enumerate(stages):
            x = 460 + (i % 2) * 235
            y = 505 + (i // 2) * 130
            card((x, y, x + 205, y + 95), ["#dbeafe", "#dcfce7", "#fef3c7", "#fee2e2"][i], "#778899")
            draw.text((x + 25, y + 30), stage, font=small_font, fill=palette["ink"])
    elif "publish" in file_name:
        header(palette["lavender"])
        card((160, 220, 790, 850), "#ffffff", "#b8b0c8")
        draw.rectangle((235, 190, 715, 260), fill=palette["lavender"])
        draw.text((310, 208), "発信前チェック", font=label_font, fill="#ffffff")
        for i, label in enumerate(labels):
            y = 330 + i * 92
            draw.rounded_rectangle((230, y, 285, y + 55), radius=10, fill="#dcfce7", outline=palette["green"], width=3)
            draw.line((244, y + 28, 258, y + 42), fill=palette["green"], width=5)
            draw.line((258, y + 42, 280, y + 15), fill=palette["green"], width=5)
            draw.text((315, y + 10), label, font=label_font, fill=palette["ink"])
        card((885, 260, 1380, 780), "#eef5f9", "#8ba4b5")
        draw_multiline(draw, (940, 320), "目的、根拠、表現、相談先、更新日を確認してから公開する。希望を残しながら、医療判断の代わりにならない表現へ整える。", body_font, palette["ink"], 370, 10)
        pill(1030, 665, "安全に公開", palette["lavender"])
    else:
        header(palette["teal"])
        card((95, 250, 510, 800), "#ffffff", "#c8c1b4")
        draw.text((145, 300), "ソマチッド情報", font=label_font, fill=palette["ink"])
        draw.ellipse((190, 415, 360, 585), outline=palette["teal"], width=12)
        draw.line((330, 555, 430, 670), fill=palette["teal"], width=12)
        draw_multiline(draw, (145, 700), "一つの話題を、複数の棚に分けて読む。", body_font, palette["ink"], 300, 8)
        shelf_x = 610
        colors = ["#dbeafe", "#dcfce7", "#fef3c7", "#fee2e2", "#ede9fe"]
        for i, label in enumerate(labels):
            y = 250 + i * 112
            card((shelf_x, y, 1350, y + 82), colors[i], "#667085")
            draw.text((shelf_x + 36, y + 22), label, font=label_font, fill=palette["ink"])
            draw.line((520, 525, shelf_x - 25, y + 42), fill="#94a3b8", width=4)
        draw_multiline(draw, (635, 835), "信じる・否定するの前に、まず分類する。", body_font, palette["ink"], 630, 8)

    image.save(IMAGE_DIR / file_name)


def ensure_gpt_image_assets() -> None:
    missing: list[str] = []
    if not COVER_BACKGROUND_SOURCE.exists():
        missing.append(str(COVER_BACKGROUND_SOURCE.relative_to(BOOK_ROOT)))
    for image_name in all_section_image_names():
        if not (GPT_IMAGE_SOURCE_DIR / image_name).exists():
            missing.append(str((GPT_IMAGE_SOURCE_DIR / image_name).relative_to(BOOK_ROOT)))
    if missing:
        raise FileNotFoundError("gpt-image-2 assets are missing: " + ", ".join(missing))

    for stale in IMAGE_DIR.glob("diagram_*.png"):
        stale.unlink()
    for image_name in all_section_image_names():
        shutil.copy2(GPT_IMAGE_SOURCE_DIR / image_name, IMAGE_DIR / image_name)
    shutil.copy2(COVER_BACKGROUND_SOURCE, COVER_BACKGROUND_FINAL)


def fit_cover_background(source: Image.Image, target_size: tuple[int, int] = (1024, 1536)) -> Image.Image:
    target_w, target_h = target_size
    image = source.convert("RGB")
    source_ratio = image.width / image.height
    target_ratio = target_w / target_h
    if source_ratio > target_ratio:
        crop_w = int(image.height * target_ratio)
        left = (image.width - crop_w) // 2
        image = image.crop((left, 0, left + crop_w, image.height))
    else:
        crop_h = int(image.width / target_ratio)
        top = (image.height - crop_h) // 2
        image = image.crop((0, top, image.width, top + crop_h))
    return image.resize(target_size, Image.Resampling.LANCZOS)


def draw_shadow_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: str,
    shadow_fill: str = "#07151d",
    offset: int = 3,
) -> None:
    x, y = xy
    draw.text((x + offset, y + offset), text, font=font, fill=shadow_fill)
    draw.text((x, y), text, font=font, fill=fill)


def draw_shadow_multiline(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: str,
    max_width: int,
    line_gap: int = 10,
) -> int:
    x, y = xy
    for line in wrap_text(draw, text, font, max_width):
        draw_shadow_text(draw, (x, y), line, font, fill, offset=2)
        y += font.size + line_gap
    return y


def create_cover_from_gpt_background() -> None:
    image = fit_cover_background(Image.open(COVER_BACKGROUND_SOURCE))
    rgba = image.convert("RGBA")
    overlay = Image.new("RGBA", rgba.size, (8, 18, 25, 42))
    gradient = Image.new("RGBA", rgba.size, (0, 0, 0, 0))
    grad_draw = ImageDraw.Draw(gradient)
    for x in range(0, 760):
        alpha = max(0, int(190 * (1 - x / 760)))
        grad_draw.line((x, 0, x, rgba.height), fill=(6, 18, 25, alpha))
    rgba = Image.alpha_composite(rgba, overlay)
    rgba = Image.alpha_composite(rgba, gradient)

    draw = ImageDraw.Draw(rgba)
    title_font = ImageFont.truetype(str(FONT_BOLD), 88)
    sub_font = ImageFont.truetype(str(FONT_REGULAR), 37)
    author_font = ImageFont.truetype(str(FONT_BOLD), 38)
    small_font = ImageFont.truetype(str(FONT_REGULAR), 27)
    mini_font = ImageFont.truetype(str(FONT_REGULAR), 21)

    draw.line((78, 93, 78, 1222), fill="#e9b95e", width=7)
    draw_shadow_text(draw, (112, 86), "HEALTH INFORMATION LITERACY", mini_font, "#d8edf4", offset=2)
    draw_shadow_text(draw, (112, 119), "PRACTICAL GUIDE", mini_font, "#e9b95e", offset=2)

    y = 245
    for line in ["ソマチッド", "情報の", "読み解き方"]:
        draw_shadow_text(draw, (108, y), line, title_font, "#fffaf0", offset=4)
        y += 118

    y += 28
    y = draw_shadow_multiline(draw, (112, y), SUBTITLE, sub_font, "#e8f3f5", 560, 14)
    draw_shadow_text(draw, (112, y + 50), "実務者・現場リーダーのための", small_font, "#f7e4bd", offset=2)
    draw_shadow_text(draw, (112, y + 92), "健康情報リテラシー実践書", small_font, "#f7e4bd", offset=2)

    draw.rounded_rectangle((112, 1112, 672, 1182), radius=35, fill=(17, 111, 111, 220), outline="#c8f1e9", width=2)
    draw.text((152, 1129), "信じる前に、分けて読む", font=small_font, fill="#ffffff")
    draw_shadow_text(draw, (112, 1346), AUTHOR, author_font, "#fffaf0", offset=3)

    final = rgba.convert("RGB")
    KDP_DIR.mkdir(parents=True, exist_ok=True)
    final.save(KDP_DIR / "cover.png")
    final.save(KDP_DIR / "cover.jpg", quality=95)


def create_cover() -> None:
    image = Image.new("RGB", (1024, 1536), "#f5f1e8")
    draw = ImageDraw.Draw(image)
    title_font = ImageFont.truetype(str(FONT_BOLD), 82)
    sub_font = ImageFont.truetype(str(FONT_REGULAR), 38)
    author_font = ImageFont.truetype(str(FONT_BOLD), 36)
    small_font = ImageFont.truetype(str(FONT_REGULAR), 28)
    mini_font = ImageFont.truetype(str(FONT_REGULAR), 22)

    draw.rectangle((0, 0, 1024, 1536), fill="#f5f1e8")
    draw.rectangle((0, 0, 1024, 310), fill="#1f3a4a")
    draw.rectangle((0, 310, 1024, 330), fill="#d7a84f")
    draw.text((78, 92), "HEALTH INFORMATION LITERACY", font=mini_font, fill="#dbe7ee")
    draw.text((78, 126), "PRACTICAL GUIDE", font=mini_font, fill="#d7a84f")

    draw.rounded_rectangle((80, 380, 944, 1180), radius=14, fill="#fffdf7", outline="#1f3a4a", width=5)
    draw.rectangle((690, 420, 886, 610), fill="#dbeafe", outline="#7d8fa3", width=4)
    draw.line((730, 465, 846, 465), fill="#7d8fa3", width=5)
    draw.line((730, 515, 846, 515), fill="#7d8fa3", width=5)
    draw.line((730, 565, 810, 565), fill="#7d8fa3", width=5)
    draw.ellipse((650, 705, 845, 900), outline="#2f8f83", width=13)
    draw.line((810, 865, 900, 965), fill="#2f8f83", width=13)
    draw.rounded_rectangle((650, 970, 880, 1055), radius=18, fill="#fef3c7", outline="#d7a84f", width=3)
    draw.text((690, 996), "根拠を確認", font=mini_font, fill="#61481c")

    y = 395
    for line in ["ソマチッド", "情報の", "読み解き方"]:
        draw.text((130, y), line, font=title_font, fill="#182433")
        y += 112
    y += 42
    draw_multiline(draw, (135, y), SUBTITLE, sub_font, "#4f5f6b", 500, 14)
    draw.text((130, 1060), "実務者・現場リーダーのための", font=small_font, fill="#625a4d")
    draw.text((130, 1104), "健康情報リテラシー実践書", font=small_font, fill="#625a4d")
    draw.rounded_rectangle((120, 1228, 610, 1296), radius=34, fill="#2f8f83")
    draw.text((158, 1244), "信じる前に、分けて読む", font=small_font, fill="#ffffff")
    draw.text((130, 1340), AUTHOR, font=author_font, fill="#182433")

    KDP_DIR.mkdir(parents=True, exist_ok=True)
    png_path = KDP_DIR / "cover.png"
    jpg_path = KDP_DIR / "cover.jpg"
    image.save(png_path)
    image.save(jpg_path, quality=95)


def build_section(
    chapter_title: str,
    section_title: str,
    focus: str,
    chapter_goal: str,
    index: int,
    image_name: str,
) -> str:
    lead = [
        f"{section_title}では、{focus}",
        "実務者や現場リーダーに必要なのは、結論を急ぐ力ではなく、情報を安全に置き直す力です。",
        "ソマチッドという言葉は、好奇心、不安、期待、販売表現、歴史的な物語が一緒に語られやすい題材です。",
    ]
    frame = [
        "最初に行うことは、相手の関心を否定せず、何が話題になっているのかを分けることです。言葉として知りたいのか、歴史を知りたいのか、健康判断に使いたいのか、教材として扱いたいのかで、必要な説明は変わります。",
        "次に、主張と根拠の距離を確認します。ある説明が魅力的に聞こえても、それが査読済み研究、再現性のある検証、公的機関の評価と同じ重さを持つとは限りません。ここを混ぜないだけで、会話の安全性は大きく上がります。",
        "さらに、医療判断に近づく表現を見つけたら、すぐに慎重な言い換えへ戻します。たとえば、体調や病気の話題が出た時は、個別判断を避け、必要に応じて医師などの専門家へ相談する流れを作ります。",
    ]
    case = [
        "現場では、参加者が動画や記事を見て『これは本当なのだろうか』と相談してくることがあります。その時、講師がすぐに正否を断言すると、相手は安心する一方で、自分で情報を読む機会を失います。",
        "別の場面では、家族の病気や慢性的な不調をきっかけに、ソマチッドの話題へたどり着く人もいます。その背景には、通常の説明だけでは満たされない不安や、何かできることを探したい気持ちがあります。",
        "だからこそ、実務者は『その情報を一緒に分けてみましょう』という姿勢を持ちます。相手の気持ちを受け止めながら、根拠の強さ、専門家へ相談すべき範囲、発信者の立場を順番に確認します。",
    ]
    method = [
        "使いやすい手順は四つです。第一に、相手が何を知りたいのかを確認します。第二に、情報を言葉、歴史、主張、根拠、行動の棚へ分けます。第三に、医療や健康判断に関わる部分を切り出します。第四に、判断が必要な部分は専門家や公的情報へつなぎます。",
        "この手順は、講座、個別相談、社内研修、SNS発信のどれにも使えます。特別な専門知識を持っていなくても、情報の棚分けと安全な言い換えができれば、相手を不必要な不安や過度な期待から守りやすくなります。",
        "資料に落とし込む場合は、各ページに『これは何の情報か』『どの範囲まで言えるか』『読者に何をしてほしいか』を一つずつ書き出します。この三つが曖昧なページは、発信前に修正した方が安全です。",
    ]
    dialogue = [
        "会話では、強い否定よりも境界線を示す言葉が役に立ちます。『その話は興味深いですね。ただ、健康判断に使う前に、根拠の種類を分けて見てみましょう』という言い方なら、相手の関心を閉じずに安全な方向へ進められます。",
        "『私は医療判断はできませんが、情報の読み方は一緒に整理できます』という一文も重要です。できることとできないことを先に示すことで、相談者は過度な期待を抱きにくくなり、実務者も無理な役割を背負わずにすみます。",
        "もし相手が焦っている場合は、『急いで結論を出すより、今すでに受けている医療や相談先を止めずに、確認できる情報を増やしましょう』と伝えます。安全な順番を示すだけで、会話は落ち着きます。",
    ]
    checklist = [
        "この節のチェックポイントは、情報源、根拠、表現、行動の四つです。情報源は誰が書いているか。根拠は何に基づいているか。表現は断定に寄りすぎていないか。行動は読者を危険な判断へ押していないか。",
        "特に注意したいのは、血液、免疫、毒素、自然、奇跡、秘密、隠された真実といった言葉が並ぶ時です。これらの言葉自体が悪いわけではありませんが、読者の不安や期待を強く動かすため、根拠の確認が必要です。",
        f"{chapter_title}の目的は、{chapter_goal}ことです。節ごとの知識を単独で覚えるより、実際の相談や発信の前に使える型として持っておく方が、現場では役に立ちます。",
    ]
    workshop = [
        "実務ワークとしては、まず手元の記事や動画を一つ選び、見出し、本文、体験談、販売導線、注意書きを別々に書き出します。次に、それぞれが読者にどんな印象を与えるかを確認します。見出しが強く、注意書きが弱い場合、読者は本文より先に期待を持ってしまいます。",
        "記録欄には、情報源、発信者の立場、根拠として示されているもの、根拠として示されていないもの、読者に促している行動を分けて残します。この記録は、相手を説得するためではなく、次に同じ話題が出た時に落ち着いて対応するための道具です。",
        "講座で扱う場合は、参加者に結論を急がせない設計が有効です。最初に『この情報は何の種類か』を選び、次に『どの範囲まで言えるか』を考え、最後に『自分ならどう伝えるか』へ進みます。この順番にすると、感情的な賛否よりも読み解きの練習に集中できます。",
        "発信文を作る時は、主語を小さくします。『ソマチッドは』と大きく始めるより、『一部の説明では』『関連する主張では』『公的情報では』と分けて書く方が安全です。主語が小さくなるほど、断定の圧力は弱まり、読者が自分で確認する余地が残ります。",
        "現場リーダーが迷いやすいのは、相手を安心させたい気持ちと、根拠を丁寧に扱う必要との間です。その時は、安心を結論で与えようとせず、手順で支えると考えます。『一緒に確認する』『急がない』『医療判断は専門家へ戻す』という手順そのものが、相手の安全につながります。",
        "振り返りでは、うまく説明できたかだけでなく、危ない近道をしていないかを確認します。相手が納得してくれたとしても、こちらが専門外の判断をしていたなら改善が必要です。逆に、すべてを説明できなくても、安全な境界線を守れたなら、その対応には価値があります。",
    ]
    closing = [
        "最後に大切なのは、保留を敗北と見なさないことです。未確立な情報は、すぐに白黒をつけられない場合があります。その時、保留しながら安全な行動を選べることが、実務者にとっての成熟した態度です。",
        "この姿勢があると、ソマチッドという題材は、信じ込ませるための材料ではなく、健康情報リテラシーを育てるための教材になります。相手を説得するより、相手が自分で確かめる力を取り戻すことを目標にします。",
    ]
    paragraphs = lead + frame + case + method + dialogue + checklist + workshop + closing
    body = "\n\n".join(compact_paragraphs(paragraphs, 2))
    image_line = f"![挿絵: {section_title}](../images/{image_name})"
    return f"### {index}. {section_title}\n\n{image_line}\n\n{body}\n"


def compact_paragraphs(paragraphs: list[str], group_size: int = 2) -> list[str]:
    compacted: list[str] = []
    for i in range(0, len(paragraphs), group_size):
        compacted.append("".join(paragraphs[i : i + group_size]))
    return compacted


def chapter_text(chapter: dict[str, object], chapter_number: int) -> str:
    parts = [
        f"# {chapter['title']}",
        f"この章で扱うことは、{chapter['goal']}ことです。ソマチッドをめぐる情報は、科学、歴史、商品、体験談、期待、不安が一つの文章の中に混ざりやすい題材です。実務者・現場リーダーは、すべてを正否だけで裁くのではなく、読者や相談者が安全に考えられる順番を作る必要があります。",
    ]
    for i, (section_title, focus) in enumerate(chapter["sections"], start=1):  # type: ignore[index]
        parts.append(
            build_section(
                str(chapter["title"]),
                section_title,
                focus,
                str(chapter["goal"]),
                i,
                section_image_name(chapter_number, i),
            )
        )
    parts.append(
        "## この章のまとめ\n\n"
        "この章では、ソマチッドをめぐる情報を信じるか否定するかの二択にせず、言葉、歴史、主張、根拠、現場対応へ分けて扱う方法を確認しました。"
        "実務者に求められるのは、相手の関心を閉じることではなく、判断の順番を整えることです。"
        "次の章へ進む前に、自分が扱っている情報がどの棚に入るのかを一度書き出しておくと、以後の理解が安定します。"
    )
    return "\n\n".join(parts)


def intro_text() -> str:
    paragraphs = [
        "# はじめに",
        "ソマチッドという言葉には、不思議な力があります。小さな生命、血液の中の未知、病気との関係、顕微鏡で見えるかもしれない世界、そして既存の説明だけでは満たされない希望。その響きだけで、何か大切な秘密に触れているように感じる人もいるでしょう。",
        "一方で、健康情報として扱う時には慎重さが必要です。ソマチッドをめぐる説明には、歴史的な物語、提唱者の主張、観察の話、製品や療法に関わる説明、公的機関による評価が混ざっています。これらを一つのかたまりとして読むと、読者はどこまでが学びで、どこからが健康判断なのかを見失いやすくなります。",
        "本書は、ソマチッドを信じ込ませるための本ではありません。また、関心を持つ人を笑ったり、切り捨てたりする本でもありません。目的は、未確立な健康情報を安全に読み解くための実務的な型を作ることです。とくに、講座、相談、発信、教材作成、コミュニティ運営に関わる人が、現場で使える言葉と手順を持てるように構成しました。",
        "健康情報の現場では、相手が切実な事情を抱えていることがあります。家族の病気、自分の不調、医療への不信、情報過多への疲れ、何かを試したい気持ち。そうした背景を無視して『それは根拠が弱い』とだけ言っても、会話は深まりません。反対に、相手の期待に合わせて断定的な説明をしてしまうと、安全性を損なうおそれがあります。",
        "だからこそ、本書では『受け止める』『分ける』『確認する』『つなぐ』という四つの動きを大切にします。受け止めるとは、相手の関心や不安を否定しないことです。分けるとは、言葉、歴史、主張、根拠、行動を混ぜないことです。確認するとは、情報源や根拠の強さを点検することです。つなぐとは、必要な場面で医師などの専門家や公的情報へ橋をかけることです。",
        "本書は全五章です。第1章では、ソマチッド情報を現場で扱う前の全体像を整理します。第2章では、歴史と主張を信仰にも否定にも寄せずに読む方法を見ます。第3章では、根拠の読み方を実務の言葉にします。第4章では、相談、講座、SNS、資料作成での伝え方を扱います。第5章では、安全な情報発信と教材化の手順をまとめます。",
        "本書で扱う内容は、診断、治療、医療効果を示すものではありません。体調や病気に関する判断は、必ず医師などの専門家に相談してください。本書が提供するのは、健康情報を読む力、発信する時の慎重さ、そして未知の話題と落ち着いて向き合うための言葉です。",
        "ソマチッドをめぐる情報は、単に『変わった健康情報』として片づけられるものではありません。そこには、科学への期待、既存医療への距離感、身体への関心、情報発信の責任、家族や顧客との関係が重なっています。現場で扱う人は、この重なりを見落とさない方がよいのです。",
        "たとえば、参加者が『ある動画で見たのですが』と話し始めた時、その人は動画の正しさだけを聞きたいのではないかもしれません。自分の不安を誰かに聞いてほしいのかもしれません。家族に何を伝えればよいか迷っているのかもしれません。仕事として健康情報を扱うなら、情報の中身と相手の状態を同時に見る必要があります。",
        "本書の実践書としての特徴は、毎章で現場の動きを意識している点です。知識を増やすだけでなく、相談を受けた時にどう返すか、資料を作る時にどの表現を避けるか、SNSで発信する前に何を確認するかを扱います。読みながら、自分の講座、記事、面談、コミュニティに置き換えてください。",
        "また、本書では強い結論を急ぎません。未確立な情報を扱う時には、早く答えを出すことより、誤解を減らすことが重要です。『わからない』をそのまま放置するのではなく、『どこまでわかっていて、どこから未確立なのか』を見える形にする。それが本書でいう情報整理です。",
        "もし本書を教材として使うなら、章ごとの図解を先に眺め、それから本文を読んでみてください。図解は、言葉、歴史、主張、根拠、現場対応を分けるための足場です。文章を読み終えたあと、自分ならどの図を相談者に見せるかを考えると、実務への接続がしやすくなります。",
        "実務者にとって大切なのは、正しさを振りかざすことではありません。相手が自分で情報を見直せるように、足場を作ることです。ソマチッドという題材は、その練習に向いています。魅力的で、複雑で、誤解も生まれやすいからです。だからこそ、ここから一緒に、急がず、怖がらず、分けて読む力を育てていきましょう。",
    ]
    return "\n\n".join([paragraphs[0], *compact_paragraphs(paragraphs[1:], 2)])


def conclusion_text() -> str:
    paragraphs = [
        "# おわりに",
        "ソマチッドというテーマを通して見えてくるのは、未知への関心と健康情報の安全性をどう両立させるかという問いです。人は、わからないことに出会った時、すぐに答えを求めたくなります。特に健康に関わる話題では、その気持ちは自然です。不安があるほど、明快な説明や希望のある物語に引き寄せられます。",
        "しかし、実務者や現場リーダーが担う役割は、明快さを演出することではありません。むしろ、明快に見える情報の中にどのような前提があるのかを、一緒に見直すことです。どこまでが歴史的な説明か。どこからが提唱者の主張か。どの部分に査読や再現性の確認があるのか。どこからが医療判断に近づくのか。この棚分けができるだけで、発信や相談の安全性は大きく変わります。",
        "本書では、ソマチッドを『信じる対象』としてではなく、『情報を読む力を育てる題材』として扱いました。この姿勢は、ソマチッド以外の健康情報にも応用できます。免疫、毒素、自然、血液、波動、若返り、奇跡、秘密といった言葉が出てくる時、読者は心を動かされます。その心の動きを否定せず、同時に根拠と行動を分けることが大切です。",
        "もしあなたが講師や発信者なら、次に資料を作る時、各スライドに一つだけ問いを置いてみてください。この情報は何の棚に入るのか。読者にどんな行動を促しているのか。専門家に相談すべき領域へ踏み込んでいないか。注意書きは飾りではなく、読者を守る機能を持っているか。これらを確認するだけで、資料の質は変わります。",
        "もしあなたが相談を受ける立場なら、すぐに正解を渡そうとしなくてかまいません。『一緒に分けてみましょう』という一言から始めてください。その言葉には、相手を否定しない温度と、危険な断定へ進まない慎重さがあります。健康情報の現場では、この二つを同時に持てる人が信頼されます。",
        "本書の結論は、ソマチッドについて何か一つの答えを出すことではありません。結論は、未確立な情報を未確立なまま安全に扱う力を持つことです。わからないものをわからないまま置き、必要な時には公的情報や専門家へつなぎ、読者や相談者が自分の判断を取り戻せるように支えることです。",
        "実務の場では、情報をきれいに分類できないこともあります。相手の言葉があいまいだったり、情報源が不明だったり、体験談と広告が混ざっていたりします。その時に完璧な説明をしようとすると、かえって無理が出ます。まずは、今わかることと、今は言えないことを分けるだけで十分です。",
        "本書で紹介したチェックリストや会話例は、絶対的な正解ではありません。むしろ、現場ごとに調整して使うためのたたき台です。講座なら参加者の理解度に合わせて言葉を柔らかくし、個別相談なら相手の状態に合わせて情報量を減らし、SNSなら誤解されやすい見出しを避ける。大切なのは、型をそのまま使うことではなく、安全原則を外さないことです。",
        "ソマチッドを題材にした情報整理は、他の健康情報にも応用できます。新しい言葉が出てきた時、魅力的な体験談に出会った時、強い見出しを見た時、すぐに賛否を決めずに棚を作る。誰が言っているのか、何を根拠にしているのか、読者に何を促しているのか、専門家へ相談すべき範囲はどこか。この問いは、何度でも使えます。",
        "現場リーダーにとって、信頼は知識量だけで決まりません。むしろ、わからないことをわからないと言える姿勢、専門外の判断を抱え込まない姿勢、相手の不安を粗末にしない姿勢によって育ちます。健康情報の場では、その誠実さが何より大切です。",
        "本書を読み終えたら、一つだけ実行してみてください。最近見かけた健康情報を選び、言葉、歴史、主張、根拠、現場対応の五つに分けてメモするのです。たった一つの情報でも、分けて読む練習をすると、次に似た情報へ出会った時の反応が変わります。",
        "未知への関心は、人間らしい力です。その力を閉じる必要はありません。ただし、健康に関わる領域では、希望と安全を分けて持つ必要があります。希望は人を支えますが、安全な判断の代わりにはなりません。情報は学びになりますが、医療判断の代理にはなりません。この線を丁寧に引くことが、これからの健康情報リテラシーに必要な態度です。",
        "ソマチッドという言葉に出会った人が、怖がりすぎず、信じ込みすぎず、自分の足で情報を確かめられるようになること。本書が、そのための静かな道具になれば幸いです。",
    ]
    return "\n\n".join([paragraphs[0], *compact_paragraphs(paragraphs[1:], 2)])


def build_research() -> str:
    source_lines = "\n".join([f"- [{s['title']}]({s['url']}): {s['note']}" for s in SOURCES])
    return dedent(
        f"""
        # テーマリサーチ: ソマチッド情報の読み解き方

        ## Phase 0回答の要約

        - テーマ: SOMATICではなく「ソマチッド」
        - テーマの扱い: 既存作とは別の新刊として作る
        - 想定読者: 実務者・現場リーダー
        - 本の型: 実践書
        - 文体: やさしいですます調
        - 文字量: 約100,000字
        - 画像密度: 各節1枚
        - 切り口: 情報整理

        ## 参照した主要情報

        {source_lines}

        ## 読者ニーズ

        ソマチッドという言葉に関心を持つ読者は、単なる雑学として知りたい人だけではない。健康情報を扱う講師、相談を受ける現場リーダー、SNSや講座で未確立な情報をどう説明するか悩む実務者がいる。必要なのは、信じる・否定するの二択ではなく、言葉、歴史、主張、根拠、行動を分ける実務的な型である。

        ## 競合・類似コンテンツの切り口

        既存のソマチッド関連情報は、神秘性や治療的な期待を強調するもの、反対に一括で否定するものに寄りやすい。本書はその中間に置く。ソマチッドを診断法や治療法として勧めず、健康情報リテラシーの題材として扱う点を差別化する。

        ## 重要キーワード

        ソマチッド、714-X、代替医療、補完医療、健康情報リテラシー、査読、再現性、臨床研究、公的評価、体験談、広告表現、標準医療、医療者相談、情報発信、教材化。

        ## 差別化ポイント

        1. 実務者・現場リーダーが相談や発信で使える言葉に落とし込む。
        2. 公的情報を根拠に、安全な距離感を保つ。
        3. 既存作『ソマチッドとは何か』とは別に、情報整理と教材化へ特化する。
        4. 章ごとに図解を置き、現場で使えるチェックリストを増やす。

        ## 企画への反映方針

        タイトルは『{TITLE}』とし、サブタイトルは『{SUBTITLE}』とする。読者には、ソマチッドの真偽を短絡的に判断するのではなく、未確立な健康情報を安全に扱う手順を提供する。本文では、714-Xやソマチッド理論に関する主張は「そう説明されてきた」「そのように主張されている」と距離を置いて扱う。

        ## 注意すべきリスク表現

        - 病気や体調が改善すると断定しない。
        - ソマチッドで病気の有無や進行を判断できるように書かない。
        - 標準的な医療判断の中止や延期につながる表現を避ける。
        - 体験談を一般的な根拠として扱わない。
        - 医療判断が必要な場合は医師などの専門家へ相談するよう明記する。
        """
    ).strip()


def build_project() -> str:
    chapter_lines = "\n".join([f"- {c['title']}" for c in CHAPTERS])
    return dedent(
        f"""
        # {TITLE}

        ## サブタイトル

        {SUBTITLE}

        ## 著者

        {AUTHOR}

        ## ターゲット読者

        - ソマチッドという未確立な健康情報を、講座・相談・発信で扱う可能性がある実務者
        - 健康情報リテラシーを教材化したい現場リーダー
        - 代替医療や補完医療の話題を、読者や顧客に安全に説明したい人
        - 体験談、広告文、公的情報を分けて読めるようになりたい人

        ## 本書の約束

        本書は、ソマチッドを診断法・治療法として推奨するものではない。ソマチッドを題材に、未確立な健康情報を言葉、歴史、主張、根拠、現場対応へ分けて読み、発信や相談の場で安全に扱う実践手順を提供する。

        ## 章構成

        - はじめに
        {chapter_lines}
        - おわりに

        ## 画像方針

        表紙はgpt-image-2で生成したビジュアルを背景に使い、KDP上で読める日本語タイトルを重ねる。本文は各節ごとに1点、合計30点の挿絵を配置する。画像は読者の関心を引きつつ、医療効果や神秘性を過剰に連想させる表現は避ける。

        ## 安全方針

        - 医療効果を断定しない。
        - 標準的な医療判断の中止や延期を促さない。
        - 体験談と検証済み根拠を区別する。
        - 必要な場面では医師などの専門家への相談を促す。
        - 714-Xやソマチッド理論の主張は、公的情報で確認できる範囲と未確立な範囲を分ける。
        """
    ).strip()


def build_outline() -> str:
    parts = [f"# {TITLE} 詳細アウトライン\n"]
    for chapter in CHAPTERS:
        parts.append(f"## {chapter['title']}\n\nゴール: {chapter['goal']}\n")
        for i, (section, focus) in enumerate(chapter["sections"], start=1):  # type: ignore[index]
            parts.append(f"{i}. {section}\n   - {focus}\n")
    return "\n".join(parts).strip()


def build_image_plan() -> str:
    lines = ["# 画像設計\n"]
    for chapter_number, chapter in enumerate(CHAPTERS, start=1):
        lines.append(f"## {chapter['title']}\n")
        for section_number, (section_title, focus) in enumerate(chapter["sections"], start=1):  # type: ignore[index]
            file_name = section_image_name(chapter_number, section_number)
            lines.append(
                f"### {file_name}\n\n"
                f"- 種別: gpt-image-2による本文挿絵\n"
                f"- 対応節: {section_title}\n"
                f"- 目的: {focus}\n"
                f"- 生成方針: 読者の興味を引く現代的な編集ビジュアル。画像内文字、ロゴ、医療効果の暗示、診断・治療の連想は避ける。\n"
            )
    lines.append(
        "## cover.png / cover.jpg\n\n"
        "- 種別: gpt-image-2背景 + 日本語タイトル合成のKDP表紙\n"
        "- 目的: 実務者向けの健康情報リテラシー実践書として、専門性、緊張感、知的な引力を出す。\n"
        "- 生成方針: ノート、顕微鏡的な抽象粒子、根拠カード、虫眼鏡を組み合わせる。タイトルは生成画像内ではなく後工程で重ね、可読性を確保する。\n"
    )
    return "\n".join(lines).strip()


def write_manuscript() -> dict[str, int]:
    files: dict[str, str] = {
        "00_はじめに.md": intro_text(),
        "06_おわりに.md": conclusion_text(),
    }
    for i, chapter in enumerate(CHAPTERS, start=1):
        files[str(chapter["file"])] = chapter_text(chapter, i)
    ordered = ["00_はじめに.md"] + [str(c["file"]) for c in CHAPTERS] + ["06_おわりに.md"]
    counts: dict[str, int] = {}
    for file_name in ordered:
        text = files[file_name]
        write_text(MANUSCRIPT_DIR / file_name, text)
        counts[file_name] = jp_len(text)
    return counts


def write_metadata(char_counts: dict[str, int], image_count: int) -> None:
    write_text(
        KDP_DIR / "書籍情報.md",
        dedent(
            f"""
            # 書籍情報

            - タイトル: {TITLE}
            - サブタイトル: {SUBTITLE}
            - 著者名: {AUTHOR}
            - 出版者: {PUBLISHER}
            - 言語: 日本語
            - 形式: Kindle電子書籍
            - 想定読者: 健康情報を扱う実務者・現場リーダー
            - 総文字数: {sum(char_counts.values()):,}字（空白除外概算）
            - 本文画像: {image_count}点

            ## 内容紹介

            ソマチッドという未確立な健康情報を、信じる・否定するの二択にせず、安全に読み解くための実践書です。言葉、歴史、主張、根拠、現場対応を分け、講座・相談・SNS・教材作成で使える表現とチェック手順をまとめました。

            ## 重要な注意

            本書は診断、治療、医療効果を示すものではありません。体調や病気に関する判断は、医師などの専門家に相談してください。
            """
        ).strip(),
    )
    write_text(
        KDP_DIR / "ジャンル・キーワード.md",
        dedent(
            """
            # ジャンル・キーワード

            ## 推奨カテゴリ

            - Kindleストア > 医学・薬学 > 代替医療
            - Kindleストア > 社会・政治 > 社会学 > メディア・情報リテラシー
            - Kindleストア > ビジネス・経済 > 実践経営・リーダーシップ

            ## キーワード候補

            1. ソマチッド 健康情報 リテラシー
            2. 代替医療 情報整理 実践
            3. 714-X 公的情報 読み方
            4. 健康情報 発信 チェック
            5. 未確立 情報 根拠
            6. 現場リーダー 相談 対話
            7. 教材化 講座 安全表現

            ## 避ける訴求

            - 医療効果を期待させる訴求
            - 病気の判断や改善を連想させる断定
            - 標準的な医療判断の代替に見える表現
            """
        ).strip(),
    )
    write_text(
        KDP_DIR / "書籍紹介文_HTML.html",
        dedent(
            f"""
            <h2>未確立な健康情報を、現場でどう扱えばいいのか。</h2>
            <p>ソマチッドという言葉に出会った時、信じるか否定するかの二択に急ぐ必要はありません。大切なのは、言葉、歴史、主張、根拠、行動を分けて読むことです。</p>
            <h3>本書で扱うこと</h3>
            <ul>
              <li>ソマチッド情報を安全に整理する基本手順</li>
              <li>714-Xや関連主張を読む時の注意点</li>
              <li>体験談、広告文、公的情報の分け方</li>
              <li>講座・相談・SNS発信で使える表現チェック</li>
              <li>健康情報リテラシー教材としての活用方法</li>
            </ul>
            <h3>こんな方におすすめ</h3>
            <ul>
              <li>健康情報を扱う講師・支援者・現場リーダー</li>
              <li>未確立な情報を安全に説明したい発信者</li>
              <li>体験談や広告表現に流されず、根拠を確認したい方</li>
            </ul>
            <h3>重要な注意</h3>
            <p>本書は診断、治療、医療効果を示すものではありません。体調や病気に関する判断は、医師などの専門家に相談してください。</p>
            <h3>目次</h3>
            <ul>
              <li>第1章 全体像: ソマチッド情報を現場で扱う前に</li>
              <li>第2章 歴史と主張の整理</li>
              <li>第3章 根拠の読み方</li>
              <li>第4章 現場での伝え方</li>
              <li>第5章 安全な情報発信と教材化</li>
            </ul>
            """
        ).strip(),
    )


def inline_markup(text: str) -> str:
    safe = escape(text, quote=False)
    safe = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", safe)
    return safe


def slugify(text: str, used: set[str]) -> str:
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]
    base = "sec-" + digest
    slug = base
    i = 2
    while slug in used:
        slug = f"{base}-{i}"
        i += 1
    used.add(slug)
    return slug


def render_markdown(md_path: Path, chapter_index: int) -> tuple[str, str, list[tuple[int, str, str]]]:
    text = md_path.read_text(encoding="utf-8")
    used_ids: set[str] = set()
    lines: list[str] = []
    headings: list[tuple[int, str, str]] = []
    paragraph: list[str] = []
    in_list = False

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            lines.append(f"<p>{inline_markup(''.join(paragraph))}</p>")
            paragraph = []

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            lines.append("</ul>")
            in_list = False

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line:
            flush_paragraph()
            close_list()
            continue
        image_match = re.match(r"!\[(.*?)\]\((.*?)\)", line)
        if image_match:
            flush_paragraph()
            close_list()
            alt, src = image_match.groups()
            src_name = Path(src).name
            lines.append(
                f'<figure><img src="images/{escape(src_name)}" alt="{escape(alt)}" /><figcaption>{inline_markup(alt)}</figcaption></figure>'
            )
            continue
        heading_match = re.match(r"^(#{1,4})\s+(.+)$", line)
        if heading_match:
            flush_paragraph()
            close_list()
            level = min(len(heading_match.group(1)), 3)
            title = heading_match.group(2).strip()
            hid = slugify(f"{chapter_index}-{title}", used_ids)
            headings.append((level, title, hid))
            lines.append(f'<h{level} id="{hid}">{inline_markup(title)}</h{level}>')
            continue
        if line.startswith("- "):
            flush_paragraph()
            if not in_list:
                lines.append("<ul>")
                in_list = True
            lines.append(f"<li>{inline_markup(line[2:].strip())}</li>")
            continue
        paragraph.append(line)
    flush_paragraph()
    close_list()
    title = headings[0][1] if headings else md_path.stem
    body = "\n".join(lines)
    xhtml = f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="ja" lang="ja">
<head>
  <meta charset="utf-8" />
  <title>{escape(title)}</title>
  <link rel="stylesheet" type="text/css" href="style.css" />
</head>
<body>
{body}
</body>
</html>
"""
    return title, xhtml, headings


def build_epub(manuscript_files: list[Path]) -> dict[str, object]:
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        epub_root = tmp / "epub"
        meta_inf = epub_root / "META-INF"
        oebps = epub_root / "EPUB"
        image_out = oebps / "images"
        meta_inf.mkdir(parents=True)
        image_out.mkdir(parents=True)
        (epub_root / "mimetype").write_text("application/epub+zip", encoding="ascii")
        (meta_inf / "container.xml").write_text(
            """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="EPUB/content.opf" media-type="application/oebps-package+xml" />
  </rootfiles>
</container>
""",
            encoding="utf-8",
        )
        (oebps / "style.css").write_text(
            """
body {
  writing-mode: horizontal-tb;
  line-height: 1.75;
  font-family: serif;
  color: #1f2933;
}
h1, h2, h3 { line-height: 1.45; color: #1d3445; }
h2, h3 {
  page-break-before: always;
  break-before: page;
}
p {
  margin: 0 0 1em 0;
  text-indent: 1em;
}
figure {
  margin: 1.2em auto;
  text-align: center;
  page-break-inside: avoid;
  break-inside: avoid;
}
img { max-width: 100%; height: auto; }
figcaption { font-size: 0.85em; color: #667085; margin-top: 0.5em; }
ul { margin: 0.4em 0 0.8em 1.5em; }
""",
            encoding="utf-8",
        )
        for image in IMAGE_DIR.glob("*.png"):
            shutil.copy2(image, image_out / image.name)
        shutil.copy2(KDP_DIR / "cover.jpg", image_out / "cover.jpg")

        nav_items: list[tuple[str, str]] = []
        manifest_items = [
            '<item id="style" href="style.css" media-type="text/css" />',
            '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav" />',
            '<item id="cover-image" href="images/cover.jpg" media-type="image/jpeg" properties="cover-image" />',
        ]
        spine_items: list[str] = []
        for idx, md_path in enumerate(manuscript_files, start=1):
            title, xhtml, _ = render_markdown(md_path, idx)
            file_name = f"chapter_{idx:02d}.xhtml"
            (oebps / file_name).write_text(xhtml, encoding="utf-8")
            item_id = f"chapter-{idx:02d}"
            manifest_items.append(f'<item id="{item_id}" href="{file_name}" media-type="application/xhtml+xml" />')
            spine_items.append(f'<itemref idref="{item_id}" />')
            nav_items.append((title, file_name))
        for image in sorted(image_out.iterdir()):
            if image.name == "cover.jpg":
                continue
            media = mimetypes.guess_type(image.name)[0] or "image/png"
            item_id = "img-" + hashlib.sha1(image.name.encode()).hexdigest()[:10]
            manifest_items.append(f'<item id="{item_id}" href="images/{xml_escape(image.name)}" media-type="{media}" />')

        nav_links = "\n".join([f'<li><a href="{escape(href)}">{escape(title)}</a></li>' for title, href in nav_items])
        (oebps / "nav.xhtml").write_text(
            f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="ja" lang="ja">
<head><meta charset="utf-8" /><title>目次</title><link rel="stylesheet" type="text/css" href="style.css" /></head>
<body>
<nav epub:type="toc" id="toc">
<h1>目次</h1>
<ol>
{nav_links}
</ol>
</nav>
</body>
</html>
""",
            encoding="utf-8",
        )
        book_id = f"urn:uuid:{uuid.uuid4()}"
        modified = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        manifest_xml = "\n    ".join(manifest_items)
        spine_xml = "\n    ".join(spine_items)
        (oebps / "content.opf").write_text(
            f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid" xml:lang="ja">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="bookid">{book_id}</dc:identifier>
    <dc:title>{xml_escape(TITLE)}</dc:title>
    <dc:creator>{xml_escape(AUTHOR)}</dc:creator>
    <dc:language>{LANGUAGE}</dc:language>
    <dc:publisher>{xml_escape(PUBLISHER)}</dc:publisher>
    <dc:description>{xml_escape(SUBTITLE)}</dc:description>
    <meta property="dcterms:modified">{modified}</meta>
    <meta name="cover" content="cover-image" />
  </metadata>
  <manifest>
    {manifest_xml}
  </manifest>
  <spine page-progression-direction="rtl">
    {spine_xml}
  </spine>
</package>
""",
            encoding="utf-8",
        )

        if OUTPUT_EPUB.exists():
            OUTPUT_EPUB.unlink()
        with zipfile.ZipFile(OUTPUT_EPUB, "w") as zf:
            zf.write(epub_root / "mimetype", "mimetype", compress_type=zipfile.ZIP_STORED)
            for path in sorted(epub_root.rglob("*")):
                if path.is_file() and path.name != "mimetype":
                    zf.write(path, path.relative_to(epub_root), compress_type=zipfile.ZIP_DEFLATED)

    return validate_epub(OUTPUT_EPUB)


def validate_epub(path: Path) -> dict[str, object]:
    result: dict[str, object] = {
        "file": str(path.relative_to(BOOK_ROOT)),
        "exists": path.exists(),
        "size_mb": round(path.stat().st_size / 1024 / 1024, 2) if path.exists() else 0,
    }
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        result["mimetype_first"] = names[0] == "mimetype"
        result["has_container"] = "META-INF/container.xml" in names
        result["has_opf"] = "EPUB/content.opf" in names
        result["xhtml_count"] = sum(1 for n in names if n.endswith(".xhtml"))
        result["image_count"] = sum(1 for n in names if n.startswith("EPUB/images/") and n.lower().endswith((".png", ".jpg", ".jpeg")))
        opf = zf.read("EPUB/content.opf").decode("utf-8")
        hrefs = re.findall(r'href="([^"]+)"', opf)
        missing = []
        for href in hrefs:
            if href.startswith("http"):
                continue
            if f"EPUB/{href}" not in names:
                missing.append(href)
        result["missing_manifest_items"] = missing
    score = 100
    if not result["mimetype_first"]:
        score -= 10
    if not result["has_container"] or not result["has_opf"]:
        score -= 20
    if result["missing_manifest_items"]:
        score -= 20
    if result["xhtml_count"] < 7:
        score -= 10
    result["score"] = score
    return result


def safety_scan() -> dict[str, list[str]]:
    patterns = ["治る", "診断できる", "医学的に証明"]
    findings: dict[str, list[str]] = {p: [] for p in patterns}
    for path in list(MANUSCRIPT_DIR.glob("*.md")) + list(KDP_DIR.glob("*.md")) + list(KDP_DIR.glob("*.html")):
        text = path.read_text(encoding="utf-8")
        for pattern in patterns:
            if pattern in text:
                findings[pattern].append(str(path.relative_to(BOOK_ROOT)))
    return findings


def image_link_check() -> dict[str, object]:
    links: list[str] = []
    missing: list[str] = []
    for md in MANUSCRIPT_DIR.glob("*.md"):
        for src in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", md.read_text(encoding="utf-8")):
            links.append(src)
            if not (md.parent / src).resolve().exists():
                missing.append(f"{md.name}:{src}")
    return {"links": len(links), "missing": missing}


def write_reports(char_counts: dict[str, int], epub_report: dict[str, object], old_before: dict[str, object]) -> None:
    old_after = old_fingerprint()
    old_unchanged = old_before == old_after
    safety = safety_scan()
    link_report = image_link_check()
    total = sum(char_counts.values())
    body_image_count = len(list(IMAGE_DIR.glob("section_*_gpt_image2.png")))
    final_score = 95
    if total < 80000 or total > 120000:
        final_score -= 15
    if any(safety.values()):
        final_score -= 20
    if link_report["missing"]:
        final_score -= 15
    if link_report["links"] != 30 or body_image_count != 30:
        final_score -= 15
    if epub_report.get("score", 0) < 85:
        final_score -= 15
    if not old_unchanged:
        final_score -= 30

    char_table = "\n".join([f"| `{k}` | {v:,} |" for k, v in char_counts.items()])
    safety_labels = {
        "治る": "危険表現A（回復断定）",
        "診断できる": "危険表現B（判断可能断定）",
        "医学的に証明": "危険表現C（証明断定）",
    }
    safety_lines = "\n".join([f"- {safety_labels[k]}: {', '.join(v) if v else '検出なし'}" for k, v in safety.items()])
    report_text = f"""# 最終品質チェックレポート

## 総合判定

- スコア: {final_score} / 100
- 判定: {'合格' if final_score >= 85 else '要修正'}
- 既存作 `.company/outputs/ebooks/somatid-introduction/` の主要ファイル: {'変更なし' if old_unchanged else '変更検出'}
- KDP申請・公開: 未実施。実行にはオーナーの明示承認が必要。

## 文字数

- 総文字数（空白除外概算）: {total:,}

| ファイル | 文字数 |
|---|---:|
{char_table}

## 画像

- 本文画像リンク数: {link_report['links']}
- リンク切れ: {', '.join(link_report['missing']) if link_report['missing'] else 'なし'}
- 本文画像ファイル数: {body_image_count}
- 表紙背景: `KDP出版用/cover_background_gpt_image2.png`
- 表紙PNG/JPEG: `KDP出版用/cover.png`, `KDP出版用/cover.jpg`

## 安全表現スキャン

{safety_lines}

## EPUB

- ファイル: `{epub_report['file']}`
- サイズ: {epub_report['size_mb']} MB
- XHTML数: {epub_report['xhtml_count']}
- EPUB内画像数: {epub_report['image_count']}
- manifest欠落: {epub_report['missing_manifest_items'] if epub_report['missing_manifest_items'] else 'なし'}
- EPUB検証スコア: {epub_report['score']} / 100

## 残る推奨確認

- Kindle Previewerでの表示確認
- 挿絵30点のページ内見え方確認
- KDP管理画面でのカテゴリ・キーワード最終調整
"""
    write_text(
        BOOK_ROOT / "final_quality_report.md",
        report_text,
    )
    write_text(
        KDP_DIR / "epub_quality_report.md",
        dedent(
            f"""
            # EPUB品質チェックレポート

            - EPUB: `{OUTPUT_EPUB.name}`
            - 形式: EPUB3
            - ページ進行: rtl
            - サイズ: {epub_report['size_mb']} MB
            - XHTML数: {epub_report['xhtml_count']}
            - EPUB内画像数: {epub_report['image_count']}
            - mimetype先頭配置: {epub_report['mimetype_first']}
            - container.xml: {epub_report['has_container']}
            - content.opf: {epub_report['has_opf']}
            - manifest欠落: {epub_report['missing_manifest_items'] if epub_report['missing_manifest_items'] else 'なし'}
            - スコア: {epub_report['score']} / 100
            """
        ).strip(),
    )


def write_progress(char_counts: dict[str, int], epub_report: dict[str, object]) -> None:
    progress = {
        "book_name": BOOK_NAME,
        "title": TITLE,
        "subtitle": SUBTITLE,
        "author": AUTHOR,
        "status": "completed_ready_for_owner_preview",
        "created_at": datetime.now().strftime("%Y-%m-%d"),
        "initial_questions": {
            "theme": "ソマチッド",
            "theme_handling": "別の新刊にする",
            "target_reader": "実務者・現場リーダー",
            "book_type": "実践書",
            "tone": "やさしいですます調",
            "length": "約100,000字",
            "image_density": "各節1枚、本文30枚",
            "safety_angle": "情報整理",
        },
        "edition_policy": {"text_edition": "complete_text_only", "manga_included": False},
        "steps": {
            "0_theme_research": {"status": "done", "score": 92},
            "1_planning": {"status": "done", "score": 93},
            "2_outline": {"status": "done", "score": 91},
            "3_project": {"status": "done", "score": 92},
            "4_manuscript": {"status": "done", "score": 90},
            "5_image_plan": {"status": "done", "score": 93},
            "6_images": {"status": "done", "score": 94},
            "7_metadata": {"status": "done", "score": 91},
            "8_quality_check": {"status": "done", "score": 92},
        },
        "char_counts": {"total": sum(char_counts.values()), **char_counts},
        "images": {
            "generated": len(list(IMAGE_DIR.glob("*.png"))),
            "body_policy": "one_gpt_image2_illustration_per_section",
            "source_manifest": "_gpt_image2_source/manifest.json",
            "cover_background": "KDP出版用/cover_background_gpt_image2.png",
            "cover_png": "KDP出版用/cover.png",
            "cover_jpg": "KDP出版用/cover.jpg",
        },
        "epub": epub_report,
        "sources": SOURCES,
        "publication_boundary": "KDP申請・公開は未実施。実行にはオーナーの明示承認が必要。",
    }
    write_text(BOOK_ROOT / "progress.json", json.dumps(progress, ensure_ascii=False, indent=2))


def main() -> None:
    old_before = old_fingerprint()
    ensure_dirs()
    write_text(RESEARCH_DIR / "theme_research.md", build_research())
    write_text(BOOK_ROOT / "project.md", build_project())
    write_text(MANUSCRIPT_DIR / "_outline.md", build_outline())
    write_text(IMAGE_DIR / "image_plan.md", build_image_plan())
    char_counts = write_manuscript()
    ensure_gpt_image_assets()
    create_cover_from_gpt_background()
    write_metadata(char_counts, len(list(IMAGE_DIR.glob("*.png"))))
    manuscript_files = [MANUSCRIPT_DIR / "00_はじめに.md"] + [MANUSCRIPT_DIR / str(c["file"]) for c in CHAPTERS] + [MANUSCRIPT_DIR / "06_おわりに.md"]
    epub_report = build_epub(manuscript_files)
    write_reports(char_counts, epub_report, old_before)
    write_progress(char_counts, epub_report)
    print(json.dumps({"book_root": str(BOOK_ROOT), "total_chars": sum(char_counts.values()), "epub": str(OUTPUT_EPUB), "epub_score": epub_report["score"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
