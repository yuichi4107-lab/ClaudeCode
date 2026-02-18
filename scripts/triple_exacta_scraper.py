#!/usr/bin/env python3
"""トリプル馬単の結果をnankankeiba.comからスクレイプして保存するスクリプト。

Usage:
    python scripts/triple_exacta_scraper.py --year 2025 --year 2026
    python scripts/triple_exacta_scraper.py --url "https://www.nankankeiba.com/jyusyosiki_result/20260306.do?month=alltuki&jo=alljo"
"""

import argparse
import csv
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nankan_predictor.scraper.triple_exacta import TripleExactaScraper

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

OUTPUT_DIR = Path("data/triple_exacta")


def scrape_year(scraper: TripleExactaScraper, year: int) -> list[dict]:
    results = scraper.scrape_results(year)
    return [r.to_dict() for r in results]


def scrape_url(scraper: TripleExactaScraper, url: str) -> tuple[str, list[dict]]:
    # URLからパラメータを分離
    from urllib.parse import urlparse, parse_qs

    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    params = {k: v[0] for k, v in parse_qs(parsed.query).items()}

    html, results = scraper.scrape_results_raw(base, params)
    return html, [r.to_dict() for r in results]


def save_results(results: list[dict], filename: str):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # JSON保存
    json_path = OUTPUT_DIR / f"{filename}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    logger.info("Saved %d results to %s", len(results), json_path)

    # CSV保存
    if results:
        csv_path = OUTPUT_DIR / f"{filename}.csv"
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=results[0].keys())
            writer.writeheader()
            writer.writerows(results)
        logger.info("Saved CSV to %s", csv_path)


def save_raw_html(html: str, filename: str):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    html_path = OUTPUT_DIR / f"{filename}.html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    logger.info("Saved raw HTML to %s", html_path)


def main():
    parser = argparse.ArgumentParser(description="トリプル馬単結果スクレイパー")
    parser.add_argument("--year", type=int, action="append", help="対象年 (複数指定可)")
    parser.add_argument("--url", type=str, action="append", help="直接URLを指定 (複数指定可)")
    parser.add_argument("--save-html", action="store_true", help="HTMLも保存する")
    args = parser.parse_args()

    if not args.year and not args.url:
        parser.error("--year か --url のいずれかを指定してください")

    scraper = TripleExactaScraper(rate_limit=3.0, use_cache=True)

    all_results = []

    if args.year:
        for year in args.year:
            results = scrape_year(scraper, year)
            all_results.extend(results)
            save_results(results, f"triple_exacta_{year}")

    if args.url:
        for i, url in enumerate(args.url):
            html, results = scrape_url(scraper, url)
            all_results.extend(results)
            save_results(results, f"triple_exacta_url_{i}")
            if args.save_html:
                save_raw_html(html, f"triple_exacta_url_{i}")

    if all_results:
        save_results(all_results, "triple_exacta_all")
        logger.info("Total: %d results collected", len(all_results))
    else:
        logger.warning("No results could be parsed. The site may be blocking access.")
        logger.info("Please try manually downloading the HTML pages and use the analysis script with --csv option.")


if __name__ == "__main__":
    main()
