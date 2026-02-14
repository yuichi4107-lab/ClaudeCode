#!/usr/bin/env python3
"""NAR 出走表ページの構造分析"""

import sys
sys.path.insert(0, '/app')

from nankan_predictor.scraper.nar_race_list import NARRaceListScraper
from bs4 import BeautifulSoup
import json

def analyze_shutuba_page():
    """NAR 出走表ページの HTML 構造を分析"""
    
    # まずレースID を取得
    list_scraper = NARRaceListScraper(use_cache=False)
    race_ids = list_scraper.get_latest_races()
    
    if not race_ids:
        print("❌ レースを取得できませんでした")
        return
    
    race_id = race_ids[0]
    print(f"✅ サンプルレースID: {race_id}")
    
    # 出走表ページを取得
    from nankan_predictor.scraper.base import BaseScraper
    scraper = BaseScraper(use_cache=False)
    
    shutuba_url = f"https://nar.netkeiba.com/race/shutuba.html?race_id={race_id}"
    print(f"\n📥 取得中: {shutuba_url}")
    
    try:
        html = scraper.get(shutuba_url)
        soup = BeautifulSoup(html, 'html.parser')
        
        # ページサイズ
        print(f"✅ HTML サイズ: {len(html)} bytes")
        
        # レース情報の位置を探す
        print("\n【ページ構造分析】")
        
        # レース情報（日時、標準タイム、馬場状態など）
        race_info = soup.find('div', class_='race_info')
        if race_info:
            print("✅ race_info div を検出")
            print(f"   テキスト: {race_info.get_text()[:200]}")
        
        # 出走馬テーブル
        tables = soup.find_all('table')
        print(f"\n✅ テーブル数: {len(tables)}")
        
        # main テーブルを探す
        for i, table in enumerate(tables):
            rows = table.find_all('tr')
            print(f"   テーブル {i}: {len(rows)} 行")
            
            # ヘッダー行を確認
            if rows:
                header = rows[0]
                cols = header.find_all(['th', 'td'])
                col_names = [col.get_text(strip=True) for col in cols[:10]]
                if col_names:
                    print(f"      ヘッダー: {col_names}")
        
        # div class="RaceData" などの公開情報
        race_data_div = soup.find('div', class_='RaceData')
        if race_data_div:
            print(f"\n✅ RaceData div を検出")
            text = race_data_div.get_text(strip=True)
            print(f"   テキスト: {text[:300]}")
        
        # スクリプトタグ内の JSON など
        scripts = soup.find_all('script')
        print(f"\n✅ スクリプトタグ数: {len(scripts)}")
        
        # 最初のスクリプト（初期化データを含むことが多い）
        if scripts:
            first_script = scripts[0].string
            if first_script:
                print(f"   最初のスクリプト（最初の300文字）:")
                print(f"   {first_script[:300]}")
        
        # リンク情報（馬詳細ページへのリンク）
        links = soup.find_all('a', href=True)
        print(f"\n✅ リンク数: {len(links)}")
        
        # 馬情報リンク（/race/horse/ など）
        horse_links = [a for a in links if '/horse/' in a.get('href', '')]
        print(f"   馬情報リンク: {len(horse_links)}")
        if horse_links:
            print(f"   サンプル: {horse_links[0].get('href')}")
        
        # 騎手リンク
        jockey_links = [a for a in links if '/jockey/' in a.get('href', '')]
        print(f"   騎手情報リンク: {len(jockey_links)}")
        
        # 調教師リンク
        trainer_links = [a for a in links if '/trainer/' in a.get('href', '')]
        print(f"   調教師情報リンク: {len(trainer_links)}")
        
    except Exception as e:
        print(f"❌ エラー: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    analyze_shutuba_page()
