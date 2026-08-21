# -*- coding: utf-8 -*-
"""JV-Data 一括ダンプCLI: 指定dataspecの生レコードをレコード種別ごとのファイルへ保存

使い方（32bit Pythonで実行）:
    C:/Users/fcmdt/py312-32/python.exe jv_dump.py SLOP 20210101000000 4
    C:/Users/fcmdt/py312-32/python.exe jv_dump.py WOOD 20210101000000 4
    C:/Users/fcmdt/py312-32/python.exe jv_dump.py BLOD 20210101000000 4

出力: C:/Users/fcmdt/jvdata/raw/<dataspec>/<レコード種別>.txt（1行1レコード・UTF-8）
パーサは後段（このダンプがあれば仕様書に沿っていつでも特徴量化できる）
"""
import io
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from jvlink_client import JVLinkClient, _decode

OUT_BASE = r"C:\Users\fcmdt\jvdata\raw"
STATE = r"C:\Users\fcmdt\jvdata\state.json"


def load_state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(st):
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(st, f, indent=1)


def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    dataspec = sys.argv[1]
    fromtime = sys.argv[2] if len(sys.argv) > 2 else "20210101000000"
    option = int(sys.argv[3]) if len(sys.argv) > 3 else 4
    state = load_state()
    if fromtime == "auto":
        # 前回のlastfiletimestampから差分取得（未実行ならフル）
        fromtime = state.get(dataspec, "20210101000000")
        option = 1

    out_dir = os.path.join(OUT_BASE, dataspec)
    os.makedirs(out_dir, exist_ok=True)
    files = {}
    counts = {}
    t0 = time.time()
    print(f"[dump] {dataspec} from={fromtime} option={option}", flush=True)

    with JVLinkClient() as jv:
        readcount, dlcount, lastts = jv.open(dataspec, fromtime, option)
        print(f"[dump] readcount={readcount} dlcount={dlcount} lastTS={lastts}", flush=True)
        if readcount == 0 and dlcount == 0:
            print(f"[dump] DONE {dataspec}: 新着なし", flush=True)
            return
        last_report = [0.0]

        def progress(st, tot):
            if time.time() - last_report[0] > 30:
                print(f"[dump] download {st}/{tot}", flush=True)
                last_report[0] = time.time()

        jv.wait_download(dlcount, progress=progress)
        n = 0
        while True:
            code, buff = jv._read_one()
            if code == 0:
                break
            if code == -1:
                continue
            if code == -3:
                time.sleep(1)
                continue
            if code in (-402, -403):
                jv._jv.JVSkip()
                continue
            if code < 0:
                print(f"[dump] JVRead error {code} — abort", flush=True)
                break
            rec = _decode(buff)
            rt = rec[:2]
            if rt not in files:
                files[rt] = open(os.path.join(out_dir, f"{rt}.txt"), "a", encoding="utf-8")
            files[rt].write(rec.rstrip("\r\n") + "\n")
            counts[rt] = counts.get(rt, 0) + 1
            n += 1
            if n % 100000 == 0:
                print(f"[dump] {n} records... {counts}", flush=True)

    for f in files.values():
        f.close()
    if lastts and str(lastts).strip():
        state[dataspec] = str(lastts).strip()
        save_state(state)
    print(f"[dump] DONE {dataspec}: {n} records in {time.time()-t0:.0f}s / {counts}", flush=True)


if __name__ == "__main__":
    main()
