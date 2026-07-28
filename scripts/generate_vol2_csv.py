#!/usr/bin/env python3
"""
vol2 新CSV生成スクリプト
設計書: SCENE_REDESIGN_PLAN.md に基づき、5列+outfit_id形式の新CSVを生成する
"""

import csv
import io
import json
import re
import os

# outfit_presets の description マッピング
OUTFIT_PRESETS = {
    "misaki_casual": "ボーダー柄（白と紺）のカットソーにデニムパンツ、白いスニーカー（自宅・外出・育児中の普段着）",
    "misaki_work_home": "グレーのスウェット上下、髪を緩くまとめ、素足（深夜〜早朝のPC作業・在宅集中タイム）",
    "misaki_formal": "紺のジャケットに白ブラウス、黒いスラックス、パンプス（OL時代・退職日・過去回想シーン）",
    "takuya_zoom_mentor": "白い無地のTシャツ、自室の白い壁を背景（Zoom・ウェビナー画面越しの指導シーン）",
    "takuya_casual": "薄いグレーのカジュアルシャツにチノパン、黒い革靴（対面・外出時の普段着）",
    "kenta_work_casual": "白い無地のシャツにベージュのチノパン、茶色の革靴（仕事帰り・夜の帰宅シーン）",
    "kenta_casual": "ネイビーのカジュアルシャツにグレーのスラックス、スニーカー（休日・自宅くつろぎシーン）",
    "yamada_suit": "紺色のスーツに白いYシャツ、紺ストライプネクタイ（OL時代の上司として過去回想シーンに登場）",
}

# 作画スタイル共通部分
DRAW_STYLE = "ジャンル: 副業に最適化した統一スタイル / 作画スタイル: 親しみやすく実践的,現代的なライフスタイル表現 / 色調: 明るく前向きな色調,オレンジ・青・黄色基調,活力ある配色 / 線画: 親しみやすい柔らかな線,カジュアルで読みやすい表現 / 演出: 必要に応じて集中線,効果線,擬音などのマンガらしい演出"

# キャラ外見指定（PNG参照）
CHAR_APPEARANCE = {
    "ミサキ": "ミサキ.pngと100%同一の外見で描画",
    "ひなた": "ひなた（2歳期）は添付のひなた_2歳期.pngと100%同一の外見で描画",
    "ケンタ": "ケンタは添付のケンタ.pngと100%同一の外見で描画",
    "タクヤ": "タクヤは添付のタクヤ.pngと100%同一の外見で描画",
    "山田課長": "山田課長は添付のYamada.pngと100%同一の外見で描画",
}

# 共通プロンプトヘッダー
def make_prompt_header(characters, outfit_id=None):
    """キャラ外見指定とoutfit_id服装指定を生成"""
    lines = [
        "◆【注意】【】で囲まれた単語は感情や状況の指示であり、画像内に文字として描画しないでください",
        "◆【絶対最優先】必ずフルカラーにしてください",
        "◆【絶対最優先】必ず日本のアニメ・マンガ調のイラストで描いてください。実写風・フォトリアル風は禁止です。",
    ]
    for char in characters:
        if char in CHAR_APPEARANCE:
            lines.append(f"◆【絶対最優先】キャラクター外見: {CHAR_APPEARANCE[char]}")
    lines.append("◆【出力サイズ】2:3")
    lines.append("◆【補足情報】上下左右に50ピクセルの余白を設けてください")
    if outfit_id and outfit_id in OUTFIT_PRESETS:
        lines.append(f"◆【補足情報】服装: {OUTFIT_PRESETS[outfit_id]}")
    return "\n".join(lines)

# テンプレ別コマ構成説明
TEMPLATE_DESC = {
    "テンプレ1": "テンプレ1: 全面1コマ",
    "テンプレ2": "テンプレ2: 上下2分割（2コマ）",
    "テンプレ3": "テンプレ3: 上小下大（上1コマ小＋下1コマ大）",
    "テンプレ4": "テンプレ4: 上大下小（上1コマ大＋下1コマ小）",
    "テンプレ5": "テンプレ5: 上・中・下3段（3コマ）",
    "テンプレ6": "テンプレ6: 上1コマ＋下左右2コマ（3コマ）",
    "テンプレ7": "テンプレ7: 4分割（左上・右上・左下・右下）（4コマ）",
}

