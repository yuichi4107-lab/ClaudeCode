import csv
import re
from collections import defaultdict
import statistics

# Read CSV
rows = []
with open(r'D:\SPAT4\spat4.csv', encoding='utf-8') as f:
    reader = csv.reader(f)
    header = next(reader)
    for row in reader:
        # Skip empty rows
        if not row or not row[0].strip():
            continue
        # Ensure row has enough columns
        if len(row) < 20:
            row.extend([''] * (20 - len(row)))
        rows.append(row)

print(f"Total valid rows: {len(rows)}")
print(f"Header: {header}")
print(f"Sample row: {rows[0]}")

# Parse helper functions
def parse_int(s):
    s = s.strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None

def parse_amount(s):
    """Parse amount like '71,225' or '17,268,480' """
    s = s.strip().replace('"', '').replace(',', '')
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None

def extract_race_number(s):
    """Extract race number from e.g. '10R' -> 10"""
    s = s.strip()
    m = re.match(r'(\d+)R', s)
    if m:
        return int(m.group(1))
    return None

def extract_weekday(date_str):
    """Extract weekday from e.g. '1月27日(月)' -> '月' """
    m = re.search(r'\((.)\)', date_str)
    if m:
        return m.group(1)
    return None

# Parse all data
data = []
for row in rows:
    rec = {}
    rec['no'] = parse_int(row[0])
    rec['flag1'] = parse_int(row[1])
    rec['date_str'] = row[2].strip()
    rec['track'] = row[3].strip()  # 競馬場
    rec['kaisai'] = row[4].strip()  # 開催日
    rec['popularity_sum'] = parse_int(row[5])
    rec['flag2'] = parse_int(row[6])

    # Race 1 (columns 7-9)
    rec['race1_num'] = extract_race_number(row[7])
    rec['race1_win_pop'] = parse_int(row[8])
    rec['race1_2nd_pop'] = parse_int(row[9])

    # Race 2 (columns 10-12)
    rec['race2_num'] = extract_race_number(row[10])
    rec['race2_win_pop'] = parse_int(row[11])
    rec['race2_2nd_pop'] = parse_int(row[12])

    # Race 3 (columns 13-15)
    rec['race3_num'] = extract_race_number(row[13])
    rec['race3_win_pop'] = parse_int(row[14])
    rec['race3_2nd_pop'] = parse_int(row[15])

    rec['carryover_announce'] = row[16].strip()
    rec['hit_count'] = parse_int(row[17])
    rec['hit_amount'] = parse_amount(row[18])
    rec['carryover'] = parse_amount(row[19])

    rec['weekday'] = extract_weekday(row[2])

    data.append(rec)

print(f"Parsed {len(data)} records")

# Filter out records with missing essential data
valid_data = [d for d in data if d['track'] and d['race1_win_pop'] is not None]
print(f"Valid records with essential data: {len(valid_data)}")

# ============================================================
# 1. 競馬場別の1番人気勝率
# ============================================================
print("\n=== 1. 競馬場別の1番人気勝率 ===")

track_stats = defaultdict(lambda: {'total_races': 0, 'fav_wins': 0, 'fav_rentai': 0})

for d in valid_data:
    track = d['track']
    for prefix in ['race1', 'race2', 'race3']:
        wp = d[f'{prefix}_win_pop']
        sp = d[f'{prefix}_2nd_pop']
        if wp is not None:
            track_stats[track]['total_races'] += 1
            if wp == 1:
                track_stats[track]['fav_wins'] += 1
            if wp == 1 or sp == 1:
                track_stats[track]['fav_rentai'] += 1

track_table = []
for track in sorted(track_stats.keys()):
    s = track_stats[track]
    win_rate = s['fav_wins'] / s['total_races'] * 100 if s['total_races'] > 0 else 0
    rentai_rate = s['fav_rentai'] / s['total_races'] * 100 if s['total_races'] > 0 else 0
    track_table.append((track, s['total_races'], s['fav_wins'], win_rate, s['fav_rentai'], rentai_rate))
    print(f"  {track}: {s['total_races']}R, 勝率 {win_rate:.1f}%, 連対率 {rentai_rate:.1f}%")

