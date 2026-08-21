#!/usr/bin/env python3
"""
Deprecated compatibility wrapper.

KDP cover generation must use ChatGPT Pro Web / ChatGPT Images 2.0 /
gpt-image-2. This script does not call image APIs. It creates a small prompt
package and exits with a non-zero status so callers cannot mistake it for a
completed cover generation step.
"""

import argparse
import datetime as dt
import json
import sys
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(
        description="Prepare a ChatGPT Pro Web gpt-image-2 cover prompt package; no API calls are made."
    )
    parser.add_argument("--prompt-file", required=True, help="Path to cover prompt text file (UTF-8)")
    parser.add_argument("--char-refs", required=True, nargs="+", help="One or more character reference PNGs")
    parser.add_argument("--out", required=True, help="Intended output PNG path")
    parser.add_argument("--size", default="1024x1536", help="Target image size")
    parser.add_argument("--quality", default="high", help="Requested quality note for the Web prompt")
    parser.add_argument("--model", default="gpt-image-2", help="Expected Web model name")
    return parser.parse_args()


def main():
    args = parse_args()
    prompt_path = Path(args.prompt_file)
    out_path = Path(args.out)
    package_dir = out_path.parent / "cover_gpt_image2_web_prompt_package"
    package_dir.mkdir(parents=True, exist_ok=True)

    prompt_text = prompt_path.read_text(encoding="utf-8") if prompt_path.exists() else ""
    manifest = {
        "status": "blocked_gpt_image2_web",
        "reason": "This compatibility script is not allowed to call image APIs. Generate the cover in ChatGPT Pro Web.",
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "model": args.model,
        "target_size": args.size,
        "quality": args.quality,
        "intended_output": str(out_path),
        "prompt_file": str(prompt_path),
        "character_references": args.char_refs,
    }

    (package_dir / "cover_prompt_for_chatgpt_web.txt").write_text(prompt_text, encoding="utf-8")
    (package_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (package_dir / "cover_status.md").write_text(
        "# Cover Status\n\n"
        "status: blocked_gpt_image2_web\n\n"
        "This script intentionally did not generate an image. Use ChatGPT Pro Web / "
        "ChatGPT Images 2.0 / gpt-image-2 with the prompt and reference images, then "
        f"save the final PNG to `{out_path}`.\n",
        encoding="utf-8",
    )

    print(f"[BLOCKED] API image generation is disabled. Prompt package: {package_dir}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
