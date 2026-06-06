#!/usr/bin/env python3
"""過去レース（全頭オッズ＋勝敗）から人気-穴バイアス β を較正する。

使い方:
    python run_calibrate.py history.csv

history.csv 列: race_id, odds, won(1/0)。各 race_id に勝ち馬 1 頭(won=1)。
推定した β を run_odds.py の --beta に渡して使う。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from popularity.calibration import fit_beta, load_history  # noqa: E402


def main():
    if len(sys.argv) < 2:
        print("usage: python run_calibrate.py history.csv")
        return
    races = load_history(sys.argv[1])
    res = fit_beta(races)
    print("=" * 56)
    print("人気-穴バイアス β 較正結果")
    print("-" * 56)
    print(f"  レース数        : {res['n_races']}")
    print(f"  推定 β          : {res['beta']:.3f}")
    print(f"  対数尤度(β)      : {-res['nll']:.2f}")
    print(f"  対数尤度(β=1基準): {-res['baseline_nll']:.2f}")
    gain = res["baseline_nll"] - res["nll"]
    print(f"  改善(対数尤度)   : {gain:+.2f}")
    if res["beta"] > 1.05:
        print("  → 本命を市場より高く評価すべき（本命は過小評価＝買い）")
    elif res["beta"] < 0.95:
        print("  → 穴を市場より高く評価すべき（本命は過大評価）")
    else:
        print("  → ほぼ市場どおり（補正の効果は小さい）")
    print(f"\n  使い方: python run_odds.py odds.csv --beta {res['beta']:.3f}")


if __name__ == "__main__":
    main()