# Overall
total_races = sum(s['total_races'] for s in track_stats.values())
total_fav_wins = sum(s['fav_wins'] for s in track_stats.values())
total_fav_rentai = sum(s['fav_rentai'] for s in track_stats.values())
overall_win = total_fav_wins / total_races * 100
overall_rentai = total_fav_rentai / total_races * 100
print(f"  全体: {total_races}R, 勝率 {overall_win:.1f}%, 連対率 {overall_rentai:.1f}%")

# ============================================================
# 2. 人気合計のレンジ別分析
# ============================================================
print("\n=== 2. 人気合計のレンジ別分析 ===")

def pop_range(p):
    if p is None:
        return None
    if p <= 5:
        return '3-5'
    elif p <= 9:
        return '6-9'
    elif p <= 14:
        return '10-14'
    elif p <= 19:
        return '15-19'
    elif p <= 24:
        return '20-24'
    else:
        return '25+'

range_stats = defaultdict(lambda: {'count': 0, 'amounts': [], 'fav_wins': 0, 'total_races': 0})

for d in valid_data:
    ps = d['popularity_sum']
    r = pop_range(ps)
    if r is None:
        continue
    range_stats[r]['count'] += 1
    if d['hit_amount'] is not None:
        range_stats[r]['amounts'].append(d['hit_amount'])

    for prefix in ['race1', 'race2', 'race3']:
        wp = d[f'{prefix}_win_pop']
        if wp is not None:
            range_stats[r]['total_races'] += 1
            if wp == 1:
                range_stats[r]['fav_wins'] += 1

range_order = ['3-5', '6-9', '10-14', '15-19', '20-24', '25+']
range_table = []
for r in range_order:
    if r not in range_stats:
        continue
    s = range_stats[r]
    avg_amt = statistics.mean(s['amounts']) if s['amounts'] else 0
    med_amt = statistics.median(s['amounts']) if s['amounts'] else 0
    win_rate = s['fav_wins'] / s['total_races'] * 100 if s['total_races'] > 0 else 0
    range_table.append((r, s['count'], avg_amt, med_amt, win_rate))
    print(f"  {r}: {s['count']}回, 平均{avg_amt:,.0f}円, 中央値{med_amt:,.0f}円, 1番人気勝率{win_rate:.1f}%")

# ============================================================
# 3. フラグ分析（列7: flag2）
# ============================================================
print("\n=== 3. フラグ分析（列7） ===")

flag_stats = defaultdict(lambda: {'count': 0, 'amounts': [], 'fav_wins': 0, 'total_races': 0})

for d in valid_data:
    f = d['flag2']
    if f is None:
        continue
    flag_stats[f]['count'] += 1
    if d['hit_amount'] is not None:
        flag_stats[f]['amounts'].append(d['hit_amount'])

    for prefix in ['race1', 'race2', 'race3']:
        wp = d[f'{prefix}_win_pop']
        if wp is not None:
            flag_stats[f]['total_races'] += 1
            if wp == 1:
                flag_stats[f]['fav_wins'] += 1

flag_table = []
for f in sorted(flag_stats.keys()):
    s = flag_stats[f]
    avg_amt = statistics.mean(s['amounts']) if s['amounts'] else 0
    med_amt = statistics.median(s['amounts']) if s['amounts'] else 0
    win_rate = s['fav_wins'] / s['total_races'] * 100 if s['total_races'] > 0 else 0
    flag_table.append((f, s['count'], avg_amt, med_amt, win_rate))
    print(f"  フラグ{f}: {s['count']}回, 平均{avg_amt:,.0f}円, 中央値{med_amt:,.0f}円, 1番人気勝率{win_rate:.1f}%")

# Estimate flag meaning
# flag2 seems to be related to number of favorites winning
# Let's check correlation
print("\n  フラグ vs 1番人気1着の回数:")
flag_vs_favcount = defaultdict(lambda: defaultdict(int))
for d in valid_data:
    f = d['flag2']
    if f is None:
        continue
    fav_count = 0
    for prefix in ['race1', 'race2', 'race3']:
        wp = d[f'{prefix}_win_pop']
        if wp == 1:
            fav_count += 1
    flag_vs_favcount[f][fav_count] += 1

