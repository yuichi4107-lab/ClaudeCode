#!/usr/bin/env python3
"""NAR 月別レース URL パターンの直接テスト"""

import sys
sys.path.insert(0, '/app')

import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime, timedelta

def test_nar_date_urls():
    """NAR の過去日付 URL パターンをテスト"""
    
    print("【NAR 月別/日別 URL パターンテスト】\n")
    
    # テストする日付範囲（2026-02-14 から過去30日分）
    base_date = datetime(2026, 2, 14)
    
    print("≫ パターン A: /race/shutuba.html + ?date パラメータ")
    for i in range(5):
        test_date = base_date - timedelta(days=i*7)
        date_str = test_date.strftime('%Y%m%d')
        url = f"https://nar.netkeiba.com/race/shutuba.html?date={date_str}"
        
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                race_count = r.text.count('race_id=')
                print(f"  ✅ {date_str}: {r.status_code} (race_id数: {race_count})")
            else:
                print(f"  ❌ {date_str}: {r.status_code}")
        except Exception as e:
            print(f"  ❌ {date_str}: {e}")
    
    print("\n≫ パターン B: /race/ + 日付パス")
    for i in range(5):
        test_date = base_date - timedelta(days=i*7)
        date_str = test_date.strftime('%Y%m%d')
        date_str2 = test_date.strftime('%Y-%m-%d')
        
        for fmt in [date_str, date_str2]:
            url = f"https://nar.netkeiba.com/race/{fmt}/"
            
            try:
                r = requests.get(url, timeout=5)
                if r.status_code == 200:
                    race_count = r.text.count('race_id=')
                    print(f"  ✅ {fmt}: {r.status_code} (race_id数: {race_count})")
            except:
                pass
    
    print("\n≫ パターン C: 月別アーカイブ URL")
    # NAR の月別ページ URL を推測
    nar_months = [
        ("202602", "2026年2月"),
        ("202601", "2026年1月"),
        ("202512", "2025年12月"),
    ]
    
    for month_code, month_name in nar_months:
        url = f"https://nar.netkeiba.com/race/{month_code}/"
        
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                race_count = r.text.count('race_id=')
                print(f"  ✅ {month_code}: {r.status_code} (race_id数: {race_count})")
            else:
                print(f"  ❌ {month_code}: {r.status_code}")
        except Exception as e:
            print(f"  ❌ {month_code}: {type(e).__name__}")
    
    print("\n≫ パターン D: netkeiba.com JRA 側月別ページ（参考）")
    # db.netkeiba.com 側の月別ページ URL 構造
    url = "https://db.netkeiba.com/?pid=race_list&start_year=2026&start_mon=2&end_year=2026&end_mon=2"
    
    try:
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            race_count = r.text.count('race/')
            print(f"  ✅ DB monthly URL: {r.status_code} (race数推定: {race_count})")
    except Exception as e:
        print(f"  ❌ DB monthly URL: {type(e).__name__}")
    
    # API エンドポイント探索
    print("\n≫ パターン E: API エンドポイント推測")
    api_urls = [
        "https://nar.netkeiba.com/api/races",
        "https://nar.netkeiba.com/api/races?date=20260214",
        "https://api.netkeiba.com/races",
        "https://api.netkeiba.com/nar/races?month=202602",
    ]
    
    for url in api_urls:
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                print(f"  ✅ {url}: {r.status_code}")
                print(f"     Content-Type: {r.headers.get('content-type')}")
                print(f"     サイズ: {len(r.text)} bytes")
        except:
            pass

if __name__ == "__main__":
    test_nar_date_urls()
