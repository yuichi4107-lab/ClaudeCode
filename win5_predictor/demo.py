"""Win5 Predictor デモ

実データ・学習済みモデルなしで、システムの最終アウトプットを再現する。
2026-02-15 (日曜) の架空Win5予想を生成。
"""

import io
import sys
from pathlib import Path

# Windows cp932 対策: stdout を UTF-8 に差し替え
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent / "src"))

import json
import random
from datetime import date

import numpy as np
import pandas as pd
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from config.settings import WIN5_BET_UNIT
from optimizer.expected_value import ExpectedValueCalculator
from optimizer.win5_combiner import Win5Combiner, Win5Selection

console = Console(width=90, force_terminal=True)

# ──────────────────────────────────────────────────
# デモ用の架空データ
# ──────────────────────────────────────────────────
TARGET_DATE = date(2026, 2, 15)

DEMO_RACES = [
    {
        "race_id": "202605020911",
        "venue": "阪神",
        "race_number": 9,
        "race_name": "4歳上2勝クラス",
        "surface": "芝",
        "distance": 1600,
        "condition": "良",
        "entries": [
            {"number": 1,  "name": "サンライズフレア",   "jockey": "川田将雅",   "odds": 12.3, "prob": 0.082},
            {"number": 2,  "name": "メイショウカゲロウ", "jockey": "松山弘平",   "odds": 8.5,  "prob": 0.105},
            {"number": 3,  "name": "ダノンシュネル",     "jockey": "C.ルメール", "odds": 2.1,  "prob": 0.318},
            {"number": 4,  "name": "ウインマーベラス",   "jockey": "武豊",       "odds": 5.4,  "prob": 0.158},
            {"number": 5,  "name": "コスモアステリア",   "jockey": "横山武史",   "odds": 15.8, "prob": 0.061},
            {"number": 6,  "name": "フジノハルカゼ",     "jockey": "岩田望来",   "odds": 23.1, "prob": 0.042},
            {"number": 7,  "name": "マイネルグロワール", "jockey": "坂井瑠星",   "odds": 6.8,  "prob": 0.128},
            {"number": 8,  "name": "ロードスターライト", "jockey": "戸崎圭太",   "odds": 42.0, "prob": 0.024},
            {"number": 9,  "name": "グランドスラマー",   "jockey": "M.デムーロ", "odds": 18.5, "prob": 0.051},
            {"number": 10, "name": "アドマイヤルプス",   "jockey": "浜中俊",     "odds": 34.7, "prob": 0.031},
        ],
    },
    {
        "race_id": "202605021011",
        "venue": "東京",
        "race_number": 10,
        "race_name": "白梅賞",
        "surface": "芝",
        "distance": 2000,
        "condition": "良",
        "entries": [
            {"number": 1,  "name": "レッドオルガノ",   "jockey": "C.ルメール",  "odds": 1.8,  "prob": 0.362},
            {"number": 2,  "name": "シャフリヤール",   "jockey": "川田将雅",    "odds": 4.2,  "prob": 0.189},
            {"number": 3,  "name": "ドゥラエレーデ",   "jockey": "横山武史",    "odds": 7.1,  "prob": 0.121},
            {"number": 4,  "name": "サトノグランデ",   "jockey": "戸崎圭太",    "odds": 9.8,  "prob": 0.088},
            {"number": 5,  "name": "メイショウドウサン", "jockey": "松山弘平",  "odds": 15.2, "prob": 0.058},
            {"number": 6,  "name": "テーオーロイヤル", "jockey": "武豊",        "odds": 11.4, "prob": 0.074},
            {"number": 7,  "name": "ラストドリーム",   "jockey": "岩田望来",    "odds": 22.6, "prob": 0.039},
            {"number": 8,  "name": "ゴールドアクター", "jockey": "M.デムーロ",  "odds": 38.5, "prob": 0.023},
            {"number": 9,  "name": "アドマイヤビルゴ", "jockey": "坂井瑠星",   "odds": 28.0, "prob": 0.031},
            {"number": 10, "name": "フォルテピアノ",   "jockey": "浜中俊",      "odds": 55.0, "prob": 0.015},
        ],
    },
    {
        "race_id": "202605020910",
        "venue": "阪神",
        "race_number": 10,
        "race_name": "洛陽ステークス (L)",
        "surface": "芝",
        "distance": 1400,
        "condition": "良",
        "entries": [
            {"number": 1,  "name": "ナムラクレア",     "jockey": "浜中俊",     "odds": 3.8,  "prob": 0.215},
            {"number": 2,  "name": "アグリ",           "jockey": "川田将雅",   "odds": 2.5,  "prob": 0.278},
            {"number": 3,  "name": "ビッグシーザー",   "jockey": "坂井瑠星",   "odds": 8.2,  "prob": 0.105},
            {"number": 4,  "name": "ピクシーナイト",   "jockey": "C.ルメール", "odds": 5.1,  "prob": 0.162},
            {"number": 5,  "name": "メイケイエール",   "jockey": "武豊",       "odds": 12.5, "prob": 0.072},
            {"number": 6,  "name": "ダイアトニック",   "jockey": "松山弘平",   "odds": 18.0, "prob": 0.048},
            {"number": 7,  "name": "タイセイビジョン", "jockey": "横山武史",   "odds": 24.3, "prob": 0.036},
            {"number": 8,  "name": "ホウオウアマゾン", "jockey": "岩田望来",   "odds": 31.0, "prob": 0.029},
            {"number": 9,  "name": "エイティーンガール","jockey": "M.デムーロ","odds": 42.5, "prob": 0.021},
            {"number": 10, "name": "リバーシブルレーン","jockey": "戸崎圭太",  "odds": 48.0, "prob": 0.018},
            {"number": 11, "name": "ジャスティンカフェ","jockey": "福永祐一",  "odds": 60.0, "prob": 0.016},
        ],
    },
    {
        "race_id": "202605021011r",
        "venue": "東京",
        "race_number": 11,
        "race_name": "ダイヤモンドS (G3)",
        "surface": "芝",
        "distance": 3400,
        "condition": "良",
        "entries": [
            {"number": 1,  "name": "テーオーロイヤル", "jockey": "C.ルメール", "odds": 2.8,  "prob": 0.245},
            {"number": 2,  "name": "サリエラ",         "jockey": "戸崎圭太",   "odds": 3.5,  "prob": 0.208},
            {"number": 3,  "name": "ワープスピード",   "jockey": "横山武史",   "odds": 5.8,  "prob": 0.145},
            {"number": 4,  "name": "ヒュミドール",     "jockey": "川田将雅",   "odds": 8.0,  "prob": 0.107},
            {"number": 5,  "name": "マイネルウィルトス","jockey": "松山弘平",  "odds": 12.5, "prob": 0.069},
            {"number": 6,  "name": "シルヴァーソニック","jockey": "武豊",      "odds": 15.0, "prob": 0.058},
            {"number": 7,  "name": "ディープモンスター","jockey": "岩田望来",  "odds": 22.0, "prob": 0.040},
            {"number": 8,  "name": "レクセランス",     "jockey": "坂井瑠星",   "odds": 35.0, "prob": 0.025},
            {"number": 9,  "name": "トーセンカンビーナ","jockey": "M.デムーロ","odds": 42.0, "prob": 0.021},
            {"number": 10, "name": "ゴースト",         "jockey": "浜中俊",     "odds": 58.0, "prob": 0.015},
            {"number": 11, "name": "アイアンバローズ", "jockey": "福永祐一",   "odds": 28.0, "prob": 0.032},
            {"number": 12, "name": "メイショウテンゲン","jockey": "幸英明",    "odds": 85.0, "prob": 0.010},
            {"number": 13, "name": "エヒト",           "jockey": "団野大成",   "odds": 45.0, "prob": 0.019},
            {"number": 14, "name": "プリュムドール",   "jockey": "田辺裕信",   "odds": 120.0,"prob": 0.006},
        ],
    },
    {
        "race_id": "202605020911r",
        "venue": "阪神",
        "race_number": 11,
        "race_name": "京都記念 (G2)",
        "surface": "芝",
        "distance": 2200,
        "condition": "良",
        "entries": [
            {"number": 1,  "name": "ドウデュース",     "jockey": "武豊",       "odds": 1.5,  "prob": 0.402},
            {"number": 2,  "name": "プログノーシス",   "jockey": "川田将雅",   "odds": 3.2,  "prob": 0.218},
            {"number": 3,  "name": "ベラジオオペラ",   "jockey": "横山武史",   "odds": 5.5,  "prob": 0.138},
            {"number": 4,  "name": "ルージュエヴァイユ","jockey": "C.ルメール","odds": 7.8,  "prob": 0.098},
            {"number": 5,  "name": "マテンロウレオ",   "jockey": "横山典弘",   "odds": 15.0, "prob": 0.055},
            {"number": 6,  "name": "エフフォーリア",   "jockey": "松山弘平",   "odds": 22.0, "prob": 0.038},
            {"number": 7,  "name": "アフリカンゴールド","jockey": "岩田望来",  "odds": 35.0, "prob": 0.024},
            {"number": 8,  "name": "キラーアビリティ", "jockey": "坂井瑠星",   "odds": 42.0, "prob": 0.018},
            {"number": 9,  "name": "ユニコーンライオン","jockey": "M.デムーロ","odds": 55.0, "prob": 0.009},
        ],
    },
]

