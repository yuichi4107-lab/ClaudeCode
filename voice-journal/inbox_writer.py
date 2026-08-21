"""
inbox_writer.py
Append transcribed text to inbox daily markdown file.
Format: inbox_dir/YYYY-MM-DD.md, with ## HH:MM-HH:MM headings.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


def append(
    start_dt: datetime,
    end_dt: datetime,
    text: str,
    note: str = None,
    inbox_dir: str = None,
) -> None:
    """
    Append a transcription segment to the inbox daily file.

    Parameters
    ----------
    start_dt : datetime
        Segment start time.
    end_dt : datetime
        Segment end time.
    text : str
        Transcribed text. If empty, uses placeholder.
    inbox_dir : str | None
        Override inbox directory (for testing). If None, reads from config.
    """
    if inbox_dir is None:
        # Load from config.json relative to this module's location
        import json
        config_path = Path(__file__).parent / "config.json"
        with open(config_path, encoding="utf-8") as f:
            cfg = json.load(f)
        inbox_dir = cfg["inbox_dir"]

    inbox_path = Path(inbox_dir)
    inbox_path.mkdir(parents=True, exist_ok=True)

    date_str = start_dt.strftime("%Y-%m-%d")
    file_path = inbox_path / f"{date_str}.md"

    header_line = f"# {date_str} 音声ログ\n"
    section_header = (
        f"\n## {start_dt.strftime('%H:%M')}–{end_dt.strftime('%H:%M')}\n"
    )
    body = text if text else "（無音/認識なし）"
    note_line = f"> ⚠ {note}\n\n" if note else ""
    entry = f"{section_header}\n{note_line}{body}\n"

    if not file_path.exists():
        # Create new file with header
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(header_line)
        logger.info("Created inbox file: %s", file_path)

    # Append entry (never overwrite)
    with open(file_path, "a", encoding="utf-8") as f:
        f.write(entry)

    logger.info("Appended to %s: %s-%s", file_path, start_dt.strftime("%H:%M"), end_dt.strftime("%H:%M"))
