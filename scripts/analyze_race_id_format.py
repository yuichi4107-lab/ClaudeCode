#!/usr/bin/env python3
"""NAR レースID デコード & ページメタデータ分析"""

import sys
sys.path.insert(0, '/app')

from nankan_predictor.scraper.nar_race_list import NARRaceListScraper
from bs4 import BeautifulSoup

def analyze_race_metadata():
    """NAR レース ID フォーマット分析とページメタデータ取得"""
    
    # レースID を取得
    list_scraper = NARRaceListScraper(use_cache=False)
    race_ids = list_scraper.get_latest_races()
    
    if not race_ids:
        print("❌ レースを取得できませんでした")
        return
    
    print(f"✅ 取得レース数: {len(race_ids)}")
    print(f"   サンプルレースID: {race_ids[:3]}")
    
    # レースID の形式を分析
    print(f"\n【レースID フォーマット分析】")
    sample_id = race_ids[0]
    print(f"ID: {sample_id}")
    print(f"  年（Y）: {sample_id[0:4]}")
    print(f"  月？ : {sample_id[4:6]}")
    print(f"  会場: {sample_id[6:8]}")
    print(f"  レース日: {sample_id[8:10]}")
    print(f"  レース番: {sample_id[10:12]}")
    
    # 出走表ページから日時・馬場を取得してみる
    from nankan_predictor.scraper.base import BaseScraper
    scraper = BaseScraper(use_cache=False)
    
    shutuba_url = f"https://nar.netkeiba.com/race/shutuba.html?race_id={sample_id}"
    print(f"\n【出走表ページからメタデータ抽出】")
    
    try:
        html = scraper.get(shutuba_url)
        soup = BeautifulSoup(html, 'html.parser')
        
        # メタタグからタイトルを取得（レース情報を含むことがある）
        title = soup.find('title')
        if title:
            print(f"✅ ページタイトル: {title.get_text()}")
        
        # meta description
        meta_desc = soup.find('meta', {'name': 'description'})
        if meta_desc:
            print(f"✅ 説明: {meta_desc.get('content')}")
        
        # Open Graph (og:title など)
        og_title = soup.find('meta', {'property': 'og:title'})
        if og_title:
            print(f"✅ OG:title: {og_title.get('content')}")
        
        # ページ内の全テキストから日付情報を探す
        print(f"\n【ページテキストから情報検索】")
        
        # 競馬場情報
        text_content = soup.get_text()
        
        # 「浦和」「大井」「川崎」「船橋」など会場名を探す
        venues = ['浦和', '大井', '川崎', '船橋']
        found_venue = None
        for v in venues:
            if v in text_content:
                found_venue = v
                break
        
        if found_venue:
            print(f"✅ 会場: {found_venue}")
        
        # 「曇」「晴」などの天気を探す
        weathers = ['晴', '曇', '雨', '雪']
        for w in weathers:
            if w in text_content and f'{w}' in text_content:
                print(f"✅ 天気の可能性: {w}")
        
        # div や span などの構造化データを探す
        divs = soup.find_all('div', class_=['race_info', 'race_data', 'RaceData', 'track_info'])
        print(f"\n✅ 構造化情報div: {len(divs)} 個見つかり")
        for div in divs:
            text = div.get_text(strip=True)[:150]
            print(f"   {div.get('class')}: {text}")
        
        # Script タグから JSON を探す
        print(f"\n【JSON スキーマからレース情報抽出】")
        scripts = soup.find_all('script', type='application/ld+json')
        if scripts:
            print(f"✅ JSON-LD スクリプト: {len(scripts)} 個")
            for i, script in enumerate(scripts[:2]):
                content = script.string
                if content:
                    print(f"   スクリプト {i} ({len(content)} 文字): {content[:150]}...")
        
    except Exception as e:
        print(f"❌ エラー: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    analyze_race_metadata()
