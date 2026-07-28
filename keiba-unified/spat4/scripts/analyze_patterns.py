import csv
import re
from collections import Counter, defaultdict

# Read CSV
rows = []
with open(r'D:\SPAT4\spat4.csv', encoding='utf-8') as f:
    reader = csv.reader(f)
    header = next(reader)
    for row in reader:
        if not row[0].strip():  # skip empty rows
            continue
        rows.append(row)

print(f"Total rows (including empty): {len(rows)}")

# Parse CO-only rows (no winning amount but has CO amount)
co_only_rows = []
for row in rows:
    no = row[0].strip()
    if not no:
        continue
    amount_str = row[18].strip().replace('"', '').replace(',', '')
    co_str = row[19].strip().replace('"', '').replace(',', '')
    if not amount_str and co_str:
        try:
            co_only_rows.append({
                'no': no,
                'co_amount': int(co_str),
                'pop_total': int(row[5].strip()) if row[5].strip() else 0,
            })
        except ValueError:
            pass

# Parse data
data = []
for row in rows:
    no = row[0].strip()
    if not no:
        continue

    # Parse 的中金額 (column 18, index 18)
    amount_str = row[18].strip().replace('"', '').replace(',', '')
    if not amount_str:
        continue  # skip rows without winning amount

    try:
        amount = int(amount_str)
    except ValueError:
        print(f"Could not parse amount: '{row[18]}' in row No={no}")
        continue

    # Parse 人気合計 (column 5)
    try:
        pop_total = int(row[5].strip())
    except ValueError:
        continue

    # Parse flag (column 1)
    flag1 = row[1].strip()

    # Parse 競馬場 (column 3)
    track = row[3].strip()

    # Parse 開催日 (column 4)
    kaisai = row[4].strip()

    # Parse キャリーオーバー発声中 (column 16)
    co_firing = row[16].strip()

    # Parse 的中口数 (column 17)
    tickets_str = row[17].strip().replace(',', '')
    tickets = int(tickets_str) if tickets_str else 0

    # Parse キャリーオーバー (column 19)
    co_str = row[19].strip().replace('"', '').replace(',', '')
    co_amount = int(co_str) if co_str else 0

    # Parse 3 races: columns 7-15
    # Race1: col 7(race), 8(1着人気), 9(2着人気)
    # Race2: col 10(race), 11(1着人気), 12(2着人気)
    # Race3: col 13(race), 14(1着人気), 15(2着人気)
    try:
        r1_win = int(row[8].strip())
        r1_place = int(row[9].strip())
        r2_win = int(row[11].strip())
        r2_place = int(row[12].strip())
        r3_win = int(row[14].strip())
        r3_place = int(row[15].strip())
    except (ValueError, IndexError):
        print(f"Could not parse race data in row No={no}")
        continue

    # フラグ column 6
    flag2 = row[6].strip()
    flag2_val = int(flag2) if flag2 else 0

    data.append({
        'no': no,
        'flag1': flag1,
        'track': track,
        'kaisai': kaisai,
        'pop_total': pop_total,
        'flag2': flag2_val,
        'r1_win': r1_win, 'r1_place': r1_place,
        'r2_win': r2_win, 'r2_place': r2_place,
        'r3_win': r3_win, 'r3_place': r3_place,
        'co_firing': co_firing == '1',
        'tickets': tickets,
        'amount': amount,
        'co_amount': co_amount,
    })

print(f"Parsed data rows: {len(data)}")

# ============================================================
# Analysis 1: 的中金額の分布
# ============================================================
amounts = [d['amount'] for d in data]
total = len(amounts)

cat_low = [a for a in amounts if a <= 100000]
cat_mid = [a for a in amounts if 100000 < a <= 1000000]
cat_high = [a for a in amounts if 1000000 < a <= 10000000]
cat_super = [a for a in amounts if a > 10000000]

