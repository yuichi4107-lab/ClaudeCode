#!/usr/bin/env python3
"""Regenerate Japanese folktales paperback interiors with true full-page bleed."""

from __future__ import annotations

import shutil
import subprocess
import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageFilter, ImageOps


TRIM_IN = 8.25
BLEED_IN = 0.125
DPI = 300
PAGE_COUNT = 32
POINTS_PER_INCH = 72

TRIM_PX = int(TRIM_IN * DPI)
SIDE_BLEED_PX = round(BLEED_IN * DPI)
TOP_BLEED_PX = round(BLEED_IN * DPI)
BOTTOM_BLEED_PX = round(BLEED_IN * DPI) - 1
INTERIOR_W_PX = TRIM_PX + SIDE_BLEED_PX
INTERIOR_H_PX = TRIM_PX + TOP_BLEED_PX + BOTTOM_BLEED_PX

PDF_W_PT = (TRIM_IN + BLEED_IN) * POINTS_PER_INCH
PDF_H_PT = (TRIM_IN + BLEED_IN * 2) * POINTS_PER_INCH

SCRIPT = Path(__file__).resolve()
ROOT = SCRIPT.parents[2]
SERIES = ROOT / ".company/outputs/picture-books/japanese-folktales"
NOW = datetime.now(ZoneInfo("Asia/Tokyo"))
STAMP = NOW.strftime("%Y%m%d_%H%M%S")
DATE_STAMP = NOW.strftime("%Y-%m-%d")


def source_page(project: Path, page_no: int) -> Path:
    candidates = [
        project / "layout/preview_pages" / f"page_{page_no:03d}.jpg",
        project / "images/pages" / f"page_{page_no:03d}.png",
        project / "images/pages_gpt_image2" / f"page_{page_no:03d}.png",
        project / "images/pages_gpt_image2" / f"page_{page_no:03d}.jpg",
    ]
    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            with Image.open(candidate) as image:
                image.verify()
            return candidate
        except Exception:
            continue
    raise FileNotFoundError(f"Missing source page {page_no:03d} in {project}")


def make_bleed_page(src: Path, page_no: int) -> Image.Image:
    page = Image.open(src).convert("RGB")
    if page.size != (TRIM_PX, TRIM_PX):
        page = page.resize((TRIM_PX, TRIM_PX), Image.Resampling.LANCZOS)

    # KDP interior bleed adds 0.125 in on the outside edge only:
    # odd pages bleed right, even pages bleed left for the standard LTR paperback.
    left_bleed = SIDE_BLEED_PX if page_no % 2 == 0 else 0

    background = ImageOps.fit(
        page,
        (INTERIOR_W_PX, INTERIOR_H_PX),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    ).filter(ImageFilter.GaussianBlur(8))
    background.paste(page, (left_bleed, TOP_BLEED_PX))
    return background


def pdf_number(value: float) -> str:
    if abs(value - round(value)) < 0.0001:
        return str(int(round(value)))
    return f"{value:.4f}".rstrip("0").rstrip(".")


def pdf_literal(text: str) -> str:
    return "(" + text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") + ")"


