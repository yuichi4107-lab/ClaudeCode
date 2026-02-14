#!/usr/bin/env python3
"""NAR トップページの詳細分析 - アーカイブリンク探索"""

import sys
sys.path.insert(0, '/app')

from nankan_predictor.scraper.base import BaseScraper
from bs4 import BeautifulSoup
import re

def analyze_nar_top_structure():
    """NAR トップページから月別/アーカイブリンク構造を分析"""
    
    scraper = BaseScraper(use_cache=False)
    html = scraper.get("https://nar.netkeiba.com/")
    soup = BeautifulSoup(html, 'html.parser')
    
    print("【NAR トップページ構造分析】\n")
    
    # すべてのリンクを抽出
    links = soup.find_all('a', href=True)
    
    # パターン別にリンクを分類
    print(f"✅ 総リンク数: {len(links)}\n")
    
    # race_id リンク
    race_id_links = [a for a in links if 'race_id=' in a.get('href', '')]
    print(f"🔗 race_id リンク: {len(race_id_links)} 個")
    if race_id_links:
        print(f"   サンプル: {race_id_links[0].get('href')}")
    
    # 月別/アーカイブリンク（月の名前を含むもの）
    print(f"\n【月別関連リンク探索】")
    
    months = ['1月', '2月', '3月', '4月', '5月', '6月', '7月', '8月', '9月', '10月', '11月', '12月']
    month_links = {}
    
    for link in links:
        text = link.get_text(strip=True)
        href = link.get('href', '')
        
        for month in months:
            if month in text:
                if month not in month_links:
                    month_links[month] = []
                month_links[month].append((text, href))
    
    if month_links:
        print(f"✅ 月別リンク検出: {len(month_links)} 月")
        for month, links_list in sorted(month_links.items()):
            print(f"   {month}: {len(links_list)} 個")
            for text, href in links_list[:2]:
                print(f"      - {text[:30]}: {href[:60]}")
    else:
        print("❌ 月別リンクが見つかりませんでした")
    
    # 日付パターンリンク（YYYYMMDD 形式など）
    print(f"\n【日付パターンリンク探索】")
    date_pattern = re.compile(r'\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{8}')
    date_links = []
    
    for link in links:
        href = link.get('href', '')
        text = link.get_text(strip=True)
        
        if date_pattern.search(href) or date_pattern.search(text):
            date_links.append((text, href))
    
    if date_links:
        print(f"✅ 日付パターンリンク: {len(date_links)} 個")
        for text, href in date_links[:5]:
            print(f"   {text[:20]}: {href[:60]}")
    else:
        print("❌ 日付パターンリンクが見つかりませんでした")
    
    # 「開催情報」「成績」など情報ページリンク
    print(f"\n【情報ページリンク探索】")
    info_keywords = ['開催', '成績', 'アーカイブ', 'バックナンバー', '過去', 'レース一覧']
    info_links = {}
    
    for link in links:
        text = link.get_text(strip=True)
        href = link.get('href', '')
        
        for keyword in info_keywords:
            if keyword in text:
                if keyword not in info_links:
                    info_links[keyword] = []
                info_links[keyword].append((text, href))
    
    if info_links:
        print(f"✅ 情報ページリンク検出: {len(info_links)} パターン")
        for keyword, links_list in info_links.items():
            print(f"   {keyword}: {len(links_list)} 個")
            for text, href in links_list[:1]:
                print(f"      - {href[:70]}")
    else:
        print("❌ 情報ページリンクが見つかりませんでした")
    
    # 開催予定日および直近の開催日
    print(f"\n【開催予定/実績関連の div/要素探索】")
    divs = soup.find_all('div', class_=lambda x: x and ('plan' in x.lower() or 'race' in x.lower() or 'schedule' in x.lower()))
    if divs:
        print(f"✅ 開催関連 div: {len(divs)} 個")
        for div in divs[:3]:
            print(f"   class={div.get('class')}, text={div.get_text(strip=True)[:50]}")
    
    # nav/aside リンク構造
    print(f"\n【ナビゲーション構造】")
    navs = soup.find_all(['nav', 'aside'])
    if navs:
        print(f"✅ nav/aside: {len(navs)} 個")
        for nav in navs[:2]:
            nav_links = nav.find_all('a', href=True)
            if nav_links:
                print(f"   内部リンク数: {len(nav_links)}")
                print(f"   サンプル: {nav_links[0].get('href')}")

if __name__ == "__main__":
    analyze_nar_top_structure()
