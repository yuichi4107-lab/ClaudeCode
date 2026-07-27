# -*- coding: utf-8 -*-
"""エントリポイント: python3 run_daily.py [rsi2|basis]"""
import os
import sys
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from common import notify  # noqa: E402


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "rsi2"
    try:
        if mode == "rsi2":
            import rsi2_engine
            rsi2_engine.run()
        elif mode == "basis":
            import basis_monitor
            basis_monitor.run()
        else:
            raise SystemExit(f"unknown mode: {mode}")
    except SystemExit:
        raise
    except Exception:
        err = traceback.format_exc()
        print(err)
        notify(f"❌ quant-bot {mode} エラー:\n{err[-600:]}")
        sys.exit(1)


if __name__ == "__main__":
    main()
