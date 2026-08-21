#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[2]
DPI = 300
FRONT_X = 2535
TOP = 38


@dataclass(frozen=True)
class CoverFix:
    pdf: Path
    title_lines: list[str]
    subtitle: str
    title_size: int
    subtitle_size: int
    panel: tuple[int, int, int, int]
    title_box: tuple[int, int, int, int]
    subtitle_box: tuple[int, int, int, int]
    accent: tuple[int, int, int, int]
    series: str | None = None
    series_box: tuple[int, int, int, int] | None = None


def find_font() -> Path | None:
    candidates: list[Path] = []
    for root in [Path("/System/Library/Fonts"), Path("/System/Library/Fonts/Supplemental"), Path("/Library/Fonts")]:
        if root.exists():
            candidates.extend(
                p
                for p in root.rglob("*")
                if p.suffix.lower() in {".ttf", ".ttc", ".otf"} and ("Hiragino" in p.name or "Yu" in p.name)
            )
    return sorted(candidates, key=lambda p: ("Hiragino" not in p.name, len(p.name)))[0] if candidates else None


FONT_PATH = find_font()


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return ImageFont.truetype(str(FONT_PATH), size) if FONT_PATH else ImageFont.load_default()


def text_size(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.ImageFont) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=fnt)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def center_lines(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    box: tuple[int, int, int, int],
    fnt: ImageFont.ImageFont,
    fill: tuple[int, int, int, int],
    gap: int,
) -> None:
    heights = [text_size(draw, line, fnt)[1] for line in lines]
    total = sum(heights) + gap * max(0, len(lines) - 1)
    y = box[1] + max(0, (box[3] - box[1] - total) // 2)
    for line, height in zip(lines, heights):
        width, _ = text_size(draw, line, fnt)
        draw.text((box[0] + (box[2] - box[0] - width) / 2, y), line, font=fnt, fill=fill)
        y += height + gap


def render_pdf_to_image(pdf: Path) -> Image.Image:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "cover"
        subprocess.run(["pdftoppm", "-png", "-singlefile", "-r", str(DPI), str(pdf), str(out)], check=True)
        return Image.open(out.with_suffix(".png")).convert("RGBA")


def apply_fix(fix: CoverFix) -> None:
    pdf = ROOT / fix.pdf
    img = render_pdf_to_image(pdf)
    draw = ImageDraw.Draw(img, "RGBA")
    dx, dy = FRONT_X, TOP
    panel = (dx + fix.panel[0], dy + fix.panel[1], dx + fix.panel[2], dy + fix.panel[3])
    title_box = (dx + fix.title_box[0], dy + fix.title_box[1], dx + fix.title_box[2], dy + fix.title_box[3])
    subtitle_box = (dx + fix.subtitle_box[0], dy + fix.subtitle_box[1], dx + fix.subtitle_box[2], dy + fix.subtitle_box[3])
    draw.rounded_rectangle(panel, radius=46, fill=(255, 252, 238, 236), outline=fix.accent, width=5)
    center_lines(draw, fix.title_lines, title_box, font(fix.title_size), (54, 47, 42, 255), gap=14)
    center_lines(draw, [fix.subtitle], subtitle_box, font(fix.subtitle_size), (88, 68, 50, 255), gap=0)
    if fix.series and fix.series_box:
        series_box = (dx + fix.series_box[0], dy + fix.series_box[1], dx + fix.series_box[2], dy + fix.series_box[3])
        center_lines(draw, [fix.series], series_box, font(36), (90, 70, 52, 255), gap=0)
    img.convert("RGB").save(pdf, "PDF", resolution=DPI)


def main() -> None:
    fixes = [
        CoverFix(
            pdf=Path(".company/outputs/picture-books/japanese-folktales/2026-06-17-warashibe-tarou-arigatou-no-tabi/KDP出版用/UPLOAD_04_ペーパーバック_表紙PDF_2026-06-17-warashibe-tarou-arigatou-no-tabi.pdf"),
            title_lines=["わらしべたろうと", "ありがとうの たび"],
            subtitle="感謝と工夫を育てる昔話えほん",
            title_size=92,
            subtitle_size=46,
            panel=(180, 150, 2295, 790),
            title_box=(240, 205, 2235, 500),
            subtitle_box=(300, 530, 2175, 625),
            accent=(130, 101, 70, 210),
            series="日本の昔話えほんシリーズ 2",
            series_box=(300, 660, 2175, 715),
        ),
        CoverFix(
            pdf=Path(".company/outputs/picture-books/2026-06-18-hoshiakari-rantan/KDP出版用/UPLOAD_04_ペーパーバック_表紙PDF_hoshiakari-rantan.pdf"),
            title_lines=["ほしあかり ランタン"],
            subtitle="まよった ときに ちいさく しらせる おはなし",
            title_size=118,
            subtitle_size=50,
            panel=(135, 110, 2340, 760),
            title_box=(200, 160, 2275, 360),
            subtitle_box=(260, 420, 2215, 640),
            accent=(235, 190, 86, 210),
        ),
        CoverFix(
            pdf=Path(".company/outputs/picture-books/2026-06-17-sorairo-madofuki/KDP出版用/UPLOAD_04_ペーパーバック_表紙PDF_sorairo-madofuki.pdf"),
            title_lines=["そらいろ まどふき"],
            subtitle="くもった こころに ひかりを いれる おはなし",
            title_size=118,
            subtitle_size=50,
            panel=(135, 110, 2340, 760),
            title_box=(200, 160, 2275, 360),
            subtitle_box=(260, 420, 2215, 640),
            accent=(119, 160, 170, 210),
        ),
    ]
    for fix in fixes:
        apply_fix(fix)
        print(f"fixed {fix.pdf}")


if __name__ == "__main__":
    main()
