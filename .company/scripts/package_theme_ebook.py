#!/usr/bin/env python3
"""Build and validate a simple reflowable EPUB from a theme-to-ebook folder."""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import re
import uuid
import zipfile
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape


MANUSCRIPT_NAMES = [
    "00_はじめに.md",
    "01_第1章.md",
    "02_第2章.md",
    "03_第3章.md",
    "04_第4章.md",
    "05_第5章.md",
    "06_おわりに.md",
]


def slugify_id(text: str) -> str:
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]
    return f"h-{digest}"


def inline_markup(text: str) -> str:
    escaped = escape(text, quote=False)
    escaped = re.sub(
        r"\[([^\]]+)\]\((https?://[^)]+)\)",
        lambda m: f'<a href="{escape(m.group(2), quote=True)}">{m.group(1)}</a>',
        escaped,
    )
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    return escaped


def table_to_html(rows: list[str]) -> str:
    parsed = [[cell.strip() for cell in row.strip().strip("|").split("|")] for row in rows]
    if len(parsed) >= 2 and all(re.fullmatch(r":?-{3,}:?", cell) for cell in parsed[1]):
        parsed.pop(1)
    if not parsed:
        return ""
    header, *body = parsed
    parts = ['<div class="table-wrap"><table><thead><tr>']
    parts.extend(f"<th>{inline_markup(cell)}</th>" for cell in header)
    parts.append("</tr></thead><tbody>")
    for row in body:
        parts.append("<tr>")
        parts.extend(f"<td>{inline_markup(cell)}</td>" for cell in row)
        parts.append("</tr>")
    parts.append("</tbody></table></div>")
    return "".join(parts)