# ソースCSV読み込み
def load_source_csv(path):
    with open(path, 'rb') as f:
        raw = f.read()
    text = raw.decode('utf-8', errors='replace')
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    pages = {}
    for row in rows[1:]:
        if len(row) >= 4:
            pn = int(row[0].strip())
            pages[pn] = {
                'template': row[1].strip(),
                'prompt': row[2],
                'text_json': row[3],
            }
    return pages

# プロンプトから服装記述を除去してoutfit_id記述に置換
def update_prompt_outfit(original_prompt, outfit_id, characters):
    """元プロンプトの服装行を削除し、outfit_id由来の服装指定に置換する"""
    lines = original_prompt.split('\n')
    new_lines = []
    skip_next = False
    for line in lines:
        if skip_next:
            skip_next = False
            continue
        # 旧服装指定行を除去
        if '◆【補足情報】服装:' in line:
            continue
        new_lines.append(line)

    # outfit_id服装指定を挿入（◆【補足情報】上下左右〜の直後）
    result = []
    inserted = False
    for line in new_lines:
        result.append(line)
        if '◆【補足情報】上下左右に50ピクセルの余白を設けてください' in line and not inserted:
            if outfit_id and outfit_id in OUTFIT_PRESETS:
                result.append(f"◆【補足情報】服装: {OUTFIT_PRESETS[outfit_id]}")
                inserted = True
    return '\n'.join(result)

def merge_text_json(json1_str, json2_str):
    """2ページのテキストJSONを結合する"""
    try:
        j1 = json.loads(json1_str) if json1_str.strip() not in ['', '[]'] else []
        j2 = json.loads(json2_str) if json2_str.strip() not in ['', '[]'] else []
        return json.dumps(j1 + j2, ensure_ascii=False)
    except:
        return json1_str

def merge_story_text(prompt1, prompt2, new_template):
    """2ページのストーリー部分を結合して新テンプレ用に整形"""
    # ストーリー部分を抽出
    def extract_story(prompt):
        idx = prompt.find('◆【ストーリー】')
        if idx >= 0:
            return prompt[idx:]
        return ""

    story1 = extract_story(prompt1)
    story2 = extract_story(prompt2)

    # コマ番号を再採番
    combined = story1.rstrip() + "\n" + story2.strip()
    return combined

# ページ番号→outfit_id のマッピング（現行番号ベース）
def get_outfit_id(page_num):
    """設計書4.3節に基づくoutfit_id割り当て"""
    # テキストページ
    if page_num in [1, 2, 70, 179, 180, 181]:
        return ""
    # P3: キャラクター紹介
    if page_num == 3:
        return "misaki_casual"
    # P4-P9: 第4話扉・日常（昼）
    if 4 <= page_num <= 9:
        return "misaki_casual"
    # P10: ケンタ帰宅22時
    if page_num == 10:
        return "kenta_work_casual"
    # P11-P19: 通帳記帳・経済的焦り
    if 11 <= page_num <= 19:
        return "misaki_casual"
    # P20-P25: ケンタとのソファ会話
    if 20 <= page_num <= 25:
        return "kenta_casual"
    # P26-P37: ミサキ内省・支援センター
    if 26 <= page_num <= 37:
        return "misaki_casual"
    # P38-P69: 深夜夜泣き〜第4話おわり
    if 38 <= page_num <= 69:
        return "misaki_work_home"
    # P71: 第5話扉
    if page_num == 71:
        return "misaki_casual"
    # P72-P98: 深夜夜泣き〜SNS発見
    if 72 <= page_num <= 98:
        return "misaki_work_home"
    # P99-P116: 翌日日中・ウェビナー当日
    if 99 <= page_num <= 116:
        return "misaki_casual"
    # P117-P129: ウェビナー視聴（前半）
    if 117 <= page_num <= 129:
        return "takuya_zoom_mentor"
    # P130-P140: ウェビナー後半（タクヤ）
    if 130 <= page_num <= 140:
        return "takuya_zoom_mentor"
    # P141-P143: 事務職時代の回想（内省ナレーション）
    if 141 <= page_num <= 143:
        return "misaki_casual"
    # P144-P148: ウェビナー終盤・9万円案内
    if 144 <= page_num <= 148:
        return "takuya_zoom_mentor"
    # P149-P158: ウェビナー後の内省・壁
    if 149 <= page_num <= 158:
        return "misaki_casual"
    # P159-P178: 夜・決断〜第5話おわり
    if 159 <= page_num <= 178:
        return "misaki_work_home"
    return "misaki_casual"