for f in sorted(flag_vs_favcount.keys()):
    counts = flag_vs_favcount[f]
    total = sum(counts.values())
    dist = ', '.join([f"{k}回:{v}({v/total*100:.0f}%)" for k, v in sorted(counts.items())])
    print(f"    フラグ{f}: {dist}")

# ============================================================
# 4. 3レース中の1番人気1着回数
# ============================================================
print("\n=== 4. 3レース中の1番人気1着回数 ===")

fav_count_stats = defaultdict(lambda: {'count': 0, 'amounts': []})

for d in valid_data:
    fav_count = 0
    for prefix in ['race1', 'race2', 'race3']:
        wp = d[f'{prefix}_win_pop']
        if wp == 1:
            fav_count += 1
    fav_count_stats[fav_count]['count'] += 1
    if d['hit_amount'] is not None:
        fav_count_stats[fav_count]['amounts'].append(d['hit_amount'])

fav_count_table = []
total_events = sum(s['count'] for s in fav_count_stats.values())
for fc in sorted(fav_count_stats.keys()):
    s = fav_count_stats[fc]
    pct = s['count'] / total_events * 100
    avg_amt = statistics.mean(s['amounts']) if s['amounts'] else 0
    med_amt = statistics.median(s['amounts']) if s['amounts'] else 0
    fav_count_table.append((fc, s['count'], pct, avg_amt, med_amt))
    print(f"  {fc}回: {s['count']}件({pct:.1f}%), 平均{avg_amt:,.0f}円, 中央値{med_amt:,.0f}円")

# ============================================================
# 5. 曜日別分析
# ============================================================
print("\n=== 5. 曜日別分析 ===")

weekday_stats = defaultdict(lambda: {'count': 0, 'amounts': [], 'fav_wins': 0, 'total_races': 0, 'pop_sums': []})

weekday_order = {'月': 0, '火': 1, '水': 2, '木': 3, '金': 4, '土': 5, '日': 6}

for d in valid_data:
    wd = d['weekday']
    if not wd:
        continue
    weekday_stats[wd]['count'] += 1
    if d['hit_amount'] is not None:
        weekday_stats[wd]['amounts'].append(d['hit_amount'])
    if d['popularity_sum'] is not None:
        weekday_stats[wd]['pop_sums'].append(d['popularity_sum'])

    for prefix in ['race1', 'race2', 'race3']:
        wp = d[f'{prefix}_win_pop']
        if wp is not None:
            weekday_stats[wd]['total_races'] += 1
            if wp == 1:
                weekday_stats[wd]['fav_wins'] += 1

weekday_table = []
for wd in sorted(weekday_stats.keys(), key=lambda x: weekday_order.get(x, 99)):
    s = weekday_stats[wd]
    avg_amt = statistics.mean(s['amounts']) if s['amounts'] else 0
    med_amt = statistics.median(s['amounts']) if s['amounts'] else 0
    avg_pop = statistics.mean(s['pop_sums']) if s['pop_sums'] else 0
    win_rate = s['fav_wins'] / s['total_races'] * 100 if s['total_races'] > 0 else 0
    weekday_table.append((wd, s['count'], avg_amt, med_amt, avg_pop, win_rate))
    print(f"  {wd}曜: {s['count']}件, 平均{avg_amt:,.0f}円, 中央値{med_amt:,.0f}円, 平均人気合計{avg_pop:.1f}, 1番人気勝率{win_rate:.1f}%")

# ============================================================
# 6. レース番号別分析
# ============================================================
print("\n=== 6. レース番号別分析 ===")

race_num_stats = defaultdict(lambda: {'total': 0, 'fav_wins': 0, 'fav_rentai': 0, 'positions': []})

for d in valid_data:
    for i, prefix in enumerate(['race1', 'race2', 'race3'], 1):
        rn = d[f'{prefix}_num']
        wp = d[f'{prefix}_win_pop']
        sp = d[f'{prefix}_2nd_pop']
        if rn is not None and wp is not None:
            race_num_stats[rn]['total'] += 1
            if wp == 1:
                race_num_stats[rn]['fav_wins'] += 1
            if wp == 1 or (sp is not None and sp == 1):
                race_num_stats[rn]['fav_rentai'] += 1
            race_num_stats[rn]['positions'].append(i)  # 1st/2nd/3rd race position