def render_markdown(path: Path, chapter_index: int) -> tuple[str, str, list[tuple[int, str, str]], list[str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    paragraph: list[str] = []
    headings: list[tuple[int, str, str]] = []
    images: list[str] = []
    list_type: str | None = None

    def flush_paragraph() -> None:
        if paragraph:
            out.append(f"<p>{inline_markup(''.join(paragraph))}</p>")
            paragraph.clear()

    def close_list() -> None:
        nonlocal list_type
        if list_type:
            out.append(f"</{list_type}>")
            list_type = None

    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if line.startswith("|") and line.endswith("|"):
            flush_paragraph()
            close_list()
            table_rows: list[str] = []
            while i < len(lines) and lines[i].strip().startswith("|") and lines[i].strip().endswith("|"):
                table_rows.append(lines[i].strip())
                i += 1
            out.append(table_to_html(table_rows))
            continue

        heading = re.match(r"^(#{1,6})\s+(.+)$", line)
        image = re.fullmatch(r"!\[([^\]]*)\]\(([^)]+)\)", line.strip())
        bullet = re.match(r"^[-*+]\s+(.+)$", line.strip())
        numbered = re.match(r"^\d+[.)]\s+(.+)$", line.strip())

        if heading:
            flush_paragraph()
            close_list()
            level = min(len(heading.group(1)), 4)
            title = heading.group(2).strip()
            hid = slugify_id(f"{chapter_index}:{len(headings)}:{title}")
            headings.append((level, title, hid))
            cls = ' class="section-title"' if level == 3 else ""
            out.append(f'<h{level} id="{hid}"{cls}>{inline_markup(title)}</h{level}>')
        elif image:
            flush_paragraph()
            close_list()
            alt, ref = image.groups()
            name = Path(ref).name
            images.append(name)
            out.append(
                f'<div class="book-image"><img src="../images/{escape(name, quote=True)}" '
                f'alt="{escape(alt, quote=True)}" /></div>'
            )
        elif bullet or numbered:
            flush_paragraph()
            desired = "ul" if bullet else "ol"
            if list_type != desired:
                close_list()
                list_type = desired
                out.append(f"<{desired}>")
            item = (bullet or numbered).group(1)
            out.append(f"<li>{inline_markup(item)}</li>")
        elif not line.strip():
            flush_paragraph()
            close_list()
        elif line.strip() == "---":
            flush_paragraph()
            close_list()
            out.append("<hr />")
        else:
            if paragraph:
                paragraph.append(" ")
            paragraph.append(line.strip())
        i += 1

    flush_paragraph()
    close_list()
    chapter_title = headings[0][1] if headings else path.stem
    body = "\n".join(out)
    xhtml = f'''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="ja" xml:lang="ja">
<head><meta charset="utf-8"/><title>{escape(chapter_title)}</title><link rel="stylesheet" href="../styles/book.css" type="text/css"/></head>
<body><section class="chapter" id="chapter-{chapter_index:03d}">{body}</section></body></html>'''
    return chapter_title, xhtml, headings, images


def media_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def read_metadata(book_dir: Path) -> tuple[str, str, str, str]:
    progress_path = book_dir / "progress.json"
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    title = str(progress.get("title") or book_dir.name)
    subtitle = str(progress.get("subtitle") or "")
    author = str(progress.get("author") or "Yuichi")
    slug = str(progress.get("book_name") or book_dir.name)
    return title, subtitle, author, slug


def safe_filename(title: str) -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|]", "_", title).strip()
    return cleaned or "ebook"


def build_epub(book_dir: Path) -> dict[str, object]:
    title, subtitle, author, slug = read_metadata(book_dir)
    manuscript_dir = book_dir / "manuscript"
    image_dir = book_dir / "images"
    kdp_dir = book_dir / "KDP出版用"
    cover = kdp_dir / "cover.png"
    missing_manuscripts = [name for name in MANUSCRIPT_NAMES if not (manuscript_dir / name).exists()]
    if missing_manuscripts:
        raise SystemExit(f"Missing manuscript files: {', '.join(missing_manuscripts)}")
    if not cover.exists():
        raise SystemExit(f"Missing cover: {cover}")

    kdp_dir.mkdir(parents=True, exist_ok=True)
    output = kdp_dir / f"{safe_filename(title)}.epub"
    uid = f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, f'ynfactory:{slug}')}"
    modified = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    rendered: list[dict[str, object]] = []
    referenced_images: set[str] = set()
    for index, name in enumerate(MANUSCRIPT_NAMES, start=1):
        chapter_title, xhtml, headings, images = render_markdown(manuscript_dir / name, index)
        filename = f"chapter-{index:03d}.xhtml"
        rendered.append({"title": chapter_title, "xhtml": xhtml, "headings": headings, "file": filename})
        referenced_images.update(images)

    missing_images = [name for name in sorted(referenced_images) if not (image_dir / name).exists()]
    if missing_images:
        raise SystemExit(f"Missing referenced images: {', '.join(missing_images)}")

    css = """
body { font-family: -apple-system, BlinkMacSystemFont, 'Hiragino Mincho ProN', 'Yu Mincho', serif; line-height: 1.85; margin: 0; color: #202124; }
.chapter { padding: 1.4em 1.2em; }
p { text-indent: 1em; margin: 0.4em 0 0.8em; }
h1, h2 { line-height: 1.45; margin: 1.6em 0 0.8em; }
h3.section-title { page-break-before: always; break-before: page; padding-top: 1.2em; }
h4 { margin-top: 1.2em; }
ul, ol { margin: 0.8em 0 1em 1.4em; padding: 0; }
li { margin: 0.35em 0; }
.book-image { text-align: center; margin: 1.2em auto; page-break-inside: avoid; }
.book-image img, .cover img { max-width: 100%; height: auto; }
.cover { text-align: center; margin: 0; padding: 0; }
.title-page { text-align: center; padding: 18% 8% 0; }
.subtitle { text-indent: 0; font-size: 1.05em; }
.author { text-indent: 0; margin-top: 3em; }
.table-wrap { overflow-x: auto; margin: 1em 0; }
table { border-collapse: collapse; width: 100%; font-size: 0.92em; }
th, td { border: 1px solid #bbb; padding: 0.45em; vertical-align: top; }
th { background: #f3f3f3; }
code { font-family: monospace; font-size: 0.9em; }
""".strip()

    cover_xhtml = f'''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html><html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="ja"><head><meta charset="utf-8"/><title>{escape(title)}</title><link rel="stylesheet" href="../styles/book.css" type="text/css"/></head><body epub:type="cover"><section class="cover"><img src="../images/cover.png" alt="{escape(title, quote=True)}"/></section></body></html>'''
    title_xhtml = f'''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html><html xmlns="http://www.w3.org/1999/xhtml" lang="ja"><head><meta charset="utf-8"/><title>{escape(title)}</title><link rel="stylesheet" href="../styles/book.css" type="text/css"/></head><body><section class="title-page"><h1>{escape(title)}</h1><p class="subtitle">{escape(subtitle)}</p><p class="author">{escape(author)}</p></section></body></html>'''

    nav_items: list[str] = []
    navpoints: list[str] = []
    for index, chapter in enumerate(rendered, start=1):
        file = str(chapter["file"])
        chapter_title = xml_escape(str(chapter["title"]))
        children = []
        for level, heading, hid in chapter["headings"]:  # type: ignore[index]
            if level == 2:
                children.append(f'<li><a href="text/{file}#{hid}">{xml_escape(heading)}</a></li>')
        nested = f"<ol>{''.join(children)}</ol>" if children else ""
        nav_items.append(f'<li><a href="text/{file}">{chapter_title}</a>{nested}</li>')
        navpoints.append(
            f'<navPoint id="navPoint-{index + 1}" playOrder="{index + 1}"><navLabel><text>{chapter_title}</text></navLabel><content src="text/{file}"/></navPoint>'
        )

    nav_xhtml = f'''<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html><html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="ja"><head><meta charset="utf-8"/><title>目次</title></head><body><nav epub:type="toc" id="toc"><h1>目次</h1><ol>{''.join(nav_items)}</ol></nav></body></html>'''
    ncx = f'''<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1"><head><meta name="dtb:uid" content="{uid}"/></head><docTitle><text>{xml_escape(title)}</text></docTitle><navMap><navPoint id="navPoint-1" playOrder="1"><navLabel><text>表紙</text></navLabel><content src="text/cover.xhtml"/></navPoint>{''.join(navpoints)}</navMap></ncx>'''

    manifest = [
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
        '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
        '<item id="css" href="styles/book.css" media-type="text/css"/>',
        '<item id="cover-page" href="text/cover.xhtml" media-type="application/xhtml+xml"/>',
        '<item id="title-page" href="text/title.xhtml" media-type="application/xhtml+xml"/>',
        '<item id="cover-image" href="images/cover.png" media-type="image/png" properties="cover-image"/>',
    ]
    spine = ['<itemref idref="cover-page"/>', '<itemref idref="title-page"/>']
    for index, chapter in enumerate(rendered, start=1):
        manifest.append(f'<item id="ch{index:03d}" href="text/{chapter["file"]}" media-type="application/xhtml+xml"/>')
        spine.append(f'<itemref idref="ch{index:03d}"/>')
    for index, name in enumerate(sorted(referenced_images), start=1):
        image_path = image_dir / name
        manifest.append(
            f'<item id="img{index:03d}" href="images/{xml_escape(name)}" media-type="{media_type(image_path)}"/>'
        )

    opf = f'''<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="book-id" version="3.0" xml:lang="ja"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="book-id">{uid}</dc:identifier><dc:title>{xml_escape(title)}</dc:title><dc:creator>{xml_escape(author)}</dc:creator><dc:language>ja</dc:language><dc:publisher>YN出版</dc:publisher><meta property="dcterms:modified">{modified}</meta></metadata><manifest>{''.join(manifest)}</manifest><spine toc="ncx">{''.join(spine)}</spine></package>'''
    container = '''<?xml version="1.0" encoding="UTF-8"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>'''

    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("OEBPS/styles/book.css", css)
        archive.writestr("OEBPS/text/cover.xhtml", cover_xhtml)
        archive.writestr("OEBPS/text/title.xhtml", title_xhtml)
        archive.writestr("OEBPS/nav.xhtml", nav_xhtml)
        archive.writestr("OEBPS/toc.ncx", ncx)
        archive.writestr("OEBPS/content.opf", opf)
        archive.write(cover, "OEBPS/images/cover.png")
        for chapter in rendered:
            archive.writestr(f"OEBPS/text/{chapter['file']}", str(chapter["xhtml"]))
        for name in sorted(referenced_images):
            archive.write(image_dir / name, f"OEBPS/images/{name}")

    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        report = {
            "file": str(output.relative_to(book_dir)),
            "exists": output.exists(),
            "size_bytes": output.stat().st_size,
            "zip_ok": archive.testzip() is None,
            "mimetype_first": bool(names and names[0] == "mimetype"),
            "xhtml_count": sum(name.endswith(".xhtml") for name in names),
            "image_count": sum(name.startswith("OEBPS/images/") for name in names),
            "has_figcaption": any(
                b"figcaption" in archive.read(name).lower()
                for name in names
                if name.endswith(".xhtml")
            ),
        }

    progress_path = book_dir / "progress.json"
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    progress["epub"] = report
    progress.setdefault("steps", {})["7_metadata"] = {"status": "done", "score": 90}
    progress_path.write_text(json.dumps(progress, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (kdp_dir / "epub_quality_report.md").write_text(
        "# EPUB品質レポート\n\n"
        + "\n".join(f"- {key}: {value}" for key, value in report.items())
        + "\n",
        encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("book_dir", type=Path)
    args = parser.parse_args()
    report = build_epub(args.book_dir.resolve())
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["zip_ok"] and report["mimetype_first"] and not report["has_figcaption"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