def build_merged_prompt(src_pages, pn1, pn2, new_template, outfit_id):
    """2ページを統合した新プロンプトを生成"""
    p1 = src_pages[pn1]
    p2 = src_pages[pn2]

    orig1 = p1['prompt']
    orig2 = p2['prompt']

    # 元プロンプトのヘッダー部分（ストーリーより前）を取得
    def get_header(prompt):
        idx = prompt.find('◆【ストーリー】')
        if idx >= 0:
            return prompt[:idx]
        return prompt

    def get_story(prompt):
        idx = prompt.find('◆【ストーリー】')
        if idx >= 0:
            return prompt[idx:]
        return ""

    header1 = get_header(orig1)
    story1 = get_story(orig1)
    story2 = get_story(orig2)

    # コマ構成を新テンプレに変更
    header_lines = header1.split('\n')
    new_header_lines = []
    for line in header_lines:
        if '◆【コマ構成】' in line:
            new_header_lines.append(f"◆【コマ構成】{TEMPLATE_DESC.get(new_template, new_template)}")
        elif '◆【補足情報】服装:' in line:
            # 後で服装記述を追加するのでスキップ
            continue
        else:
            new_header_lines.append(line)

    # 服装指定を追加
    final_header_lines = []
    outfit_inserted = False
    for line in new_header_lines:
        final_header_lines.append(line)
        if '◆【補足情報】上下左右に50ピクセルの余白を設けてください' in line and not outfit_inserted:
            if outfit_id and outfit_id in OUTFIT_PRESETS:
                final_header_lines.append(f"◆【補足情報】服装: {OUTFIT_PRESETS[outfit_id]}")
                outfit_inserted = True

    # ストーリー統合
    merged_story = story1.rstrip() + "\n" + story2.strip()

    return '\n'.join(final_header_lines) + "\n" + merged_story

def update_single_prompt_outfit(original_prompt, outfit_id):
    """単一ページのプロンプトのoutfit_id服装指定を更新"""
    lines = original_prompt.split('\n')
    new_lines = []
    outfit_inserted = False
    for line in lines:
        if '◆【補足情報】服装:' in line:
            # 既存の服装行を置き換え
            if not outfit_inserted and outfit_id and outfit_id in OUTFIT_PRESETS:
                new_lines.append(f"◆【補足情報】服装: {OUTFIT_PRESETS[outfit_id]}")
                outfit_inserted = True
            # 古い服装指定は捨てる
        else:
            new_lines.append(line)
            if '◆【補足情報】上下左右に50ピクセルの余白を設けてください' in line and not outfit_inserted:
                if outfit_id and outfit_id in OUTFIT_PRESETS:
                    new_lines.append(f"◆【補足情報】服装: {OUTFIT_PRESETS[outfit_id]}")
                    outfit_inserted = True
    return '\n'.join(new_lines)