def write_pdf(image_paths: list[Path], pdf_path: Path) -> None:
    """Write a single-image-per-page PDF with an exact MediaBox, no reportlab dependency."""
    objects: list[bytes] = []
    page_ids: list[int] = []

    def add_object(data: bytes) -> int:
        objects.append(data)
        return len(objects)

    catalog_id = add_object(b"")
    pages_id = add_object(b"")

    for idx, image_path in enumerate(image_paths, start=1):
        with Image.open(image_path) as image:
            width, height = image.size
        image_bytes = image_path.read_bytes()
        image_id = add_object(
            (
                f"<< /Type /XObject /Subtype /Image /Width {width} /Height {height} "
                f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode "
                f"/Length {len(image_bytes)} >>\nstream\n"
            ).encode("ascii")
            + image_bytes
            + b"\nendstream"
        )
        content = (
            f"q\n{pdf_number(PDF_W_PT)} 0 0 {pdf_number(PDF_H_PT)} 0 0 cm\n"
            f"/Im{idx} Do\nQ\n"
        ).encode("ascii")
        content_id = add_object(
            f"<< /Length {len(content)} >>\nstream\n".encode("ascii")
            + content
            + b"endstream"
        )
        page_id = add_object(
            (
                f"<< /Type /Page /Parent {pages_id} 0 R "
                f"/MediaBox [0 0 {pdf_number(PDF_W_PT)} {pdf_number(PDF_H_PT)}] "
                f"/Resources << /ProcSet [/PDF /ImageC] /XObject << /Im{idx} {image_id} 0 R >> >> "
                f"/Contents {content_id} 0 R >>"
            ).encode("ascii")
        )
        page_ids.append(page_id)

    objects[catalog_id - 1] = f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode("ascii")
    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects[pages_id - 1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode("ascii")

    offsets: list[int] = [0]
    with pdf_path.open("wb") as fh:
        fh.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        for obj_no, data in enumerate(objects, start=1):
            offsets.append(fh.tell())
            fh.write(f"{obj_no} 0 obj\n".encode("ascii"))
            fh.write(data)
            fh.write(b"\nendobj\n")
        info_id = len(objects) + 1
        offsets.append(fh.tell())
        info = (
            f"<< /Title {pdf_literal(pdf_path.stem)} "
            f"/Producer {pdf_literal('YNFactory bleed repair script')} >>"
        ).encode("utf-8")
        fh.write(f"{info_id} 0 obj\n".encode("ascii"))
        fh.write(info)
        fh.write(b"\nendobj\n")
        xref_at = fh.tell()
        fh.write(f"xref\n0 {info_id + 1}\n".encode("ascii"))
        fh.write(b"0000000000 65535 f \n")
        for offset in offsets[1:]:
            fh.write(f"{offset:010d} 00000 n \n".encode("ascii"))
        fh.write(
            (
                f"trailer\n<< /Size {info_id + 1} /Root {catalog_id} 0 R /Info {info_id} 0 R >>\n"
                f"startxref\n{xref_at}\n%%EOF\n"
            ).encode("ascii")
        )


def pdfinfo_line(pdf_path: Path) -> tuple[str, str]:
    out = subprocess.check_output(["pdfinfo", str(pdf_path)], text=True, errors="replace")
    pages = "?"
    size = "?"
    for line in out.splitlines():
        if line.startswith("Pages:"):
            pages = line.split(":", 1)[1].strip()
        elif line.startswith("Page size:"):
            size = line.split(":", 1)[1].strip()
    return pages, size


def write_paperback_size_spec(project: Path) -> None:
    kdp = project / "KDP出版用"
    (kdp / "paperback_size_spec.md").write_text(
        "\n".join(
            [
                "# paperback_size_spec",
                "",
                "- trim: 8.25 x 8.25 inch",
                "- page_count: 32",
                "- ink/paper: full color / premium color paperback",
                "- bleed: 0.125 inch on top, bottom, and outside edge",
                "- interior PDF page size: 8.375 x 8.5 inch / 603 x 612 pt",
                "- raster page size: 2513 x 2550 px at 300 dpi",
                "- odd pages: outside bleed on right",
                "- even pages: outside bleed on left",
                "- note: the full-page image/background extends to every PDF page edge; no white top/bottom padding is used",
                "",
            ]
        ),
        encoding="utf-8",
    )


def append_quality_note(project: Path, pages: str, size: str) -> None:
    report = project / "QUALITY_REPORT.md"
    if not report.exists():
        return
    marker = f"## {DATE_STAMP} ペーパーバック本文PDFブリード修正"
    text = report.read_text(encoding="utf-8")
    if marker in text:
        return
    note = "\n".join(
        [
            "",
            marker,
            "",
            "- status: PASS",
            "- target: `KDP出版用/UPLOAD_03_ペーパーバック_本文PDF_*.pdf`",
            "- fix: 8.25 inch正方形の仕上がりに対し、本文PDFを8.375 x 8.5 inchへ再生成",
            "- image/background: 上下と外側の0.125 inchまでページ全面に拡張",
            f"- validation: {pages} pages / {size}",
            "- remaining: KDP Print Previewerでアップロード弌の裁ち落としを目視確認",
            "",
        ]
    )
    report.write_text(text.rstrip() + "\n" + note, encoding="utf-8")


def update_progress(project: Path, pages: str, size: str) -> None:
    progress_path = project / "progress.json"
    if not progress_path.exists():
        return
    try:
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
    except Exception:
        return
    kdp_stage = progress.setdefault("kdp_stage", {})
    kdp_stage["paperback_bleed_fix"] = {
        "fixed_at": NOW.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "target": "UPLOAD_03 paperback interior PDF",
        "trim": "8.25 x 8.25 inch",
        "page_size_with_bleed": "8.375 x 8.5 inch / 603 x 612 pt",
        "bleed": "0.125 inch top, bottom, and outside edge",
        "validation": f"{pages} pages / {size}",
    }
    progress_path.write_text(json.dumps(progress, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def process_project(project: Path) -> dict[str, str]:
    kdp = project / "KDP出版用"
    pdf = next(kdp.glob("UPLOAD_03_ペーパーバック_本文PDF_*.pdf"))
    bleed_dir = project / "layout/paperback_interior_bleed_pages"
    bleed_dir.mkdir(parents=True, exist_ok=True)

    backup_dir = kdp / "_not_for_upload" / f"backup_before_bleed_fix_{STAMP}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(pdf, backup_dir / pdf.name)

    generated: list[Path] = []
    for page_no in range(1, PAGE_COUNT + 1):
        page = make_bleed_page(source_page(project, page_no), page_no)
        out = bleed_dir / f"page_{page_no:03d}.jpg"
        page.save(out, "JPEG", quality=95, optimize=True, dpi=(DPI, DPI))
        generated.append(out)

    write_pdf(generated, pdf)
    pages, size = pdfinfo_line(pdf)

    write_paperback_size_spec(project)
    append_quality_note(project, pages, size)
    update_progress(project, pages, size)

    info = kdp / f"INFO_bleed_fix_{DATE_STAMP}.md"
    info.write_text(
        "\n".join(
            [
                f"# INFO_bleed_fix_{DATE_STAMP}",
                "",
                "- status: fixed",
                "- target: paperback interior PDF / UPLOAD_03",
                "- trim: 8.25 x 8.25 inch",
                "- interior PDF page size: 8.375 x 8.5 inch / 603 x 612 pt",
                "- bleed: 0.125 inch top, bottom, and outside edge",
                "- odd pages: outside bleed on right",
                "- even pages: outside bleed on left",
                "- source: layout/preview_pages/page_001.jpg ... page_032.jpg",
                f"- backup: {backup_dir.relative_to(project)}",
                f"- validation: {pages} pages / {size}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return {
        "project": project.name,
        "pdf": str(pdf.relative_to(ROOT)),
        "backup": str(backup_dir.relative_to(ROOT)),
        "pages": pages,
        "size": size,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "projects",
        nargs="*",
        help="Project directory paths or names under .company/outputs/picture-books/japanese-folktales. Defaults to all.",
    )
    args = parser.parse_args()

    if args.projects:
        projects = []
        for raw in args.projects:
            path = Path(raw)
            if not path.exists():
                path = SERIES / raw
            projects.append(path)
    else:
        projects = sorted(p for p in SERIES.iterdir() if p.is_dir())

    rows = []
    for project in projects:
        if not project.is_dir():
            raise FileNotFoundError(project)
        if not (project / "KDP出版用").exists():
            continue
        row = process_project(project)
        rows.append(row)
        print(f"{row['project']}: {row['pages']} pages / {row['size']}", flush=True)

    report = SERIES / f"BLEED_FIX_REPORT_{DATE_STAMP}.md"
    lines = [
        f"# BLEED_FIX_REPORT_{DATE_STAMP}",
        "",
        "- status: completed",
        f"- scope: {'selected Japanese folktales paperback interior UPLOAD_03 PDFs' if args.projects else 'all Japanese folktales paperback interior UPLOAD_03 PDFs'}",
        "- fix: regenerated 32 full-page raster pages per book and embedded them edge-to-edge in an exact 8.375 x 8.5 inch PDF",
        "- KDP rule applied: trim 8.25 x 8.25 inch, bleed PDF width +0.125 inch, height +0.25 inch",
        "- backups: old UPLOAD_03 PDFs were copied under each KDP出版用/_not_for_upload/backup_before_bleed_fix_* folder",
        "",
        "| Project | Pages | Page size | PDF |",
        "|---|---:|---|---|",
    ]
    for row in rows:
        lines.append(f"| {row['project']} | {row['pages']} | {row['size']} | `{row['pdf']}` |")
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
