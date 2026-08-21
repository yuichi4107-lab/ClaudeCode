#!/usr/bin/env python3
"""Validate theme-to-ebook packages and enforce the 100k-character batch gate."""

from __future__ import annotations

import argparse
from collections import Counter
import json
import re
import zipfile
from pathlib import Path


EXPECTED_MANUSCRIPTS = [
    "00_はじめに.md",
    "01_第1章.md",
    "02_第2章.md",
    "03_第3章.md",
    "04_第4章.md",
    "05_第5章.md",
    "06_おわりに.md",
]

EXPECTED_FILES = [
    "project.md",
    "progress.json",
    "_research/theme_research.md",
    "manuscript/_outline.md",
    "images/image_plan.md",
    "KDP出版用/書籍情報.md",
    "KDP出版用/ジャンル・キーワード.md",
    "KDP出版用/書籍紹介文_HTML.html",
    "KDP出版用/cover.png",
    "KDP出版用/cover.jpg",
    "final_quality_report.md",
]


def visible_text(markdown: str) -> str:
    """Return approximate reader-visible text from a Markdown manuscript."""
    text = re.sub(r"```.*?```", "", markdown, flags=re.S)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"^\s{0,3}(?:#{1,6}|>|[-+*]|\d+[.)])\s*", "", text, flags=re.M)
    text = re.sub(r"[*_~`]", "", text)
    text = re.sub(r"\s+", "", text)
    return text


def sentence_repetition_metrics(markdowns: list[str]) -> dict[str, object]:
    """Measure exact repeated reader-visible sentences.

    The ratio counts only the second and later occurrence of a sentence with
    at least 20 visible characters.  This catches template padding while
    allowing short labels and ordinary connective phrases to recur.
    """
    sentences: list[str] = []
    total_visible = 0
    for markdown in markdowns:
        rendered = visible_text(markdown)
        total_visible += len(rendered)
        for sentence in re.split(r"(?<=[。！？!?])", rendered):
            normalized = re.sub(r"\s+", "", sentence)
            if len(normalized) >= 20:
                sentences.append(normalized)
    counts = Counter(sentences)
    duplicate_extra_chars = sum(
        (count - 1) * len(sentence)
        for sentence, count in counts.items()
        if count > 1
    )
    top_repeated = [
        {"count": count, "chars": len(sentence), "text": sentence[:240]}
        for sentence, count in sorted(
            counts.items(), key=lambda item: (-item[1], -len(item[0]), item[0])
        )
        if count > 1
    ][:20]
    ratio = duplicate_extra_chars / total_visible if total_visible else 0.0
    return {
        "sentence_count": len(sentences),
        "unique_sentence_count": len(counts),
        "duplicate_extra_chars": duplicate_extra_chars,
        "duplicate_extra_ratio": ratio,
        "top_repeated": top_repeated,
    }


def duplicate_long_paragraphs(markdowns: list[str]) -> list[dict[str, object]]:
    """Return exact duplicate Markdown paragraphs of 80+ visible characters."""
    paragraphs: list[str] = []
    for markdown in markdowns:
        for block in re.split(r"\n\s*\n", markdown):
            normalized = re.sub(r"^\s{0,3}(?:#{1,6}|>|[-+*]|\d+[.)])\s*", "", block)
            normalized = re.sub(r"[*_~`]", "", normalized)
            normalized = re.sub(r"\s+", "", normalized)
            if len(normalized) >= 80:
                paragraphs.append(normalized)
    counts = Counter(paragraphs)
    return [
        {"count": count, "chars": len(text), "text": text[:240]}
        for text, count in sorted(
            counts.items(), key=lambda item: (-item[1], -len(item[0]), item[0])
        )
        if count > 1
    ]


def find_markdown_images(markdown: str) -> list[str]:
    return re.findall(r"!\[[^\]]*\]\(([^)]+)\)", markdown)


def validate_epub(path: Path) -> dict[str, object]:
    result: dict[str, object] = {
        "path": str(path),
        "exists": path.exists(),
        "zip_ok": False,
        "mimetype_first": False,
        "error": None,
    }
    if not path.exists():
        return result
    try:
        with zipfile.ZipFile(path) as archive:
            result["zip_ok"] = archive.testzip() is None
            names = archive.namelist()
            result["mimetype_first"] = bool(names and names[0] == "mimetype")
    except (OSError, zipfile.BadZipFile) as exc:
        result["error"] = str(exc)
    return result