def main():
    src_path = r'G:\マイドライブ\YNFactory-cc\.company\outputs\ebooks-manga\manga-career-restart\vol2\panels\comicle_output_pre_50char_redesign.csv'
    out_path = r'G:\マイドライブ\YNFactory-cc\.company\outputs\ebooks-manga\manga-career-restart\vol2\panels\comicle_output.csv'

    src_pages = load_source_csv(src_path)
    print(f"Loaded {len(src_pages)} source pages")

    # 設計書に基づく統合マッピング
    # merged: {old_page_1: (old_page_2, new_template)} のdictで、
    # old_page_1 が統合後の代表ページ、old_page_2 は消費される
    # absorbed: {page_to_remove: page_to_absorb_into} の辞書

    # 第4話 直接マージ（2ページ→1ページ）
    merge_map_ep4 = {
        11: (12, "テンプレ5"),   # P11+P12 → テンプレ5
        15: (16, "テンプレ7"),   # P15+P16 → テンプレ7
        18: (19, "テンプレ7"),   # P18+P19 → テンプレ7
        30: (31, "テンプレ7"),   # P30+P31 → テンプレ7
        34: (35, "テンプレ5"),   # P34+P35 → テンプレ5
        36: (37, "テンプレ5"),   # P36+P37 → テンプレ5
        38: (39, "テンプレ5"),   # P38+P39 → テンプレ5
        46: (47, "テンプレ7"),   # P46+P47 → テンプレ7
        52: (53, "テンプレ5"),   # P52+P53 → テンプレ5
        54: (55, "テンプレ5"),   # P54+P55 → テンプレ5
        56: (57, "テンプレ7"),   # P56+P57 → テンプレ7
        58: (59, "テンプレ7"),   # P58+P59 → テンプレ7
        64: (65, "テンプレ7"),   # P64+P65 → テンプレ7
    }

    # 第4話 テンプレ1吸収（remove_page → keep_page に吸収）
    # absorbed_into: {page_to_remove: absorb_target}
    absorbed_ep4 = {
        6: 5,    # P6 → P5に吸収
        17: 16,  # P17 → P16に吸収（P15+P16マージ後のP15に）
        33: 34,  # P33 → P34に転置（P34のコマに吸収、P33は削除）
        48: 47,  # P48 → P47に吸収（P46+P47マージ後のP46に）
        60: 58,  # P60 → P58+P59マージ後に吸収
        67: 66,  # P67 → P66に吸収
        68: 69,  # P68 → P69に転置
    }

    # 第5話 直接マージ
    merge_map_ep5 = {
        78: (79, "テンプレ7"),   # P78+P79 → テンプレ7
        80: (81, "テンプレ7"),   # P80+P81 → テンプレ7
        86: (87, "テンプレ5"),   # P86+P87 → テンプレ5
        97: (98, "テンプレ7"),   # P97+P98 → テンプレ7
        99: (100, "テンプレ5"),  # P99+P100 → テンプレ5
        118: (119, "テンプレ7"), # P118+P119 → テンプレ7
        123: (124, "テンプレ5"), # P123+P124 → テンプレ5
        134: (135, "テンプレ5"), # P134+P135 → テンプレ5
        137: (138, "テンプレ7"), # P137+P138 → テンプレ7
        144: (145, "テンプレ5"), # P144+P145 → テンプレ5
        146: (147, "テンプレ7"), # P146+P147 → テンプレ7
        159: (160, "テンプレ7"), # P159+P160 → テンプレ7
        166: (167, "テンプレ7"), # P166+P167 → テンプレ7
    }

    # 第5話 テンプレ1吸収
    absorbed_ep5 = {
        73: 72,   # P73 → P72に吸収
        75: 74,   # P75 → P74に吸収
        82: 83,   # P82 → P83の前段に
        101: 99,  # P101 → P99+100マージ後に吸収
        110: 109, # P110 → P109に吸収
        125: 126, # P125 → P126の前段に
        130: 131, # P130 → P131の冒頭に
        136: 134, # P136 → P134+P135マージ後に吸収
        140: 137, # P140 → P137+P138マージ後に吸収
        152: 153, # P152 → P153の前段に
        158: 157, # P158 → P157末尾に
        169: 166, # P169 → P166+P167マージ後に吸収
    }

    # 全体マージマップ
    all_merges = {**merge_map_ep4, **merge_map_ep5}
    all_absorbed = {**absorbed_ep4, **absorbed_ep5}

    # 消費（スキップ）されるページ集合
    consumed_pages = set()
    for p1, (p2, tmpl) in all_merges.items():
        consumed_pages.add(p2)
    for removed, _ in all_absorbed.items():
        consumed_pages.add(removed)

    # absorbed_into の対象が merge済みページの場合の解決
    # （例: P17はP16に吸収 → P16はP15+P16のマージ先P15に）
    # absorbed target の正規化
    def resolve_absorb_target(target, all_merges_consumed):
        """吸収先ページが消費済みなら、その統合先を辿る"""
        # P16がP15にマージされた場合、P17はP15に吸収される
        for p1, (p2, tmpl) in all_merges.items():
            if target == p2:
                return p1  # p2はp1に統合されたのでp1が実際の保持ページ
        return target

    # 出力行リスト構築
    output_rows = []
    new_page_num = 1

    # 吸収テキストのバッファ: {keep_page: [absorbed_text_json_items]}
    absorbed_texts = {}
    absorbed_prompts = {}  # {keep_page: [absorbed_story_text]}

    # 吸収先の解決
    resolved_absorbed = {}
    for removed, target in all_absorbed.items():
        real_target = target
        # targetがmergeの消費側(p2)なら統合先(p1)に向ける
        for p1, (p2, tmpl) in all_merges.items():
            if target == p2:
                real_target = p1
                break
        resolved_absorbed[removed] = real_target

    # 吸収テキストを事前収集
    for removed, real_target in resolved_absorbed.items():
        if removed in src_pages:
            p = src_pages[removed]
            if real_target not in absorbed_texts:
                absorbed_texts[real_target] = []
                absorbed_prompts[real_target] = []
            try:
                tj = json.loads(p['text_json']) if p['text_json'].strip() not in ['', '[]'] else []
            except:
                tj = []
            absorbed_texts[real_target].extend(tj)
            # ストーリーテキスト部分
            story_idx = p['prompt'].find('◆【ストーリー】')
            if story_idx >= 0:
                absorbed_prompts[real_target].append(p['prompt'][story_idx:])

    def process_page(old_pn, template_override=None, extra_text_json=None, extra_story_text=None):
        """1ページ分の出力行を生成"""
        if old_pn not in src_pages:
            return None
        p = src_pages[old_pn]
        template = template_override if template_override else p['template']
        outfit_id = get_outfit_id(old_pn)

        if template == "テキストページ":
            # テキストページはプロンプトをそのまま使用、outfit_id=空文字
            return {
                'template': template,
                'prompt': p['prompt'],
                'text_json': p['text_json'],
                'outfit_id': ""
            }

        # プロンプト更新（服装記述をoutfit_id版に変更）
        updated_prompt = update_single_prompt_outfit(p['prompt'], outfit_id)

        # テンプレ変更がある場合はコマ構成行も更新
        if template_override and template_override != p['template']:
            lines = updated_prompt.split('\n')
            new_lines = []
            for line in lines:
                if '◆【コマ構成】' in line:
                    new_lines.append(f"◆【コマ構成】{TEMPLATE_DESC.get(template, template)}")
                else:
                    new_lines.append(line)
            updated_prompt = '\n'.join(new_lines)

        # 吸収テキストを追加
        text_json_data = []
        try:
            text_json_data = json.loads(p['text_json']) if p['text_json'].strip() not in ['', '[]'] else []
        except:
            pass

        if extra_text_json:
            text_json_data.extend(extra_text_json)

        if old_pn in absorbed_texts:
            text_json_data.extend(absorbed_texts[old_pn])

        # 吸収ストーリーテキストをプロンプトに追加
        if old_pn in absorbed_prompts and absorbed_prompts[old_pn]:
            extra_stories = "\n".join(absorbed_prompts[old_pn])
            if '◆【ストーリー】' in updated_prompt:
                updated_prompt = updated_prompt.rstrip() + "\n" + extra_stories.replace('◆【ストーリー】\n', '')
            else:
                updated_prompt += "\n" + extra_stories

        if extra_story_text:
            updated_prompt = updated_prompt.rstrip() + "\n" + extra_story_text

        return {
            'template': template,
            'prompt': updated_prompt,
            'text_json': json.dumps(text_json_data, ensure_ascii=False) if text_json_data else '[]',
            'outfit_id': outfit_id
        }

    def process_merged_page(old_pn1, old_pn2, new_template):
        """2ページを統合した出力行を生成"""
        outfit_id = get_outfit_id(old_pn1)

        p1 = src_pages[old_pn1]
        p2 = src_pages[old_pn2]

        # プロンプト統合
        merged_prompt = build_merged_prompt(src_pages, old_pn1, old_pn2, new_template, outfit_id)

        # テキストJSON統合
        text_json_data = []
        try:
            t1 = json.loads(p1['text_json']) if p1['text_json'].strip() not in ['', '[]'] else []
            t2 = json.loads(p2['text_json']) if p2['text_json'].strip() not in ['', '[]'] else []
            text_json_data = t1 + t2
        except:
            pass

        # 吸収テキスト追加
        if old_pn1 in absorbed_texts:
            text_json_data.extend(absorbed_texts[old_pn1])
        if old_pn2 in absorbed_texts:
            text_json_data.extend(absorbed_texts[old_pn2])

        # 吸収ストーリー追加
        extra_stories = []
        for key in [old_pn1, old_pn2]:
            if key in absorbed_prompts and absorbed_prompts[key]:
                extra_stories.extend(absorbed_prompts[key])
        if extra_stories:
            extra = "\n".join(extra_stories).replace('◆【ストーリー】\n', '')
            merged_prompt = merged_prompt.rstrip() + "\n" + extra

        return {
            'template': new_template,
            'prompt': merged_prompt,
            'text_json': json.dumps(text_json_data, ensure_ascii=False) if text_json_data else '[]',
            'outfit_id': outfit_id
        }

    # 全181ページを処理
    for old_pn in range(1, 182):
        if old_pn in consumed_pages:
            # このページは他のページに統合・吸収された
            continue

        if old_pn in all_merges:
            # このページが2つのページを統合する代表ページ
            p2, new_tmpl = all_merges[old_pn]
            row_data = process_merged_page(old_pn, p2, new_tmpl)
        else:
            # 単一ページ処理
            row_data = process_page(old_pn)

        if row_data:
            output_rows.append({
                'page_num': new_page_num,
                **row_data
            })
            new_page_num += 1

    print(f"Generated {len(output_rows)} pages")

    # テンプレ分布確認
    tmpl_dist = {}
    for r in output_rows:
        t = r['template']
        tmpl_dist[t] = tmpl_dist.get(t, 0) + 1
    print("Template distribution:")
    for k, v in sorted(tmpl_dist.items()):
        print(f"  {k}: {v}")

    # outfit_id分布確認
    outfit_dist = {}
    for r in output_rows:
        oid = r['outfit_id']
        outfit_dist[oid] = outfit_dist.get(oid, 0) + 1
    print("outfit_id distribution:")
    for k, v in sorted(outfit_dist.items()):
        print(f"  '{k}': {v}")

    # 50字超過チェック
    over_50 = 0
    total_panels = 0
    for r in output_rows:
        if r['template'] == 'テキストページ':
            continue
        try:
            panels = json.loads(r['text_json'])
            for p in panels:
                if isinstance(p, dict) and 'text' in p:
                    total_panels += 1
                    if len(p['text']) > 50:
                        over_50 += 1
        except:
            pass

    print(f"Total panels: {total_panels}")
    print(f"Over 50 chars: {over_50} ({over_50/total_panels*100:.1f}%)" if total_panels > 0 else "No panels")

    # CSV出力
    with open(out_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f, quoting=csv.QUOTE_ALL)
        writer.writerow(['ページ番号', '使用するコマ割りテンプレ', '漫画作成のプロンプト', 'コマ別テキストJSON', 'outfit_id'])
        for r in output_rows:
            writer.writerow([
                r['page_num'],
                r['template'],
                r['prompt'],
                r['text_json'],
                r['outfit_id']
            ])

    print(f"Written to: {out_path}")
    return output_rows

if __name__ == '__main__':
    main()
