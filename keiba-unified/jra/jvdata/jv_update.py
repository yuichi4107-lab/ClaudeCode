# -*- coding: utf-8 -*-
"""JVデータ 日次更新オーケストレータ（Task Scheduler: 毎日06:05想定）

1. SLOP/WOOD/DIFF の差分ダンプ（32bit Pythonのjv_dump.pyを子プロセスで実行）
2. HCパース（冪等upsert）で jvdata.sqlite 更新
3. VPSへ jvdata.sqlite を転送

64bit Pythonで実行してよい（COM部分は子プロセスの32bit Pythonが担う）
"""
import io
import os
import subprocess
import sys
import time

LOG = r"C:\Users\fcmdt\jvdata\update.log"


class _Tee(io.TextIOBase):
    """stdoutとログファイルの両方へ書く（Task Scheduler実行時の記録用）"""

    def __init__(self):
        self._con = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        self._f = open(LOG, "a", encoding="utf-8")

    def write(self, s):
        self._con.write(s)
        self._f.write(s)
        return len(s)

    def flush(self):
        self._con.flush()
        self._f.flush()


sys.stdout = _Tee()
print(f"\n===== jv_update {time.strftime('%Y-%m-%d %H:%M:%S')} =====", flush=True)

HERE = os.path.dirname(os.path.abspath(__file__))
PY32 = r"C:\Users\fcmdt\py312-32\python.exe"
DB = r"C:\Users\fcmdt\jvdata\jvdata.sqlite"
VPS = "root@163.44.101.31:/opt/keiba-unified/jra/data/jvdata.sqlite"


def run(cmd, timeout=3600):
    print(f"[update] $ {' '.join(cmd)}", flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout)
    print(r.stdout[-2000:], flush=True)
    if r.returncode != 0:
        print(r.stderr[-1000:], flush=True)
        raise RuntimeError(f"failed: {cmd} rc={r.returncode}")


def main():
    t0 = time.time()
    # DIFN/BLDN=マスタ系の現行形式（旧DIFF/BLODは2023-07で凍結されているため使わない）
    for spec in ("SLOP", "WOOD", "DIFN", "BLDN"):
        run([PY32, os.path.join(HERE, "jv_dump.py"), spec, "auto"])
    run([sys.executable, os.path.join(HERE, "parse_hc.py")])
    run([sys.executable, os.path.join(HERE, "parse_wc.py")])
    run(["scp", "-o", "BatchMode=yes", DB, VPS], timeout=1800)
    print(f"[update] ALL DONE in {time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
