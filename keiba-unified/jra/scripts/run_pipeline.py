"""フルパイプライン実行スクリプト

Full pipeline: scrape -> features -> train -> backtest -> report

Usage:
    python -m scripts.run_pipeline
    python -m scripts.run_pipeline --skip-scrape
    python -m scripts.run_pipeline --skip-scrape --skip-features
"""

import argparse
import subprocess
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def main():
    parser = argparse.ArgumentParser(description="JRA Keiba Full Pipeline")
    parser.add_argument("--skip-scrape", action="store_true", help="Skip scraping step")
    parser.add_argument("--skip-features", action="store_true", help="Skip feature building step")
    parser.add_argument("--skip-train", action="store_true", help="Skip model training step")
    args = parser.parse_args()

    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    scripts = []
    if not args.skip_scrape:
        scripts.append("scripts/01_scrape_races.py")
    if not args.skip_features:
        scripts.append("scripts/02_build_features.py")
    if not args.skip_train:
        scripts.append("scripts/03_train_model.py")
    scripts.append("scripts/04_run_backtest.py")
    scripts.append("scripts/05_generate_report.py")

    for script in scripts:
        script_path = os.path.join(project_root, script)
        print(f"\n{'=' * 60}")
        print(f"Running: {script}")
        print(f"{'=' * 60}")
        result = subprocess.run(
            [sys.executable, script_path],
            cwd=project_root,
        )
        if result.returncode != 0:
            print(f"\nError in {script} (exit code {result.returncode})")
            sys.exit(1)

    print(f"\n{'=' * 60}")
    print("Pipeline completed successfully!")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