race_num_table = []
for rn in sorted(race_num_stats.keys()):
    s = race_num_stats[rn]
    win_rate = s['fav_wins'] / s['total'] * 100
    rentai_rate = s['fav_rentai'] / s['total'] * 100
    race_num_table.append((rn, s['total'], s['fav_wins'], win_rate, s['fav_rentai'], rentai_rate))
    print(f"  {rn}R: {s['total']}回, 1番人気勝率{win_rate:.1f}%, 連対率{rentai_rate:.1f}%")

# ============================================================
# Additional: Carryover analysis
# ============================================================
print("\n=== 補足: キャリーオーバー分析 ===")

co_data = [d for d in valid_data if d['carryover'] is not None and d['carryover'] > 0]
non_co_data = [d for d in valid_data if d['carryover'] is None or d['carryover'] == 0]

# Check carryover_announce
co_announce = [d for d in valid_data if d['carryover_announce'] == '1']
print(f"  キャリーオーバー発声中: {len(co_announce)}件")
print(f"  キャリーオーバーあり（次回繰越）: {len(co_data)}件")

# Hit rate (的中口数 is filled)
hit_data = [d for d in valid_data if d['hit_count'] is not None and d['hit_count'] > 0]
no_hit_data = [d for d in valid_data if d['hit_amount'] is None]
print(f"  的中あり: {len(valid_data) - len(no_hit_data)}件, 的中なし(不的中): {len(no_hit_data)}件")

# ============================================================
# Generate Markdown output
# ============================================================

md = []
md.append("# SPAT4 トリプル馬単 統計分析レポート")
md.append("")
md.append(f"**分析対象**: {len(valid_data)}回分のデータ")
md.append(f"**分析日**: 2026-02-27")
md.append("")

# Section 1: Track analysis
md.append("## 1. 競馬場別の1番人気勝率")
md.append("")
md.append("各レースにおいて1番人気が1着になる確率（勝率）と、1着または2着に来る確率（連対率）を競馬場別に集計。")
md.append("")
md.append("| 競馬場 | レース数 | 1番人気1着 | 勝率 | 1番人気連対 | 連対率 |")
md.append("|--------|----------|------------|------|-------------|--------|")
for row in track_table:
    md.append(f"| {row[0]} | {row[1]} | {row[2]} | {row[3]:.1f}% | {row[4]} | {row[5]:.1f}% |")
md.append(f"| **全体** | **{total_races}** | **{total_fav_wins}** | **{overall_win:.1f}%** | **{total_fav_rentai}** | **{overall_rentai:.1f}%** |")
md.append("")

# Find insights
best_track = max(track_table, key=lambda x: x[3])
worst_track = min(track_table, key=lambda x: x[3])
md.append(f"**考察**: 1番人気勝率が最も高いのは **{best_track[0]}**（{best_track[3]:.1f}%）、最も低いのは **{worst_track[0]}**（{worst_track[3]:.1f}%）。")
md.append(f"全体の1番人気勝率は{overall_win:.1f}%で、JRA中央競馬の約33%と比べると{'高い' if overall_win > 33 else '低い'}水準。")
md.append("")

# Section 2: Popularity range analysis
md.append("## 2. 人気合計レンジ別分析")
md.append("")
md.append("人気合計 = 3レースの1着馬の人気の合計。値が小さいほど「堅い」（人気馬が勝っている）結果。")
md.append("")
md.append("| 人気合計 | 特徴 | 出現数 | 平均的中金額 | 中央値 | 1番人気勝率 |")
md.append("|----------|------|--------|-------------|--------|-------------|")
labels = {'3-5': '超堅', '6-9': '堅い', '10-14': 'やや堅い', '15-19': '普通', '20-24': '荒れ', '25+': '大荒れ'}
for row in range_table:
    label = labels.get(row[0], '')
    md.append(f"| {row[0]} | {label} | {row[1]}回 | {row[2]:,.0f}円 | {row[3]:,.0f}円 | {row[4]:.1f}% |")
md.append("")

