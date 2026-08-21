from __future__ import annotations

import argparse
import sys

from .browser import BrowserAutomationError
from .config import load_config
from .runner import RoomAutomationRunner
from .sheets import SheetError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rakuten ROOM auto posting")
    parser.add_argument("--config", help="Path to config.yaml")
    sub = parser.add_subparsers(dest="command", required=True)

    preview = sub.add_parser("preview", help="Show candidate rows without updates")
    preview.add_argument("--limit", type=int, default=None)

    prepare = sub.add_parser("prepare", help="Move unposted rows to approval pending")
    prepare.add_argument("--limit", type=int, default=None)
    prepare.add_argument("--dry-run", action="store_true")

    replenish = sub.add_parser("replenish", help="Add ranking items when remaining rows run low")
    replenish.add_argument("--dry-run", action="store_true")

    approve = sub.add_parser("approve", help="Auto-approve pending rows after pre-checks")
    approve.add_argument("--limit", type=int, default=None)
    approve.add_argument("--dry-run", action="store_true")

    run = sub.add_parser("run", help="Post approved rows")
    run.add_argument("--limit", type=int, default=None)
    run.add_argument("--dry-run", action="store_true")

    sub.add_parser("check-session", help="Check Rakuten ROOM login session")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cfg = load_config(args.config)
        runner = RoomAutomationRunner(cfg)
        if args.command == "preview":
            rows = runner.preview(args.limit)
            if not rows:
                print("No candidate rows.")
                return 0
            for row in rows:
                url = row.get("product_url", cfg.sheet.columns)
                status = row.get("status", cfg.sheet.columns)
                desc = row.get("description", cfg.sheet.columns)
                print(f"row={row.row_number} status={status or '(blank)'} desc={'yes' if desc else 'no'} url={url}")
            return 0
        if args.command == "prepare":
            summary = runner.prepare(args.limit, dry_run=args.dry_run)
            print(summary)
            return 0 if summary.errors == 0 else 2
        if args.command == "replenish":
            summary = runner.replenish(dry_run=args.dry_run)
            print(summary)
            return 0 if summary.errors == 0 else 2
        if args.command == "approve":
            summary = runner.approve(args.limit, dry_run=args.dry_run)
            print(summary)
            return 0 if summary.errors == 0 else 2
        if args.command == "run":
            summary = runner.run(args.limit, dry_run=args.dry_run)
            print(summary)
            return 0 if summary.errors == 0 else 2
        if args.command == "check-session":
            print(runner.check_session())
            return 0
    except (BrowserAutomationError, SheetError, FileNotFoundError) as exc:
        print(f"[ERR] {exc}", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
