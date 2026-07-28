"""
ショートバックテスト全12ケース一括実行スクリプト
Phase A: runner.py x 12
Phase B: optimizer.py x 12
"""
import os
import sys
import json
import time
import subprocess
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "short_backtest_all.log")

CASES = [
    {"id": 1, "currency": "BTC-USDT", "pattern": "double_top", "data": "data/ohlcv/BTC-USDT_1d_1000.json"},
    {"id": 2, "currency": "BTC-USDT", "pattern": "rsi_overbought_reversal", "data": "data/ohlcv/BTC-USDT_1d_1000.json"},
    {"id": 3, "currency": "BTC-USDT", "pattern": "rally_top", "data": "data/ohlcv/BTC-USDT_1d_1000.json"},
    {"id": 4, "currency": "ETH-USDT", "pattern": "double_top", "data": "data/ohlcv/ETH-USDT_1d_1000.json"},
    {"id": 5, "currency": "ETH-USDT", "pattern": "rsi_overbought_reversal", "data": "data/ohlcv/ETH-USDT_1d_1000.json"},
    {"id": 6, "currency": "ETH-USDT", "pattern": "rally_top", "data": "data/ohlcv/ETH-USDT_1d_1000.json"},
    {"id": 7, "currency": "SOL-USDT", "pattern": "double_top", "data": "data/ohlcv/SOL-USDT_1d_1000.json"},
    {"id": 8, "currency": "SOL-USDT", "pattern": "rsi_overbought_reversal", "data": "data/ohlcv/SOL-USDT_1d_1000.json"},
    {"id": 9, "currency": "SOL-USDT", "pattern": "rally_top", "data": "data/ohlcv/SOL-USDT_1d_1000.json"},
    {"id": 10, "currency": "XRP-USDT", "pattern": "double_top", "data": "data/ohlcv/XRP-USDT_1d_1000.json"},
    {"id": 11, "currency": "XRP-USDT", "pattern": "rsi_overbought_reversal", "data": "data/ohlcv/XRP-USDT_1d_1000.json"},
    {"id": 12, "currency": "XRP-USDT", "pattern": "rally_top", "data": "data/ohlcv/XRP-USDT_1d_1000.json"},
]


def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        print(f"[{ts}] [log-encode-err]", flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run_runner(case):
    """runner.pyを実行してresult.jsonのパスを返す"""
    data_path = os.path.join(BASE_DIR, case["data"])
    cmd = [
        sys.executable, "-u",
        os.path.join(BASE_DIR, "src/backtest/runner.py"),
        data_path,
        "--pattern", case["pattern"],
        "--direction", "short",
        "--window", "50",
        "--step", "5",
        "--hold", "20",
        "--delay", "1.0",
    ]

    log(f"Case {case['id']}: {case['currency']} {case['pattern']} 開始")
    start_time = time.time()

    result_json_path = None
    signal_count = 0
    output_lines = []

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=BASE_DIR,
    )

    for line in proc.stdout:
        line = line.rstrip()
        output_lines.append(line)
        try:
            print(f"  {line}", flush=True)
        except UnicodeEncodeError:
            print(f"  [encode-err]", flush=True)

        # result.jsonのパスを抽出
        if "Results saved:" in line:
            result_json_path = line.split("Results saved:")[-1].strip()

        # シグナル数を抽出
        if "Signals detected" in line:
            try:
                signal_count = int(line.split(":")[-1].strip())
            except:
                pass

    proc.wait()
    elapsed = time.time() - start_time

    log(f"Case {case['id']}: 完了 ({elapsed:.0f}秒), result.json={result_json_path}, signals={signal_count}")

    return {
        "case": case,
        "result_json": result_json_path,
        "signal_count": signal_count,
        "elapsed": elapsed,
        "returncode": proc.returncode,
    }