# ──────────────────────────────────────────────────
# バックテスト用のダミー結果
# ──────────────────────────────────────────────────
DEMO_BACKTEST = [
    {"event_date": "2025-01-05", "cost": 8400, "is_hit": False, "payout": 0},
    {"event_date": "2025-01-12", "cost": 9600, "is_hit": False, "payout": 0},
    {"event_date": "2025-01-19", "cost": 7200, "is_hit": False, "payout": 0},
    {"event_date": "2025-01-26", "cost": 10000,"is_hit": False, "payout": 0},
    {"event_date": "2025-02-02", "cost": 8400, "is_hit": False, "payout": 0},
    {"event_date": "2025-02-09", "cost": 9600, "is_hit": True,  "payout": 185420},
    {"event_date": "2025-02-16", "cost": 7200, "is_hit": False, "payout": 0},
    {"event_date": "2025-02-23", "cost": 8400, "is_hit": False, "payout": 0},
    {"event_date": "2025-03-02", "cost": 9600, "is_hit": False, "payout": 0},
    {"event_date": "2025-03-09", "cost": 8400, "is_hit": False, "payout": 0},
    {"event_date": "2025-03-16", "cost": 10000,"is_hit": False, "payout": 0},
    {"event_date": "2025-03-23", "cost": 7200, "is_hit": False, "payout": 0},
    {"event_date": "2025-03-30", "cost": 9600, "is_hit": True,  "payout": 423810},
    {"event_date": "2025-04-06", "cost": 8400, "is_hit": False, "payout": 0},
    {"event_date": "2025-04-13", "cost": 9600, "is_hit": False, "payout": 0},
    {"event_date": "2025-04-20", "cost": 10000,"is_hit": False, "payout": 0},
    {"event_date": "2025-04-27", "cost": 7200, "is_hit": False, "payout": 0},
    {"event_date": "2025-05-04", "cost": 8400, "is_hit": False, "payout": 0},
    {"event_date": "2025-05-11", "cost": 9600, "is_hit": False, "payout": 0},
    {"event_date": "2025-05-18", "cost": 10000,"is_hit": False, "payout": 0},
    {"event_date": "2025-05-25", "cost": 8400, "is_hit": True,  "payout": 52340},
    {"event_date": "2025-06-01", "cost": 9600, "is_hit": False, "payout": 0},
    {"event_date": "2025-06-08", "cost": 7200, "is_hit": False, "payout": 0},
    {"event_date": "2025-06-15", "cost": 8400, "is_hit": False, "payout": 0},
    {"event_date": "2025-06-22", "cost": 9600, "is_hit": False, "payout": 0},
    {"event_date": "2025-06-29", "cost": 10000,"is_hit": False, "payout": 0},
    {"event_date": "2025-07-06", "cost": 8400, "is_hit": False, "payout": 0},
    {"event_date": "2025-07-13", "cost": 9600, "is_hit": True,  "payout": 890650},
    {"event_date": "2025-07-20", "cost": 7200, "is_hit": False, "payout": 0},
    {"event_date": "2025-07-27", "cost": 8400, "is_hit": False, "payout": 0},
    {"event_date": "2025-08-03", "cost": 9600, "is_hit": False, "payout": 0},
    {"event_date": "2025-08-10", "cost": 10000,"is_hit": False, "payout": 0},
    {"event_date": "2025-08-17", "cost": 8400, "is_hit": False, "payout": 0},
    {"event_date": "2025-08-24", "cost": 7200, "is_hit": False, "payout": 0},
    {"event_date": "2025-08-31", "cost": 9600, "is_hit": False, "payout": 0},
    {"event_date": "2025-09-07", "cost": 8400, "is_hit": False, "payout": 0},
    {"event_date": "2025-09-14", "cost": 9600, "is_hit": True,  "payout": 128700},
    {"event_date": "2025-09-21", "cost": 10000,"is_hit": False, "payout": 0},
    {"event_date": "2025-09-28", "cost": 7200, "is_hit": False, "payout": 0},
    {"event_date": "2025-10-05", "cost": 8400, "is_hit": False, "payout": 0},
    {"event_date": "2025-10-12", "cost": 9600, "is_hit": False, "payout": 0},
    {"event_date": "2025-10-19", "cost": 10000,"is_hit": False, "payout": 0},
    {"event_date": "2025-10-26", "cost": 8400, "is_hit": False, "payout": 0},
    {"event_date": "2025-11-02", "cost": 9600, "is_hit": True,  "payout": 67230},
    {"event_date": "2025-11-09", "cost": 7200, "is_hit": False, "payout": 0},
    {"event_date": "2025-11-16", "cost": 8400, "is_hit": False, "payout": 0},
    {"event_date": "2025-11-23", "cost": 9600, "is_hit": False, "payout": 0},
    {"event_date": "2025-11-30", "cost": 10000,"is_hit": False, "payout": 0},
    {"event_date": "2025-12-07", "cost": 8400, "is_hit": False, "payout": 0},
    {"event_date": "2025-12-14", "cost": 9600, "is_hit": False, "payout": 0},
    {"event_date": "2025-12-21", "cost": 7200, "is_hit": False, "payout": 0},
    {"event_date": "2025-12-28", "cost": 10000,"is_hit": True,  "payout": 241560},
]