avg_amount = sum(amounts) / total if total else 0
median_amount = sorted(amounts)[total // 2] if total else 0

# Distribution in more detail
brackets = [
    (0, 10000, "1万円以下"),
    (10001, 50000, "1万-5万"),
    (50001, 100000, "5万-10万"),
    (100001, 300000, "10万-30万"),
    (300001, 500000, "30万-50万"),
    (500001, 1000000, "50万-100万"),
    (1000001, 3000000, "100万-300万"),
    (3000001, 5000000, "300万-500万"),
    (5000001, 10000000, "500万-1000万"),
    (10000001, 20000000, "1000万-2000万"),
    (20000001, 50000000, "2000万-5000万"),
    (50000001, 100000000, "5000万以上"),
]

bracket_counts = []
for lo, hi, label in brackets:
    cnt = sum(1 for a in amounts if lo <= a <= hi)
    bracket_counts.append((label, cnt, cnt/total*100 if total else 0))

# ============================================================
# Analysis 2: 低配当パターン (10万円以下)
# ============================================================
low_data = [d for d in data if d['amount'] <= 100000]
low_pop_avg = sum(d['pop_total'] for d in low_data) / len(low_data) if low_data else 0

# Count 1着人気 patterns for low
low_win_patterns = Counter()
for d in low_data:
    pattern = (d['r1_win'], d['r2_win'], d['r3_win'])
    low_win_patterns[pattern] += 1

# Count 2着人気 patterns for low
low_place_patterns = Counter()
for d in low_data:
    pattern = (d['r1_place'], d['r2_place'], d['r3_place'])
    low_place_patterns[pattern] += 1

# Most common 1着 popularity values in low payout
low_r1_win_count = Counter(d['r1_win'] for d in low_data)
low_r2_win_count = Counter(d['r2_win'] for d in low_data)
low_r3_win_count = Counter(d['r3_win'] for d in low_data)

# ============================================================
# Analysis 3: 高配当パターン (100万円以上)
# ============================================================
high_data = [d for d in data if d['amount'] >= 1000000]
high_pop_avg = sum(d['pop_total'] for d in high_data) / len(high_data) if high_data else 0

super_high_data = [d for d in data if d['amount'] >= 10000000]
super_high_pop_avg = sum(d['pop_total'] for d in super_high_data) / len(super_high_data) if super_high_data else 0

# Most common patterns in high payout
high_win_patterns = Counter()
for d in high_data:
    pattern = (d['r1_win'], d['r2_win'], d['r3_win'])
    high_win_patterns[pattern] += 1

# ============================================================
# Analysis 4: キャリーオーバー分析
# ============================================================
co_on = [d for d in data if d['co_firing']]
co_off = [d for d in data if not d['co_firing']]

co_on_avg = sum(d['amount'] for d in co_on) / len(co_on) if co_on else 0
co_off_avg = sum(d['amount'] for d in co_off) / len(co_off) if co_off else 0

co_on_median = sorted(d['amount'] for d in co_on)[len(co_on)//2] if co_on else 0
co_off_median = sorted(d['amount'] for d in co_off)[len(co_off)//2] if co_off else 0

# キャリーオーバー額の分析 (rows where co_amount > 0, including non-winning rows)
co_rows = [d for d in data if d['co_amount'] > 0]
# Also include CO-only rows (non-winning rows with CO data)
co_amounts_list = [d['co_amount'] for d in co_rows] + [d['co_amount'] for d in co_only_rows]
co_avg_amount = sum(co_amounts_list) / len(co_amounts_list) if co_amounts_list else 0

# ============================================================
# Analysis 5: 1番人気の組み合わせパターン
# ============================================================
def classify_win(pop):
    if pop == 1:
        return "1番人気"
    elif pop == 2:
        return "2番人気"
    elif pop == 3:
        return "3番人気"
    else:
        return f"{pop}番人気以下" if pop <= 5 else "6番人気以下"

def classify_win_group(pop):
    if pop == 1:
        return "1人気"
    elif pop <= 3:
        return "2-3人気"
    else:
        return "4人気以下"

# Count how many 1番人気 wins in 3 races
fav_count_dist = Counter()
for d in data:
    fav_count = sum(1 for w in [d['r1_win'], d['r2_win'], d['r3_win']] if w == 1)
    fav_count_dist[fav_count] += 1

fav_count_amounts = defaultdict(list)
for d in data:
    fav_count = sum(1 for w in [d['r1_win'], d['r2_win'], d['r3_win']] if w == 1)
    fav_count_amounts[fav_count].append(d['amount'])

# Grouped pattern analysis
pattern_groups = defaultdict(list)
for d in data:
    wins = sorted([d['r1_win'], d['r2_win'], d['r3_win']])
    # Classify pattern
    fav1_count = wins.count(1)
    if fav1_count == 3:
        pat = "1人気-1人気-1人気"
    elif fav1_count == 2:
        pat = "1人気-1人気-その他"
    elif fav1_count == 1:
        # Check if the other two are within top 3
        others = [w for w in wins if w != 1]
        if all(w <= 3 for w in others):
            pat = "1人気-上位人気-上位人気"
        else:
            pat = "1人気-混合"
    else:
        if all(w <= 3 for w in wins):
            pat = "全2-3番人気"
        else:
            pat = "全て4番人気以下含む"
    pattern_groups[pat].append(d['amount'])

# ============================================================
# Analysis 6: 開催日目別分析
# ============================================================
day_pattern = re.compile(r'第\d+回(\d+)日目')
day_data = defaultdict(list)
for d in data:
    m = day_pattern.search(d['kaisai'])
    if m:
        day_num = int(m.group(1))
        day_data[day_num].append(d)

# ============================================================
# Analysis 7: 2着人気の傾向
# ============================================================
# All 2着 popularity values across all 3 races
all_place_pops = []
for d in data:
    all_place_pops.extend([d['r1_place'], d['r2_place'], d['r3_place']])

place_counter = Counter(all_place_pops)
total_place = len(all_place_pops)

# 2着人気 vs 配当の関係
place_avg_by_pop = defaultdict(list)
for d in data:
    for p in [d['r1_place'], d['r2_place'], d['r3_place']]:
        place_avg_by_pop[p].append(d['amount'])

# 2着に1番人気が来るレース数と配当
place_fav1_count = Counter()
for d in data:
    cnt = sum(1 for p in [d['r1_place'], d['r2_place'], d['r3_place']] if p == 1)
    place_fav1_count[cnt] += 1

place_fav1_amounts = defaultdict(list)
for d in data:
    cnt = sum(1 for p in [d['r1_place'], d['r2_place'], d['r3_place']] if p == 1)
    place_fav1_amounts[cnt].append(d['amount'])

# ============================================================
# Analysis 8: 連続堅い/荒れレースの傾向
# ============================================================
# Define "堅い" (solid) as pop_total <= 14, "荒れ" (upset) as pop_total >= 22
# Sort by No for time series
sorted_data = sorted(data, key=lambda d: int(d['no']))

streaks_solid = []  # consecutive solid days
streaks_upset = []  # consecutive upset days
current_type = None
current_streak = 0

for d in sorted_data:
    if d['pop_total'] <= 14:
        t = 'solid'
    elif d['pop_total'] >= 22:
        t = 'upset'
    else:
        t = 'mid'

    if t == current_type:
        current_streak += 1
    else:
        if current_type == 'solid' and current_streak >= 1:
            streaks_solid.append(current_streak)
        elif current_type == 'upset' and current_streak >= 1:
            streaks_upset.append(current_streak)
        current_type = t
        current_streak = 1

if current_type == 'solid':
    streaks_solid.append(current_streak)
elif current_type == 'upset':
    streaks_upset.append(current_streak)

# Transition analysis
transitions = Counter()
for i in range(len(sorted_data) - 1):
    prev_pop = sorted_data[i]['pop_total']
    next_pop = sorted_data[i+1]['pop_total']

    if prev_pop <= 14:
        prev_t = '堅い'
    elif prev_pop >= 22:
        prev_t = '荒れ'
    else:
        prev_t = '中間'

    if next_pop <= 14:
        next_t = '堅い'
    elif next_pop >= 22:
        next_t = '荒れ'
    else:
        next_t = '中間'

    transitions[(prev_t, next_t)] += 1

# ============================================================
# Generate Markdown Report
# ============================================================
lines = []
lines.append("# SPAT4 トリプル馬単 的中パターン分析")
lines.append("")
lines.append(f"分析対象データ: {len(data)}件")
lines.append("")

# --- 1. 的中金額の分布 ---
lines.append("## 1. 的中金額の分布")
lines.append("")
lines.append(f"- **平均金額**: {avg_amount:,.0f}円")
lines.append(f"- **中央値**: {median_amount:,}円")
lines.append(f"- **最低金額**: {min(amounts):,}円")
lines.append(f"- **最高金額**: {max(amounts):,}円")
lines.append("")

lines.append("### 4段階分類")
lines.append("")
lines.append("| カテゴリ | 件数 | 割合 | 平均金額 |")
lines.append("|---|---|---|---|")

cats = [
    ("低配当(10万以下)", cat_low),
    ("中配当(10万-100万)", cat_mid),
    ("高配当(100万-1000万)", cat_high),
    ("超高配当(1000万以上)", cat_super),
]
for label, cat in cats:
    cnt = len(cat)
    pct = cnt / total * 100
    avg = sum(cat) / cnt if cnt else 0
    lines.append(f"| {label} | {cnt}件 | {pct:.1f}% | {avg:,.0f}円 |")

lines.append("")
lines.append("### 詳細金額帯別分布")
lines.append("")
lines.append("| 金額帯 | 件数 | 割合 | 累積割合 |")
lines.append("|---|---|---|---|")
cumulative = 0
for label, cnt, pct in bracket_counts:
    cumulative += pct
    lines.append(f"| {label} | {cnt}件 | {pct:.1f}% | {cumulative:.1f}% |")

# --- 2. 低配当パターン ---
lines.append("")
lines.append("## 2. 低配当パターン (10万円以下)")
lines.append("")
lines.append(f"- **該当件数**: {len(low_data)}件 ({len(low_data)/total*100:.1f}%)")
lines.append(f"- **人気合計の平均**: {low_pop_avg:.1f}")
lines.append(f"- **平均金額**: {sum(d['amount'] for d in low_data)/len(low_data):,.0f}円" if low_data else "")
lines.append("")

lines.append("### 各レース1着の人気分布 (低配当時)")
lines.append("")
lines.append("| 人気 | レース1 | レース2 | レース3 |")
lines.append("|---|---|---|---|")
for pop in range(1, 8):
    r1 = low_r1_win_count.get(pop, 0)
    r2 = low_r2_win_count.get(pop, 0)
    r3 = low_r3_win_count.get(pop, 0)
    r1p = r1/len(low_data)*100 if low_data else 0
    r2p = r2/len(low_data)*100 if low_data else 0
    r3p = r3/len(low_data)*100 if low_data else 0
    lines.append(f"| {pop}番人気 | {r1}回({r1p:.1f}%) | {r2}回({r2p:.1f}%) | {r3}回({r3p:.1f}%) |")

lines.append("")
lines.append("### 低配当時の1着人気組み合わせ上位10パターン")
lines.append("")
lines.append("| 順位 | パターン (R1-R2-R3) | 出現回数 | 平均金額 |")
lines.append("|---|---|---|---|")
# Compute avg amount per pattern for low data
low_pattern_amounts = defaultdict(list)
for d in low_data:
    pattern = (d['r1_win'], d['r2_win'], d['r3_win'])
    low_pattern_amounts[pattern].append(d['amount'])

for rank, (pat, cnt) in enumerate(low_win_patterns.most_common(10), 1):
    avg_pat = sum(low_pattern_amounts[pat]) / len(low_pattern_amounts[pat])
    lines.append(f"| {rank} | {pat[0]}人気-{pat[1]}人気-{pat[2]}人気 | {cnt}回 | {avg_pat:,.0f}円 |")

# --- 3. 高配当パターン ---
lines.append("")
lines.append("## 3. 高配当パターン (100万円以上)")
lines.append("")
lines.append(f"- **該当件数**: {len(high_data)}件 ({len(high_data)/total*100:.1f}%)")
lines.append(f"- **人気合計の平均**: {high_pop_avg:.1f}")
lines.append(f"- **平均金額**: {sum(d['amount'] for d in high_data)/len(high_data):,.0f}円" if high_data else "")
lines.append("")

lines.append(f"### 超高配当 (1000万円以上): {len(super_high_data)}件")
lines.append(f"- **人気合計の平均**: {super_high_pop_avg:.1f}")
lines.append("")

lines.append("### 高配当時の1着人気組み合わせ上位10パターン")
lines.append("")
lines.append("| 順位 | パターン (R1-R2-R3) | 出現回数 | 平均金額 |")
lines.append("|---|---|---|---|")
high_pattern_amounts = defaultdict(list)
for d in high_data:
    pattern = (d['r1_win'], d['r2_win'], d['r3_win'])
    high_pattern_amounts[pattern].append(d['amount'])

for rank, (pat, cnt) in enumerate(high_win_patterns.most_common(10), 1):
    avg_pat = sum(high_pattern_amounts[pat]) / len(high_pattern_amounts[pat])
    lines.append(f"| {rank} | {pat[0]}人気-{pat[1]}人気-{pat[2]}人気 | {cnt}回 | {avg_pat:,.0f}円 |")

lines.append("")
lines.append("### 高配当vs低配当の人気合計比較")
lines.append("")
lines.append("| 項目 | 低配当(10万以下) | 中配当(10万-100万) | 高配当(100万以上) | 超高配当(1000万以上) |")
lines.append("|---|---|---|---|---|")
mid_data = [d for d in data if 100000 < d['amount'] <= 1000000]
mid_pop_avg = sum(d['pop_total'] for d in mid_data) / len(mid_data) if mid_data else 0
lines.append(f"| 人気合計平均 | {low_pop_avg:.1f} | {mid_pop_avg:.1f} | {high_pop_avg:.1f} | {super_high_pop_avg:.1f} |")
lines.append(f"| 件数 | {len(low_data)} | {len(mid_data)} | {len(high_data)} | {len(super_high_data)} |")

# --- 4. キャリーオーバー分析 ---
lines.append("")
lines.append("## 4. キャリーオーバー分析")
lines.append("")
lines.append("### キャリーオーバー発声中の影響")
lines.append("")
lines.append("| 項目 | CO発声中 | CO発声なし |")
lines.append("|---|---|---|")
lines.append(f"| 件数 | {len(co_on)}件 | {len(co_off)}件 |")
lines.append(f"| 平均金額 | {co_on_avg:,.0f}円 | {co_off_avg:,.0f}円 |")
lines.append(f"| 中央値 | {co_on_median:,}円 | {co_off_median:,}円 |")

# CO on: amount category distribution
co_on_low = sum(1 for d in co_on if d['amount'] <= 100000)
co_on_high = sum(1 for d in co_on if d['amount'] >= 1000000)
co_off_low = sum(1 for d in co_off if d['amount'] <= 100000)
co_off_high = sum(1 for d in co_off if d['amount'] >= 1000000)
lines.append(f"| 低配当(10万以下)率 | {co_on_low/len(co_on)*100:.1f}% | {co_off_low/len(co_off)*100:.1f}% |")
lines.append(f"| 高配当(100万以上)率 | {co_on_high/len(co_on)*100:.1f}% | {co_off_high/len(co_off)*100:.1f}% |")

lines.append("")
lines.append("### キャリーオーバー額の分析")
lines.append("")
lines.append(f"※ CO額は不的中時に繰り越される金額。不的中行({len(co_only_rows)}件)と的中行のCOデータを合算して分析。")
lines.append("")
if co_amounts_list:
    lines.append(f"- **CO発生件数**: {len(co_amounts_list)}件 (的中行:{len(co_rows)}件、不的中行:{len(co_only_rows)}件)")
    lines.append(f"- **CO平均額**: {co_avg_amount:,.0f}円")
    lines.append(f"- **CO中央値**: {sorted(co_amounts_list)[len(co_amounts_list)//2]:,}円")
    lines.append(f"- **CO最大額**: {max(co_amounts_list):,}円")
    lines.append(f"- **CO最小額**: {min(co_amounts_list):,}円")
else:
    lines.append("キャリーオーバーデータなし")

# CO amount brackets
co_brackets = [
    (0, 5000000, "500万以下"),
    (5000001, 10000000, "500万-1000万"),
    (10000001, 15000000, "1000万-1500万"),
    (15000001, 50000000, "1500万-5000万"),
    (50000001, 100000000, "5000万以上"),
]
if co_amounts_list:
    lines.append("")
    lines.append("| CO額帯 | 件数 | 割合 |")
    lines.append("|---|---|---|")
    for lo, hi, label in co_brackets:
        cnt = sum(1 for a in co_amounts_list if lo <= a <= hi)
        pct = cnt / len(co_amounts_list) * 100
        lines.append(f"| {label} | {cnt}件 | {pct:.1f}% |")

# --- 5. 1番人気の組み合わせパターン ---
lines.append("")
lines.append("## 5. 1番人気の組み合わせパターン")
lines.append("")
lines.append("### 3レース中の1番人気勝利数別")
lines.append("")
lines.append("| 1番人気勝利数 | 件数 | 割合 | 平均金額 | 中央値 |")
lines.append("|---|---|---|---|---|")
for cnt in sorted(fav_count_dist.keys()):
    n = fav_count_dist[cnt]
    pct = n / total * 100
    amts = fav_count_amounts[cnt]
    avg = sum(amts) / len(amts) if amts else 0
    med = sorted(amts)[len(amts)//2] if amts else 0
    lines.append(f"| {cnt}レース | {n}件 | {pct:.1f}% | {avg:,.0f}円 | {med:,}円 |")

lines.append("")
lines.append("### パターングループ別分析")
lines.append("")
lines.append("| パターン | 件数 | 割合 | 平均金額 | 中央値 |")
lines.append("|---|---|---|---|---|")
for pat in ["1人気-1人気-1人気", "1人気-1人気-その他", "1人気-上位人気-上位人気", "1人気-混合", "全2-3番人気", "全て4番人気以下含む"]:
    amts = pattern_groups.get(pat, [])
    n = len(amts)
    if n == 0:
        continue
    pct = n / total * 100
    avg = sum(amts) / n
    med = sorted(amts)[n//2]
    lines.append(f"| {pat} | {n}件 | {pct:.1f}% | {avg:,.0f}円 | {med:,}円 |")

# --- 6. 開催日目別分析 ---
lines.append("")
lines.append("## 6. 開催日目別分析")
lines.append("")
lines.append("| 開催日目 | 件数 | 平均金額 | 中央値 | 平均人気合計 | 高配当(100万以上)率 |")
lines.append("|---|---|---|---|---|---|")
for day_num in sorted(day_data.keys()):
    dd = day_data[day_num]
    n = len(dd)
    amts = [d['amount'] for d in dd]
    avg = sum(amts) / n
    med = sorted(amts)[n//2]
    pop_avg = sum(d['pop_total'] for d in dd) / n
    high_pct = sum(1 for a in amts if a >= 1000000) / n * 100
    lines.append(f"| {day_num}日目 | {n}件 | {avg:,.0f}円 | {med:,}円 | {pop_avg:.1f} | {high_pct:.1f}% |")

# --- 7. 2着人気の傾向 ---
lines.append("")
lines.append("## 7. 2着人気の傾向")
lines.append("")
lines.append("### 2着に来た馬の人気分布 (全レース合計)")
lines.append("")
lines.append("| 人気 | 出現回数 | 割合 |")
lines.append("|---|---|---|")
for pop in sorted(place_counter.keys()):
    cnt = place_counter[pop]
    pct = cnt / total_place * 100
    lines.append(f"| {pop}番人気 | {cnt}回 | {pct:.1f}% |")

lines.append("")
lines.append("### 3レース中の2着1番人気数別の配当")
lines.append("")
lines.append("| 2着1番人気数 | 件数 | 割合 | 平均金額 | 中央値 |")
lines.append("|---|---|---|---|---|")
for cnt in sorted(place_fav1_count.keys()):
    n = place_fav1_count[cnt]
    pct = n / total * 100
    amts = place_fav1_amounts[cnt]
    avg = sum(amts) / len(amts) if amts else 0
    med = sorted(amts)[len(amts)//2] if amts else 0
    lines.append(f"| {cnt}レース | {n}件 | {pct:.1f}% | {avg:,.0f}円 | {med:,}円 |")

# 2着の人気合計と配当の関係
lines.append("")
lines.append("### 2着人気合計と配当の関係")
lines.append("")
place_total_amounts = defaultdict(list)
for d in data:
    pt = d['r1_place'] + d['r2_place'] + d['r3_place']
    place_total_amounts[pt].append(d['amount'])

# Group into ranges
place_total_groups = [
    (3, 6, "3-6(堅い)"),
    (7, 10, "7-10"),
    (11, 15, "11-15"),
    (16, 20, "16-20(荒れ)"),
    (21, 50, "21以上(大荒れ)"),
]
lines.append("| 2着人気合計 | 件数 | 割合 | 平均金額 |")
lines.append("|---|---|---|---|")
for lo, hi, label in place_total_groups:
    amts = []
    for pt, a_list in place_total_amounts.items():
        if lo <= pt <= hi:
            amts.extend(a_list)
    n = len(amts)
    pct = n / total * 100 if total else 0
    avg = sum(amts) / n if n else 0
    lines.append(f"| {label} | {n}件 | {pct:.1f}% | {avg:,.0f}円 |")

# --- 8. 連続堅い/荒れレースの傾向 ---
lines.append("")
lines.append("## 8. 連続堅いレース・荒れレースの傾向")
lines.append("")
lines.append("定義: 堅い = 人気合計14以下、荒れ = 人気合計22以上、中間 = 15-21")
lines.append("")

solid_count = sum(1 for d in data if d['pop_total'] <= 14)
mid_count2 = sum(1 for d in data if 15 <= d['pop_total'] <= 21)
upset_count = sum(1 for d in data if d['pop_total'] >= 22)
lines.append(f"- 堅い: {solid_count}件 ({solid_count/total*100:.1f}%)")
lines.append(f"- 中間: {mid_count2}件 ({mid_count2/total*100:.1f}%)")
lines.append(f"- 荒れ: {upset_count}件 ({upset_count/total*100:.1f}%)")
lines.append("")

lines.append("### 連続ストリーク分析")
lines.append("")
if streaks_solid:
    lines.append(f"- **堅いストリーク**: 最大{max(streaks_solid)}連続、平均{sum(streaks_solid)/len(streaks_solid):.1f}連続")
else:
    lines.append("- **堅いストリーク**: なし")
if streaks_upset:
    lines.append(f"- **荒れストリーク**: 最大{max(streaks_upset)}連続、平均{sum(streaks_upset)/len(streaks_upset):.1f}連続")
else:
    lines.append("- **荒れストリーク**: なし")

lines.append("")
lines.append("### 遷移確率マトリクス")
lines.append("")
lines.append("| 前回 \\ 次回 | 堅い | 中間 | 荒れ |")
lines.append("|---|---|---|---|")
for prev in ['堅い', '中間', '荒れ']:
    total_from = sum(transitions[(prev, n)] for n in ['堅い', '中間', '荒れ'])
    if total_from == 0:
        lines.append(f"| {prev} | - | - | - |")
    else:
        vals = []
        for nxt in ['堅い', '中間', '荒れ']:
            cnt = transitions[(prev, nxt)]
            pct = cnt / total_from * 100
            vals.append(f"{cnt}回({pct:.1f}%)")
        lines.append(f"| {prev} | {vals[0]} | {vals[1]} | {vals[2]} |")

# --- 戦略的示唆 ---
lines.append("")
lines.append("## 9. 戦略的示唆")
lines.append("")

# Calculate key insights
lines.append("### 狙い目パターン")
lines.append("")

# Find the most profitable pattern group
best_pattern = max(pattern_groups.items(), key=lambda x: sum(x[1])/len(x[1]) if x[1] else 0)
lines.append(f"1. **1番人気が3レース中2レース以上で勝利する確率**: {(fav_count_dist.get(2,0)+fav_count_dist.get(3,0))/total*100:.1f}% -- この場合の中央値は比較的低く的中しやすい")
lines.append("")

# Low payout strategy
lines.append(f"2. **低配当(10万以下)を狙う場合**: 人気合計{low_pop_avg:.0f}以下を目安に、1番人気が2-3レースで勝つパターンを狙う。3レースとも1-3番人気なら的中率が高い")
lines.append("")

# CO strategy
if co_on:
    lines.append(f"3. **キャリーオーバー時**: CO発声中は平均{co_on_avg:,.0f}円 vs 非CO時{co_off_avg:,.0f}円。CO時は{'高配当が出やすい' if co_on_avg > co_off_avg else '配当が抑えめになる'}傾向")
    lines.append("")

# Day analysis
if day_data:
    max_day = max(day_data.items(), key=lambda x: sum(d['amount'] for d in x[1])/len(x[1]))
    min_day = min(day_data.items(), key=lambda x: sum(d['amount'] for d in x[1])/len(x[1]))
    lines.append(f"4. **開催日目**: {max_day[0]}日目が最も平均配当が高く(荒れやすい)、{min_day[0]}日目が最も堅い傾向")
    lines.append("")

# 2着 insight
fav1_2nd_pct = place_counter.get(1, 0) / total_place * 100
lines.append(f"5. **2着の傾向**: 1番人気が2着に来る割合は{fav1_2nd_pct:.1f}%。2着の予測は配当に大きく影響するため、2着に中穴馬が来るパターンを意識")
lines.append("")

# Transition insight
lines.append("6. **連続傾向**: ", )
total_from_solid = sum(transitions[('堅い', n)] for n in ['堅い', '中間', '荒れ'])
if total_from_solid:
    solid_to_solid = transitions[('堅い', '堅い')] / total_from_solid * 100
    lines[-1] += f"堅いレースの次も堅い確率は{solid_to_solid:.1f}%。"
total_from_upset = sum(transitions[('荒れ', n)] for n in ['堅い', '中間', '荒れ'])
if total_from_upset:
    upset_to_upset = transitions[('荒れ', '荒れ')] / total_from_upset * 100
    lines[-1] += f"荒れの次も荒れる確率は{upset_to_upset:.1f}%。"
lines[-1] += "前回の結果を参考に資金配分を調整する戦略が有効"
lines.append("")

# Final summary
lines.append("### 推奨戦略まとめ")
lines.append("")
lines.append("| 戦略 | ターゲット | ポイント |")
lines.append("|---|---|---|")
lines.append("| 堅実狙い | 人気合計14以下、1番人気2勝以上 | 的中率重視。100口程度で回収 |")
lines.append("| 中穴狙い | 人気合計15-21、1番人気1勝+中穴混合 | コスパ重視。2着の穴馬がカギ |")
lines.append("| 大穴狙い | 人気合計22以上、CO発声中 | 高額配当狙い。資金少量で大きなリターン |")
lines.append("| CO活用 | キャリーオーバー発生時 | CO額を確認し、投資額を調整 |")

output = "\n".join(lines)

with open(r'D:\SPAT4\analysis_patterns.md', 'w', encoding='utf-8') as f:
    f.write(output)

print("Analysis complete. Output written to D:\\SPAT4\\analysis_patterns.md")
print(f"Total records analyzed: {len(data)}")