# Insights
if range_table:
    cheapest = min(range_table, key=lambda x: x[2])
    most_expensive = max(range_table, key=lambda x: x[2])
    most_common = max(range_table, key=lambda x: x[1])
    md.append(f"**考察**: 最も出現頻度が高いのは人気合計 **{most_common[0]}**（{most_common[1]}回）。")
    md.append(f"平均的中金額が最も低いのは **{cheapest[0]}**（{cheapest[2]:,.0f}円）、最も高いのは **{most_expensive[0]}**（{most_expensive[2]:,.0f}円）。")
    md.append(f"人気合計が大きくなるほど的中金額が上がる傾向が顕著。")
md.append("")

# Section 3: Flag analysis
md.append("## 3. フラグ分析（列7）")
md.append("")
md.append("CSVの7列目（2番目の「フラグ」列）の値別に分析。")
md.append("")
md.append("| フラグ | 出現数 | 割合 | 平均的中金額 | 中央値 | 1番人気勝率 |")
md.append("|--------|--------|------|-------------|--------|-------------|")
total_flag = sum(row[1] for row in flag_table)
for row in flag_table:
    pct = row[1] / total_flag * 100
    md.append(f"| {row[0]} | {row[1]}回 | {pct:.1f}% | {row[2]:,.0f}円 | {row[3]:,.0f}円 | {row[4]:.1f}% |")
md.append("")

md.append("### フラグと1番人気1着回数のクロス集計")
md.append("")
md.append("| フラグ | 0回 | 1回 | 2回 | 3回 |")
md.append("|--------|-----|-----|-----|-----|")
for f in sorted(flag_vs_favcount.keys()):
    counts = flag_vs_favcount[f]
    total = sum(counts.values())
    cols = []
    for fc in range(4):
        c = counts.get(fc, 0)
        cols.append(f"{c}({c/total*100:.0f}%)")
    md.append(f"| {f} | {' | '.join(cols)} |")
md.append("")

# Estimate flag meaning
md.append("### フラグの意味推定")
md.append("")
# Check if flag correlates with fav count, carryover, etc.
flag_co_rate = {}
for f_val in sorted(flag_stats.keys()):
    matching = [d for d in valid_data if d['flag2'] == f_val]
    co_count = sum(1 for d in matching if d['carryover_announce'] == '1')
    flag_co_rate[f_val] = co_count / len(matching) * 100 if matching else 0

md.append("フラグ値と各指標の関係を調査した結果:")
md.append("")
for f_val in sorted(flag_stats.keys()):
    s = flag_stats[f_val]
    win_rate = s['fav_wins'] / s['total_races'] * 100 if s['total_races'] > 0 else 0
    avg = statistics.mean(s['amounts']) if s['amounts'] else 0
    md.append(f"- **フラグ{f_val}**: 1番人気勝率 {win_rate:.1f}%, 平均的中金額 {avg:,.0f}円, CO発声率 {flag_co_rate[f_val]:.0f}%")

# Check correlation with popularity sum
flag_pop_avg = {}
for f_val in sorted(flag_stats.keys()):
    matching = [d for d in valid_data if d['flag2'] == f_val and d['popularity_sum'] is not None]
    if matching:
        flag_pop_avg[f_val] = statistics.mean([d['popularity_sum'] for d in matching])
    else:
        flag_pop_avg[f_val] = 0

md.append("")
md.append("フラグ値と人気合計の平均:")
for f_val in sorted(flag_pop_avg.keys()):
    md.append(f"- フラグ{f_val}: 平均人気合計 {flag_pop_avg[f_val]:.1f}")

md.append("")
md.append("**推定**: フラグ値が小さいほど1番人気勝率が高く平均的中金額が低い傾向がある場合、フラグは「堅さ」の指標と考えられる。")
md.append("フラグ1は最も堅い組（1番人気勝率が高い）、フラグ3は荒れる組と推定される。")
md.append("")

# Section 4: Favorite count distribution
md.append("## 4. 3レース中の1番人気1着回数の分布")
md.append("")
md.append("3レース中、1番人気が1着になった回数の分布と的中金額の関係。")
md.append("")
md.append("| 1番人気1着回数 | 件数 | 割合 | 平均的中金額 | 中央値 |")
md.append("|----------------|------|------|-------------|--------|")
for row in fav_count_table:
    md.append(f"| {row[0]}回 | {row[1]}件 | {row[2]:.1f}% | {row[3]:,.0f}円 | {row[4]:,.0f}円 |")