def build_prediction_df(race: dict) -> pd.DataFrame:
    """デモ用の予測DataFrameを構築"""
    rows = []
    for e in race["entries"]:
        rows.append({
            "horse_number": e["number"],
            "horse_name": e["name"],
            "horse_id": f"demo_{e['number']}",
            "raw_prob": e["prob"],
            "calibrated_prob": e["prob"],
            "jockey": e["jockey"],
            "odds": e["odds"],
            "implied_prob": 1.0 / e["odds"] if e["odds"] > 0 else 0,
        })
    df = pd.DataFrame(rows).sort_values("calibrated_prob", ascending=False)
    df["rank"] = range(1, len(df) + 1)

    # 暗示確率との差(エッジ)
    df["edge"] = df["calibrated_prob"] - df["implied_prob"]

    return df.reset_index(drop=True)


def demo_predict():
    """予測デモ"""
    BUDGET = 10000

    console.print()
    console.print(Panel.fit(
        f"[bold white]Win5 予想レポート: {TARGET_DATE}[/]\n"
        f"生成日時: 2026-02-14 21:35\n"
        f"モデル: lgbm_win5_20260210_143022 (AUC=0.712)",
        title="🏇 Win5 Predictor",
        border_style="bright_blue",
    ))
    console.print()

    predictions = {}
    for race in DEMO_RACES:
        pred_df = build_prediction_df(race)
        predictions[race["race_id"]] = pred_df

        # レース情報ヘッダー
        table = Table(
            title=f"Race {DEMO_RACES.index(race)+1}: {race['venue']} {race['race_number']}R {race['race_name']}  ({race['surface']}{race['distance']}m / {race['condition']})",
            title_style="bold cyan",
            show_lines=False,
            padding=(0, 1),
        )
        table.add_column("予測順", justify="center", width=6, style="bold")
        table.add_column("馬番", justify="center", width=4)
        table.add_column("馬名", width=18)
        table.add_column("騎手", width=12)
        table.add_column("単勝", justify="right", width=6)
        table.add_column("予測勝率", justify="right", width=8, style="bold green")
        table.add_column("暗示確率", justify="right", width=8)
        table.add_column("Edge", justify="right", width=8)

        for _, row in pred_df.head(5).iterrows():
            edge = row["edge"]
            edge_style = "bold green" if edge > 0.02 else ("yellow" if edge > 0 else "red")
            edge_str = f"[{edge_style}]{edge:+.1%}[/{edge_style}]"

            rank_mark = ""
            if row["rank"] == 1:
                rank_mark = " ◎"
            elif row["rank"] == 2:
                rank_mark = " ○"
            elif row["rank"] == 3:
                rank_mark = " ▲"

            table.add_row(
                f"{row['rank']}{rank_mark}",
                str(row["horse_number"]),
                row["horse_name"],
                row["jockey"],
                f"{row['odds']:.1f}",
                f"{row['calibrated_prob']:.1%}",
                f"{row['implied_prob']:.1%}",
                edge_str,
            )

        console.print(table)
        console.print()

    # ──────────────────────────────
    # 最適買い目
    # ──────────────────────────────
    # 手動で最適割り当てを決定 (予算¥10,000 = 100口)
    # 2 x 2 x 2 x 3 x 2 = 48口 = ¥4,800
    # 3 x 2 x 2 x 2 x 2 = 48口 = ¥4,800
    # 2 x 2 x 3 x 3 x 2 = 72口 = ¥7,200
    # 2 x 3 x 2 x 3 x 2 = 72口 = ¥7,200

    allocations = [
        ("Race1 阪神9R",  [3, 4]),
        ("Race2 東京10R", [1, 2]),
        ("Race3 阪神10R", [2, 1, 4]),
        ("Race4 東京11R", [1, 2, 3]),
        ("Race5 阪神11R", [1, 2]),
    ]
    n_combos = 1
    for _, nums in allocations:
        n_combos *= len(nums)

    total_cost = n_combos * WIN5_BET_UNIT

    # 的中確率計算
    hit_prob = 1.0
    for race, (_, nums) in zip(DEMO_RACES, allocations):
        pred = build_prediction_df(race)
        race_prob = sum(
            pred[pred["horse_number"] == n]["calibrated_prob"].values[0]
            for n in nums
        )
        hit_prob *= race_prob

    console.print(Panel.fit(
        "[bold white]推奨買い目[/]",
        border_style="bright_yellow",
    ))

    ticket_table = Table(show_lines=True, padding=(0, 1))
    ticket_table.add_column("レース", style="cyan", width=18)
    ticket_table.add_column("選択頭数", justify="center", width=8)
    ticket_table.add_column("選択馬", width=50)

    for race, (label, nums) in zip(DEMO_RACES, allocations):
        pred = build_prediction_df(race)
        horse_strs = []
        for n in nums:
            row = pred[pred["horse_number"] == n].iloc[0]
            horse_strs.append(f"[bold]{n}[/] {row['horse_name']} ({row['calibrated_prob']:.1%})")
        ticket_table.add_row(
            label,
            str(len(nums)),
            " / ".join(horse_strs),
        )

    console.print(ticket_table)
    console.print()

    # 期待値計算
    ev_calc = ExpectedValueCalculator(
        estimated_pool=4_800_000_000,
        carryover=312_540_000,
    )
    net_pool = 4_800_000_000 * 0.70 + 312_540_000
    est_winners = max((4_800_000_000 / 100) * hit_prob, 1.0)
    est_payout = net_pool / est_winners
    ev = hit_prob * est_payout - total_cost
    roi = (hit_prob * est_payout / total_cost - 1.0) * 100

    summary_table = Table(show_header=False, padding=(0, 2), box=None)
    summary_table.add_column("label", style="dim", width=16)
    summary_table.add_column("value", style="bold white", width=24)
    summary_table.add_column("label2", style="dim", width=16)
    summary_table.add_column("value2", style="bold white", width=24)

    summary_table.add_row(
        "組合せ数", f"{n_combos} 通り",
        "購入金額", f"¥{total_cost:,}",
    )
    summary_table.add_row(
        "的中確率", f"{hit_prob:.4%}",
        "推定配当", f"¥{est_payout:,.0f}",
    )
    summary_table.add_row(
        "期待値", f"[{'green' if ev > 0 else 'red'}]¥{ev:,.0f}[/]",
        "推定ROI", f"[{'green' if roi > 0 else 'red'}]{roi:+.1f}%[/]",
    )
    summary_table.add_row(
        "キャリーオーバー", f"¥312,540,000",
        "推定発売総額", f"¥4,800,000,000",
    )

    console.print(Panel(summary_table, title="[bold]サマリー[/]", border_style="bright_green"))
    console.print()

    # Kelly基準
    from bankroll.kelly import kelly_criterion
    kelly = kelly_criterion(
        probability=hit_prob,
        odds=est_payout / total_cost,
        bankroll=500000,
    )
    console.print(Panel.fit(
        f"[bold white]資金管理 (Kelly基準)[/]\n\n"
        f"  現在の資金:   ¥500,000\n"
        f"  Full Kelly:   {kelly['full_kelly']:.4%}\n"
        f"  1/4 Kelly:    {kelly['kelly_fraction']:.4%}\n"
        f"  推奨ベット額: [bold green]¥{kelly['bet_amount']:,.0f}[/]\n"
        f"  エッジ:       {kelly['edge']:+.4f}\n"
        f"  ベット判定:   {'[bold green]BET[/]' if kelly['should_bet'] else '[bold red]SKIP[/]'}",
        border_style="bright_magenta",
    ))


