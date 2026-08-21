# -*- coding: utf-8 -*-
"""JV-Link (JRA-VAN Data Lab.) Python クライアント

前提（2026-07-11に確立した動作パターン）:
  - JV-Linkは32bit COMのため **32bit Python** (C:/Users/fcmdt/py312-32) で実行する
  - タイプライブラリのJVRead宣言が誤っている（sizeが実際は入力なのにoutと宣言）ため、
    pywin32の InvokeTypes で引数型を手動指定して呼ぶ
  - BSTRにSJISバイト列がANSI(cp1252)経由で化けて入るため cp1252→cp932 で復元する

使い方:
    from jvlink_client import JVLinkClient
    with JVLinkClient() as jv:
        for rec in jv.records("SLOP", "20210101000000", option=4):
            ...  # rec は復元済みのレコード文字列（先頭2文字がレコード種別）
"""
import time

import win32com.client

SID = "UNKNOWN"
DISPID_JVREAD = 9
# buff: VT_BYREF|VT_BSTR in/out, size: VT_BYREF|VT_I4 in/out, fname: VT_BYREF|VT_BSTR out
JVREAD_ARGTYPES = ((16392, 3), (16387, 3), (16392, 2))
BUFF_SIZE = 110000


def _decode(b):
    """JV-LinkのBSTR文字化け復元（cp1252経由のSJIS）"""
    if not b:
        return ""
    try:
        return b.encode("cp1252", errors="strict").decode("cp932", errors="replace")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return b


class JVLinkError(RuntimeError):
    pass


class JVLinkClient:
    def __init__(self, sid=SID):
        self._jv = win32com.client.gencache.EnsureDispatch("JVDTLab.JVLink")
        rc = self._jv.JVInit(sid)
        if rc != 0:
            raise JVLinkError(f"JVInit failed: {rc}")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        try:
            self._jv.JVClose()
        except Exception:
            pass

    def open(self, dataspec, fromtime, option=1):
        """JVOpen。戻り値 (readcount, downloadcount, lastfiletimestamp)

        rc=-1 は「該当データなし」（差分取得で新着ゼロ）の正常系 → (0,0,fromtime) を返す
        """
        rc, readcount, dlcount, lastts = self._jv.JVOpen(dataspec, fromtime, option, 0, 0)
        if rc == -1:
            return 0, 0, fromtime
        if rc != 0:
            raise JVLinkError(f"JVOpen({dataspec},{fromtime},{option}) failed: {rc}")
        return readcount, dlcount, lastts

    def wait_download(self, dlcount, poll=2.0, timeout=7200, progress=None):
        """ダウンロード完了待ち。JVStatusがdlcountに達するまでポーリング"""
        if dlcount <= 0:
            return
        t0 = time.time()
        while True:
            st = self._jv.JVStatus()
            if st < 0:
                raise JVLinkError(f"JVStatus error: {st}")
            if progress:
                progress(st, dlcount)
            if st >= dlcount:
                return
            if time.time() - t0 > timeout:
                raise JVLinkError(f"download timeout: {st}/{dlcount}")
            time.sleep(poll)

    def _read_one(self):
        """1レコード読む。戻り値 (code, decoded_buff)"""
        ret = self._jv._oleobj_.InvokeTypes(
            DISPID_JVREAD, 0, 1, (3, 0), JVREAD_ARGTYPES, "", BUFF_SIZE)
        return ret[0], ret[1]

    def records(self, dataspec, fromtime, option=1, on_skip=None):
        """JVOpen→全レコードをyieldするジェネレータ。

        -402/-403（ファイル破損等）は JVSkip でスキップして継続する。
        """
        readcount, dlcount, lastts = self.open(dataspec, fromtime, option)
        self.wait_download(dlcount)
        skipped = 0
        while True:
            code, buff = self._read_one()
            if code == 0:          # 全ファイル読了
                break
            if code == -1:         # ファイル切替
                continue
            if code == -3:         # ダウンロード中
                time.sleep(1)
                continue
            if code in (-402, -403):   # ファイル破損 → スキップ
                skipped += 1
                if on_skip:
                    on_skip(code)
                self._jv.JVSkip()
                continue
            if code < 0:
                raise JVLinkError(f"JVRead failed: {code}")
            yield _decode(buff)
        if skipped:
            print(f"[jvlink] skipped {skipped} broken files", flush=True)

    def status(self):
        return self._jv.JVStatus()
