#!/usr/bin/env python3
"""NAR アーカイブページの URL 構造探索"""

import sys
sys.path.insert(0, '/app')

import requests
from bs4 import BeautifulSoup
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def explore_nar_month_page():
    """NAR 月別ページの URL 構造を探索"""
    
    # NAR のいくつかの月別 URL パターンをテスト
    base_url = "https://nar.netkeiba.com/top/"
    
    print("【NAR 月別ページ探索】\n")
    
    # パターン1: top ページのクエリパラメータ
    print("≫ パターン1: トップページ + クエリパラメータ")
    test_urls = [
        f"{base_url}",
        f"{base_url}?date=20260201",
        f"{base_url}?year=2026&month=02",
        f"{base_url}?ym=202602",
    ]
    
    for url in test_urls:
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, 'html.parser')
                race_count = len(soup.find_all('a', href=lambda x: x and 'race_id=' in (x or '')))
                print(f"  ✅ {url}")
                print(f"     → {r.status_code}, レース数推定: {race_count}\n")
            else:
                print(f"  ❌ {url}")
                print(f"     → ステータス: {r.status_code}\n")
        except Exception as e:
            print(f"  ❌ {url}")
            print(f"     → エラー: {e}\n")
    
    # パターン2: race list ページ
    print("≫ パターン2: race list ページ")
    test_urls = [
        "https://nar.netkeiba.com/race/list/",
        "https://nar.netkeiba.com/race/list.html",
        "https://nar.netkeiba.com/top/race_list/",
    ]
    
    for url in test_urls:
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                print(f"  ✅ {url} (ステータス {r.status_code})")
                # リンク構造を確認
                soup = BeautifulSoup(r.text, 'html.parser')
                links = soup.find_all('a', href=True)[:10]
                if links:
                    print(f"     サンプルリンク:")
                    for link in links[:3]:
                        print(f"       - {link.get('href')}")
                print()
            else:
                print(f"  ❌ {url} (ステータス {r.status_code})\n")
        except Exception as e:
            print(f"  ❌ {url} (エラー: {e})\n")
    
    # パターン3: 特定日付ページ
    print("≫ パターン3: 特定日付ページ")
    test_urls = [
        "https://nar.netkeiba.com/race/20260214/",
        "https://nar.netkeiba.com/race/2026-02-14/",
    ]
    
    for url in test_urls:
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, 'html.parser')
                race_count = len(soup.find_all('a', href=lambda x: x and 'race_id=' in (x or '')))
                print(f"  ✅ {url}")
                print(f"     → ステータス: {r.status_code}, レース数: {race_count}\n")
            else:
                print(f"  ❌ {url} (ステータス {r.status_code})\n")
        except Exception as e:
            print(f"  ❌ {url} (エラー: {e})\n")

if __name__ == "__main__":
    explore_nar_month_page()