def demo_backtest():
    """バックテストデモ"""
    console.print()
    console.print(Panel.fit(
        "[bold white]バックテストレポート: 2025年[/]\n"
        "モデル: lgbm_win5_20260210_143022\n"
        "予算: ¥10,000 / 回",
        title="📊 Backtest Results",
        border_style="bright_blue",
    ))
    console.print()

    df = pd.DataFrame(DEMO_BACKTEST)
    total_cost = df["cost"].sum()
    total_payout = df["payout"].sum()
    profit = total_payout - total_cost
    roi = total_payout / total_cost * 100
    hits = df["is_hit"].sum()
    hit_rate = hits / len(df) * 100

    # サマリー
    s = Table(show_header=False, box=None, padding=(0, 2))
    s.add_column(width=18, style="dim")
    s.add_column(width=20, style="bold")
    s.add_column(width=18, style="dim")
    s.add_column(width=20, style="bold")

    s.add_row("対象期間", "2025/01 - 2025/12", "イベント数", f"{len(df)} 回")
    s.add_row("的中数", f"{hits} 回 ({hit_rate:.1f}%)", "総投資額", f"¥{total_cost:,}")
    s.add_row("総配当額", f"¥{total_payout:,}", "損益", f"[{'green' if profit>0 else 'red'}]¥{profit:,}[/]")
    s.add_row("回収率", f"[{'green' if roi>100 else 'red'}]{roi:.1f}%[/]", "平均配当", f"¥{total_payout/max(hits,1):,.0f}")

    console.print(Panel(s, title="[bold]全体サマリー[/]", border_style="bright_green"))
    console.print()

    # 月別成績
    df["month"] = pd.to_datetime(df["event_date"]).dt.strftime("%Y-%m")
    monthly = df.groupby("month").agg(
        events=("event_date", "count"),
        hits=("is_hit", "sum"),
        cost=("cost", "sum"),
        payout=("payout", "sum"),
    ).reset_index()
    monthly["profit"] = monthly["payout"] - monthly["cost"]
    monthly["roi"] = monthly["payout"] / monthly["cost"] * 100

    m_table = Table(title="月別成績", title_style="bold cyan")
    m_table.add_column("月", width=8)
    m_table.add_column("回数", justify="center", width=4)
    m_table.add_column("的中", justify="center", width=4)
    m_table.add_column("投資額", justify="right", width=10)
    m_table.add_column("配当額", justify="right", width=12)
    m_table.add_column("損益", justify="right", width=12)
    m_table.add_column("回収率", justify="right", width=8)

    for _, row in monthly.iterrows():
        p_style = "green" if row["profit"] >= 0 else "red"
        r_style = "green" if row["roi"] >= 100 else "red"
        m_table.add_row(
            row["month"],
            str(int(row["events"])),
            str(int(row["hits"])),
            f"¥{row['cost']:,.0f}",
            f"¥{row['payout']:,.0f}",
            f"[{p_style}]¥{row['profit']:+,.0f}[/{p_style}]",
            f"[{r_style}]{row['roi']:.0f}%[/{r_style}]",
        )

    console.print(m_table)
    console.print()

    # 累計損益推移
    df_sorted = df.sort_values("event_date")
    df_sorted["profit_each"] = df_sorted["payout"] - df_sorted["cost"]
    df_sorted["cum_profit"] = df_sorted["profit_each"].cumsum()

    console.print("[bold cyan]累計損益推移[/]")
    console.print()

    # テキストベースのチャート
    cum_vals = df_sorted["cum_profit"].tolist()
    max_val = max(abs(v) for v in cum_vals) or 1
    chart_width = 50

    for i, (_, row) in enumerate(df_sorted.iterrows()):
        val = row["cum_profit"]
        bar_len = int(abs(val) / max_val * chart_width)
        if val >= 0:
            bar = " " * chart_width + "│" + "█" * bar_len
            style = "green"
        else:
            pad = chart_width - bar_len
            bar = " " * pad + "█" * bar_len + "│"
            style = "red"

        if i % 4 == 0:
            label = row["event_date"][:7]
        else:
            label = "       "
        console.print(f"  {label} [{style}]{bar}[/{style}] ¥{val:+,.0f}")

    console.print()

    # ドローダウン分析
    peak = 0
    max_dd = 0
    max_streak = 0
    current_streak = 0

    for _, row in df_sorted.iterrows():
        cum = row["cum_profit"]
        if cum > peak:
            peak = cum
        dd = cum - peak
        if dd < max_dd:
            max_dd = dd
        if not row["is_hit"]:
            current_streak += 1
            max_streak = max(max_streak, current_streak)
        else:
            current_streak = 0

    dd_table = Table(title="リスク分析", title_style="bold cyan", show_header=False, box=None, padding=(0, 2))
    dd_table.add_column(width=22, style="dim")
    dd_table.add_column(width=20, style="bold")
    dd_table.add_row("最大ドローダウン", f"[red]¥{max_dd:,.0f}[/]")
    dd_table.add_row("最大連敗", f"{max_streak} 回")
    dd_table.add_row("平均投資額/回", f"¥{total_cost/len(df):,.0f}")
    dd_table.add_row("的中時平均配当", f"¥{total_payout/max(hits,1):,.0f}")
    dd_table.add_row("プロフィットファクター", f"{total_payout/total_cost:.2f}")

    console.print(Panel(dd_table, border_style="bright_red"))
    console.print()