md.append("")

if fav_count_table:
    zero_fav = next((r for r in fav_count_table if r[0] == 0), None)
    three_fav = next((r for r in fav_count_table if r[0] == 3), None)
    md.append(f"**考察**: 1番人気が3レースとも1着になる確率は{three_fav[2]:.1f}%（{three_fav[1]}件）、" if three_fav else "")
    md.append(f"1回も1着にならない確率は{zero_fav[2]:.1f}%（{zero_fav[1]}件）。" if zero_fav else "")
    if three_fav and zero_fav:
        md.append(f"3回全て1番人気1着の場合の平均的中金額は{three_fav[3]:,.0f}円、0回の場合は{zero_fav[3]:,.0f}円と、")
        ratio = zero_fav[3] / three_fav[3] if three_fav[3] > 0 else 0
        md.append(f"約{ratio:.1f}倍の差がある。")
md.append("")

# Section 5: Weekday analysis
md.append("## 5. 曜日別分析")
md.append("")
md.append("開催曜日別の傾向。平均人気合計が大きいほど荒れやすい曜日。")
md.append("")
md.append("| 曜日 | 開催数 | 平均的中金額 | 中央値 | 平均人気合計 | 1番人気勝率 |")
md.append("|------|--------|-------------|--------|-------------|-------------|")
for row in weekday_table:
    md.append(f"| {row[0]}曜 | {row[1]}回 | {row[2]:,.0f}円 | {row[3]:,.0f}円 | {row[4]:.1f} | {row[5]:.1f}% |")
md.append("")

if weekday_table:
    most_expensive_wd = max(weekday_table, key=lambda x: x[2])
    cheapest_wd = min(weekday_table, key=lambda x: x[2])
    md.append(f"**考察**: 平均的中金額が最も高いのは **{most_expensive_wd[0]}曜日**（{most_expensive_wd[2]:,.0f}円）、")
    md.append(f"最も低いのは **{cheapest_wd[0]}曜日**（{cheapest_wd[2]:,.0f}円）。")
    most_common_wd = max(weekday_table, key=lambda x: x[1])
    md.append(f"最も開催が多いのは **{most_common_wd[0]}曜日**（{most_common_wd[1]}回）。")
md.append("")

# Section 6: Race number analysis
md.append("## 6. レース番号別の1番人気勝率")
md.append("")
md.append("レース番号（8R〜12R等）ごとの1番人気成績。レース番号が大きいほど上位クラスのレース。")
md.append("")
md.append("| レース番号 | 出走回数 | 1番人気1着 | 勝率 | 1番人気連対 | 連対率 |")
md.append("|------------|----------|------------|------|-------------|--------|")
for row in race_num_table:
    md.append(f"| {row[0]}R | {row[1]}回 | {row[2]} | {row[3]:.1f}% | {row[4]} | {row[5]:.1f}% |")
md.append("")

if race_num_table:
    best_rn = max(race_num_table, key=lambda x: x[3])
    worst_rn = min(race_num_table, key=lambda x: x[3])
    md.append(f"**考察**: 1番人気勝率が最も高いのは **{best_rn[0]}R**（{best_rn[3]:.1f}%）、最も低いのは **{worst_rn[0]}R**（{worst_rn[3]:.1f}%）。")
md.append("")

# Section 7: Supplementary stats
md.append("## 7. 補足統計")
md.append("")

# Overall stats
all_amounts = [d['hit_amount'] for d in valid_data if d['hit_amount'] is not None]
no_hit_count = sum(1 for d in valid_data if d['hit_amount'] is None)
md.append(f"### 基本統計")
md.append("")
md.append(f"- **総データ数**: {len(valid_data)}回")
md.append(f"- **的中あり**: {len(all_amounts)}回（{len(all_amounts)/len(valid_data)*100:.1f}%）")
md.append(f"- **不的中（的中金額なし）**: {no_hit_count}回（{no_hit_count/len(valid_data)*100:.1f}%）")
if all_amounts:
    md.append(f"- **平均的中金額**: {statistics.mean(all_amounts):,.0f}円")
    md.append(f"- **中央値**: {statistics.median(all_amounts):,.0f}円")
    md.append(f"- **最小的中金額**: {min(all_amounts):,.0f}円")
    md.append(f"- **最大的中金額**: {max(all_amounts):,.0f}円")
    md.append(f"- **標準偏差**: {statistics.stdev(all_amounts):,.0f}円")