def run_optimizer(case_result):
    """optimizer.pyを実行してgrid_search結果を返す"""
    case = case_result["case"]
    result_json = case_result["result_json"]

    if not result_json or not os.path.exists(result_json):
        log(f"Optimizer Case {case['id']}: result.json not found: {result_json}")
        return {"case": case, "error": "result.json not found", "best_calmar": None, "best_dd30": None}

    cmd = [
        sys.executable, "-u",
        os.path.join(BASE_DIR, "src/backtest/optimizer.py"),
        result_json,
        "--extended",
        "--max-dd", "30",
    ]

    log(f"Optimizer Case {case['id']}: {case['currency']} {case['pattern']} 開始")
    start_time = time.time()

    output_lines = []
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=BASE_DIR,
    )

    for line in proc.stdout:
        line = line.rstrip()
        output_lines.append(line)
        try:
            print(f"  {line}", flush=True)
        except UnicodeEncodeError:
            print(f"  [encode-err]", flush=True)

    proc.wait()
    elapsed = time.time() - start_time

    log(f"Optimizer Case {case['id']}: done ({elapsed:.0f}s)")

    # grid_search_results.jsonを読み込む
    result_dir = os.path.dirname(result_json)
    grid_file = os.path.join(result_dir, "grid_search_results.json")

    best_calmar = None
    best_dd30 = None

    if os.path.exists(grid_file):
        with open(grid_file, "r", encoding="utf-8") as f:
            grid_data = json.load(f)

        # best_calmar
        if "best_calmar" in grid_data:
            best_calmar = grid_data["best_calmar"]
        elif "results" in grid_data and grid_data["results"]:
            # calmarでソートして最良を選ぶ
            results = grid_data["results"]
            valid = [r for r in results if r.get("calmar") is not None and r.get("max_dd_pct", 100) <= 100]
            if valid:
                best_calmar = max(valid, key=lambda x: x.get("calmar", 0))

        # best_dd30 (DD<=30%)
        if "best_dd30" in grid_data:
            best_dd30 = grid_data["best_dd30"]
        elif "results" in grid_data and grid_data["results"]:
            results = grid_data["results"]
            dd30 = [r for r in results if r.get("max_dd_pct", 100) <= 30]
            if dd30:
                best_dd30 = max(dd30, key=lambda x: x.get("calmar", 0))

    return {
        "case": case,
        "result_json": result_json,
        "grid_file": grid_file if os.path.exists(grid_file) else None,
        "best_calmar": best_calmar,
        "best_dd30": best_dd30,
        "output": "\n".join(output_lines),
        "elapsed": elapsed,
    }


def main():
    overall_start = time.time()
    log("=== ショートバックテスト全12ケース開始 ===")

    # Phase A: runner.py
    log("--- Phase A: Gemini判定バックテスト ---")
    phase_a_results = []
    for case in CASES:
        result = run_runner(case)
        phase_a_results.append(result)
        # ケース間に少しウェイト
        if case["id"] < 12:
            time.sleep(2)

    log("--- Phase A 完了 ---")

    # Phase B: optimizer.py
    log("--- Phase B: TP/SL最適化 ---")
    phase_b_results = []
    for phase_a in phase_a_results:
        result = run_optimizer(phase_a)
        phase_b_results.append(result)
        if phase_a["case"]["id"] < 12:
            time.sleep(1)

    log("--- Phase B 完了 ---")

    # サマリー出力
    overall_elapsed = time.time() - overall_start
    log(f"\n=== 全12ケース完了 (合計: {overall_elapsed/60:.1f}分) ===\n")

    print("\n" + "=" * 100)
    print("最終サマリー表")
    print("=" * 100)
    print(f"{'ケース':<30} {'シグナル数':>10} {'Best Calmar推奨':<45} {'Best DD≤30%推奨':<45}")
    print("-" * 100)

    for i, (pa, pb) in enumerate(zip(phase_a_results, phase_b_results)):
        case = pa["case"]
        case_name = f"{case['currency']} {case['pattern']}"
        signals = pa["signal_count"]

        # Best Calmar
        if pb.get("best_calmar"):
            bc = pb["best_calmar"]
            calmar_str = f"TP={bc.get('tp_pct','?')} SL={bc.get('sl_pct','?')} Hold={bc.get('hold_bars','?')} PF={bc.get('profit_factor','?')} Ret={bc.get('total_return_pct','?')}% DD={bc.get('max_dd_pct','?')}%"
        else:
            calmar_str = "N/A"

        # Best DD30
        if pb.get("best_dd30"):
            bd = pb["best_dd30"]
            dd30_str = f"TP={bd.get('tp_pct','?')} SL={bd.get('sl_pct','?')} Hold={bd.get('hold_bars','?')} PF={bd.get('profit_factor','?')} Ret={bd.get('total_return_pct','?')}% DD={bd.get('max_dd_pct','?')}%"
        else:
            dd30_str = "N/A"

        print(f"{case_name:<30} {signals:>10} {calmar_str:<45} {dd30_str:<45}")

    print("=" * 100)

    # JSON保存
    summary = {
        "generated_at": datetime.now().isoformat(),
        "total_elapsed_min": round(overall_elapsed / 60, 1),
        "cases": []
    }
    for pa, pb in zip(phase_a_results, phase_b_results):
        summary["cases"].append({
            "id": pa["case"]["id"],
            "currency": pa["case"]["currency"],
            "pattern": pa["case"]["pattern"],
            "signal_count": pa["signal_count"],
            "result_json": pa["result_json"],
            "grid_file": pb.get("grid_file"),
            "best_calmar": pb.get("best_calmar"),
            "best_dd30": pb.get("best_dd30"),
        })

    summary_path = os.path.join(BASE_DIR, "short_backtest_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    log(f"サマリー保存: {summary_path}")


if __name__ == "__main__":
    main()