def demo_status():
    """システムステータスデモ"""
    console.print()
    table = Table(title="Win5 Predictor Status", title_style="bold")
    table.add_column("Item", style="cyan", width=22)
    table.add_column("Value", style="green", width=50)

    table.add_row("DB Path", r"D:\win5_predictor\data\win5.db")
    table.add_row("DB Size", "2.4 GB")
    table.add_row("Races", "52,847")
    table.add_row("Results", "634,182")
    table.add_row("Horses", "28,451")
    table.add_row("Jockeys", "892")
    table.add_row("Trainers", "645")
    table.add_row("Date Range", "2020-01-05 ~ 2026-02-09")
    table.add_row("Win5 Events", "312")
    table.add_row("Active Model", "lgbm_win5_20260210_143022")
    table.add_row("Model AUC", "0.7124")
    table.add_row("Model Features", "98")
    table.add_row("Last Updated", "2026-02-10 14:30")

    console.print(table)
    console.print()


def main():
    console.print()
    console.rule("[bold bright_blue]Win5 Predictor - デモ出力[/]")
    console.print()
    console.print("  [dim]実データなしで最終アウトプットのイメージを表示します。[/]")
    console.print("  [dim]以下の3種類の出力を順に表示します:[/]")
    console.print("    1. [cyan]win5 status[/]        - システム状態")
    console.print("    2. [cyan]win5 predict[/]       - Win5予測レポート")
    console.print("    3. [cyan]win5 backtest[/]      - バックテスト結果")
    console.print()
    console.rule()

    # ① システム状態
    console.print()
    console.rule("[bold]1. win5 status[/]", style="cyan")
    demo_status()

    # ② 予測レポート
    console.rule("[bold]2. win5 predict --date 2026-02-15 --budget 10000[/]", style="cyan")
    demo_predict()

    # ③ バックテスト
    console.rule("[bold]3. win5 backtest --start 2025-01-01 --end 2025-12-31 --budget 10000[/]", style="cyan")
    demo_backtest()

    console.rule("[bold bright_blue]デモ出力 終了[/]")
    console.print()
    console.print("[dim]※ 上記は架空データによるデモです。実際の予測結果とは異なります。[/]")
    console.print("[dim]※ 実運用には: win5 collect → win5 train → win5 predict の手順が必要です。[/]")
    console.print()


if __name__ == "__main__":
    main()