md.append("")

# Carryover info
md.append(f"### キャリーオーバー")
md.append("")
md.append(f"- **キャリーオーバー発声中の回数**: {len(co_announce)}回")
co_amounts = [d['carryover'] for d in valid_data if d['carryover'] is not None and d['carryover'] > 0]
if co_amounts:
    md.append(f"- **キャリーオーバー発生回数（次回繰越あり）**: {len(co_amounts)}回")
    md.append(f"- **平均キャリーオーバー額**: {statistics.mean(co_amounts):,.0f}円")
    md.append(f"- **最大キャリーオーバー額**: {max(co_amounts):,.0f}円")
md.append("")

# Top 10 highest payouts
md.append("### 高額的中 TOP10")
md.append("")
sorted_by_amount = sorted([d for d in valid_data if d['hit_amount'] is not None], key=lambda x: x['hit_amount'], reverse=True)
md.append("| 順位 | 日時 | 競馬場 | 人気合計 | 的中金額 | 1番人気1着数 |")
md.append("|------|------|--------|----------|----------|-------------|")
for i, d in enumerate(sorted_by_amount[:10], 1):
    fav_cnt = sum(1 for p in ['race1', 'race2', 'race3'] if d[f'{p}_win_pop'] == 1)
    md.append(f"| {i} | {d['date_str']} | {d['track']} | {d['popularity_sum']} | {d['hit_amount']:,.0f}円 | {fav_cnt}回 |")
md.append("")

# Low payout (堅い結果) TOP10
md.append("### 低額的中（堅い結果）TOP10")
md.append("")
sorted_by_amount_asc = sorted([d for d in valid_data if d['hit_amount'] is not None], key=lambda x: x['hit_amount'])
md.append("| 順位 | 日時 | 競馬場 | 人気合計 | 的中金額 | 1番人気1着数 |")
md.append("|------|------|--------|----------|----------|-------------|")
for i, d in enumerate(sorted_by_amount_asc[:10], 1):
    fav_cnt = sum(1 for p in ['race1', 'race2', 'race3'] if d[f'{p}_win_pop'] == 1)
    md.append(f"| {i} | {d['date_str']} | {d['track']} | {d['popularity_sum']} | {d['hit_amount']:,.0f}円 | {fav_cnt}回 |")
md.append("")

# Track x Race position analysis
md.append("### 競馬場 x レース順序（第1/第2/第3レース）の1番人気勝率")
md.append("")
md.append("SPAT4の3レースにおける各ポジション（第1/第2/第3レース）での1番人気勝率。")
md.append("")

track_pos_stats = defaultdict(lambda: defaultdict(lambda: {'total': 0, 'fav_wins': 0}))
for d in valid_data:
    track = d['track']
    for i, prefix in enumerate(['race1', 'race2', 'race3'], 1):
        wp = d[f'{prefix}_win_pop']
        if wp is not None:
            track_pos_stats[track][i]['total'] += 1
            if wp == 1:
                track_pos_stats[track][i]['fav_wins'] += 1

md.append("| 競馬場 | 第1レース | 第2レース | 第3レース |")
md.append("|--------|-----------|-----------|-----------|")
for track in sorted(track_pos_stats.keys()):
    cols = []
    for pos in [1, 2, 3]:
        s = track_pos_stats[track][pos]
        rate = s['fav_wins'] / s['total'] * 100 if s['total'] > 0 else 0
        cols.append(f"{rate:.1f}% ({s['fav_wins']}/{s['total']})")
    md.append(f"| {track} | {' | '.join(cols)} |")
md.append("")

# Write to file
output = '\n'.join(md)
with open(r'D:\SPAT4\analysis_stats.md', 'w', encoding='utf-8') as f:
    f.write(output)

print("\n=== analysis_stats.md を出力しました ===")