def validate_book(
    book_dir: Path,
    minimum: int,
    maximum: int,
    max_repeat_ratio: float = 0.05,
) -> dict[str, object]:
    manuscript_dir = book_dir / "manuscript"
    missing = [item for item in EXPECTED_FILES if not (book_dir / item).exists()]
    missing.extend(
        f"manuscript/{name}"
        for name in EXPECTED_MANUSCRIPTS
        if not (manuscript_dir / name).exists()
    )

    counts: dict[str, int] = {}
    combined_visible = ""
    missing_images: list[str] = []
    banned_hits: list[str] = []
    manuscript_markdowns: list[str] = []

    for name in EXPECTED_MANUSCRIPTS:
        path = manuscript_dir / name
        if not path.exists():
            continue
        markdown = path.read_text(encoding="utf-8")
        manuscript_markdowns.append(markdown)
        rendered = visible_text(markdown)
        counts[name] = len(rendered)
        combined_visible += rendered
        if "<figcaption" in markdown.lower() or "図解:" in markdown or "図解：" in markdown:
            banned_hits.append(name)
        for image_ref in find_markdown_images(markdown):
            image_path = (path.parent / image_ref).resolve()
            if not image_path.exists():
                missing_images.append(f"{name}: {image_ref}")

    epubs = sorted((book_dir / "KDP出版用").glob("*.epub")) if (book_dir / "KDP出版用").exists() else []
    epub_reports = [validate_epub(path) for path in epubs]
    if not epubs:
        missing.append("KDP出版用/*.epub")

    total = len(combined_visible)
    char_gate = minimum <= total <= maximum
    repetition = sentence_repetition_metrics(manuscript_markdowns)
    repetition_gate = repetition["duplicate_extra_ratio"] < max_repeat_ratio
    paragraph_duplicates = duplicate_long_paragraphs(manuscript_markdowns)
    paragraph_duplicate_gate = not paragraph_duplicates
    unrelated_faq_safety_hits = sum(
        markdown.count("影響が大きい判断では「") for markdown in manuscript_markdowns
    )
    faq_relevance_gate = unrelated_faq_safety_hits == 0
    epub_gate = bool(epub_reports) and all(
        report["zip_ok"] and report["mimetype_first"] for report in epub_reports
    )
    passed = (
        not missing
        and char_gate
        and not missing_images
        and not banned_hits
        and repetition_gate
        and paragraph_duplicate_gate
        and faq_relevance_gate
        and epub_gate
    )

    return {
        "slug": book_dir.name,
        "path": str(book_dir),
        "passed": passed,
        "visible_char_count": total,
        "char_range": {"min": minimum, "max": maximum},
        "char_gate": char_gate,
        "chapter_counts": counts,
        "sentence_repetition": repetition,
        "max_repeat_ratio": max_repeat_ratio,
        "repetition_gate": repetition_gate,
        "duplicate_long_paragraphs": paragraph_duplicates,
        "paragraph_duplicate_gate": paragraph_duplicate_gate,
        "unrelated_faq_safety_hits": unrelated_faq_safety_hits,
        "faq_relevance_gate": faq_relevance_gate,
        "missing_files": sorted(set(missing)),
        "missing_images": sorted(set(missing_images)),
        "banned_caption_hits": sorted(set(banned_hits)),
        "epubs": epub_reports,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("books", nargs="+", type=Path)
    parser.add_argument("--min", dest="minimum", type=int, default=95_000)
    parser.add_argument("--max", dest="maximum", type=int, default=105_000)
    parser.add_argument("--max-repeat-ratio", type=float, default=0.05)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    reports = [
        validate_book(
            path.resolve(), args.minimum, args.maximum, args.max_repeat_ratio
        )
        for path in args.books
    ]
    payload = {
        "passed": all(report["passed"] for report in reports),
        "book_count": len(reports),
        "passed_count": sum(bool(report["passed"]) for report in reports),
        "reports": reports,
    }
    serialized = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
