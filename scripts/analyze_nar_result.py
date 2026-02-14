#!/usr/bin/env python3
"""NAR 結果ページの構造分析"""

import sys
sys.path.insert(0, '/app')

from nankan_predictor.scraper.nar_race_list import NARRaceListScraper
from bs4 import BeautifulSoup

def analyze_result_page():
    """NAR 結果ページの HTML 構造を分析"""
    
    # レースID を取得
    list_scraper = NARRaceListScraper(use_cache=False)
    race_ids = list_scraper.get_latest_races()
    
    if not race_ids:
        print("❌ レースを取得できませんでした")
        return
    
    race_id = race_ids[0]
    print(f"✅ サンプルレースID: {race_id}")
    
    # 結果ページを取得
    from nankan_predictor.scraper.base import BaseScraper
    scraper = BaseScraper(use_cache=False)
    
    result_url = f"https://nar.netkeiba.com/race/result.html?race_id={race_id}"
    print(f"\n📥 取得中: {result_url}")
    
    try:
        html = scraper.get(result_url)
        soup = BeautifulSoup(html, 'html.parser')
        
        # ページサイズ
        print(f"✅ HTML サイズ: {len(html)} bytes")
        
        print("\n【ページ構造分析】")
        
        # テーブル情報
        tables = soup.find_all('table')
        print(f"✅ テーブル数: {len(tables)}")
        
        # 各テーブルの詳細
        for i, table in enumerate(tables):
            rows = table.find_all('tr')
            print(f"\n   テーブル {i}: {len(rows)} 行")
            
            # ヘッダーと最初の数行を表示
            if rows:
                # ヘッダー
                header = rows[0]
                cols = header.find_all(['th', 'td'])
                col_names = [col.get_text(strip=True) for col in cols[:15]]
                if col_names:
                    print(f"      ヘッダー: {col_names}")
                
                # 最初のデータ行
                if len(rows) > 1:
                    data = rows[1]
                    data_cols = data.find_all(['td'])
                    data_vals = [col.get_text(strip=True) for col in data_cols[:15]]
                    if data_vals:
                        print(f"      データ1: {data_vals}")
        
        # レース情報（日時、馬場、標準タイムなど）
        print(f"\n✅ テキスト情報検索:")
        
        # 「第」などの通常の文字列から日付けを推測
        div_list = soup.find_all('div')
        
        for div in div_list:
            text = div.get_text(strip=True)
            if '第' in text and '日目' in text:
                print(f"   開催情報: {text[:100]}")
                break
        
        # 払戻情報
        print(f"\n✅ 払戻情報検索:")
        payout_text = soup.find_all(string=lambda text: text and '馬連' in text)
        if payout_text:
            print(f"   馬連情報見つかり: {len(payout_text)} 件")
            if payout_text:
                print(f"   サンプル: {payout_text[0][:100]}")
        
        # リンク情報
        links = soup.find_all('a', href=True)
        horse_links = [a for a in links if '/horse/' in a.get('href', '')]
        print(f"\n✅ 馬情報リンク: {len(horse_links)}")
        
    except Exception as e:
        print(f"❌ エラー: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    analyze_result_page()
