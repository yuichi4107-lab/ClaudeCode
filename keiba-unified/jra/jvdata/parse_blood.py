#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
parse_blood.py

Decode JRA-VAN blood-line master files (SK.txt / HN.txt / UM.txt) and build a
`blood` table in jvdata.sqlite for pedigree-based prediction models.

--- Encoding quirk ------------------------------------------------------
The raw txt files under raw/BLDN and raw/DIFN are NOT plain Shift-JIS. Each
line is UTF-8 text that was produced by taking the *original* Shift-JIS
bytes, decoding them one-by-one as if they were windows-1252 (the WHATWG
"windows-1252" table, where the C1 range 0x80-0x9F maps to curly quotes /
control chars per that table instead of raising an error), and then
re-encoding the resulting string as UTF-8. This mangles every Japanese
character but the transformation is fully reversible:

    utf8_bytes -> decode('utf-8') -> for each char, map back through the
    windows-1252 code table -> original Shift-JIS byte -> decode('cp932')

After reversing this, every record in a given file has a *constant* number
of recovered Shift-JIS bytes (verified: SK.txt = 206 bytes/record,
HN.txt = 249 bytes/record, UM.txt = 1607 bytes/record), confirming the
classic JV-Data fixed-length record layout. Field offsets below are byte
offsets into the recovered Shift-JIS record, not into the mojibake text.

--- Layout summary (see report for full derivation/validation) ---------
SK.txt (産駒3代血統, 206 bytes/record):
  [0:2]    "SK"
  [2:3]    kubun
  [3:11]   created date (YYYYMMDD)
  [11:21]  horse_id      -- this horse's own 血統登録番号 (10 digits)
  [21:29]  birth date (YYYYMMDD)
  [66:206] pedigree block: 14 x 10-byte 繁殖登録番号, in order
           0=sire 1=dam 2=FF 3=FM 4=damsire(MF) 5=MM 6..13=great-grandparents

HN.txt (繁殖馬マスタ, 249 bytes/record):
  [11:21]  horse_id -- 繁殖登録番号 (matches SK pedigree IDs)
  [40:76]  JP name (36 bytes, zenkaku, cp932)
  [229:239]/[239:249] this animal's own sire_id / damsire_id (bonus, unused)

UM.txt (馬マスタ, 1607 bytes/record, covers ALL horses incl. pre-2021):
  [11:21]  horse_id -- same 血統登録番号 namespace as SK
  [38:46]  birth date (YYYYMMDD)
  [204 + 46*i : 204 + 46*i + 46] for i in 0..13: 10-byte id + 36-byte name,
           same generation order as SK's pedigree block.

--- Build strategy -------------------------------------------------------
1. Parse HN.txt -> hn_map: breeding_id -> name
2. Parse UM.txt -> um_map: horse_id -> dict(birth_year, sire_id, sire_name,
   dam_id, dam_name, damsire_id, damsire_name)  (UM already embeds names,
   used both as the pre-2021 fallback source AND as a secondary name-fill
   whenever HN.txt is missing a particular breeding animal's own record.)
3. Parse SK.txt -> primary source of (horse_id, sire_id, dam_id, damsire_id)
   for horses it covers (dabout 2021+).
   sire_name  = hn_map.get(sire_id)  or um_map[horse_id].sire_name (if any)
   damsire_name = hn_map.get(damsire_id) or um_map[horse_id].damsire_name
4. For every horse_id in UM.txt NOT covered by SK.txt (pre-2021 horses),
   emit a row straight from UM's own embedded pedigree (ids + names).
5. Write result to the `blood` table in jvdata.sqlite (DROP+CREATE, insert
   only -- the existing `hanro` table and other tables are never touched).

Run: python parse_blood.py
"""
import random
import sqlite3
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
SK_PATH = BASE / "raw" / "BLDN" / "SK.txt"
HN_PATH = BASE / "raw" / "BLDN" / "HN.txt"
UM_PATH = BASE / "raw" / "DIFN" / "UM.txt"
DB_PATH = BASE / "jvdata.sqlite"

SK_RECLEN = 206
HN_RECLEN = 249
UM_RECLEN = 1607

# ---------------------------------------------------------------------
# Mojibake reversal: SJIS byte -> (mis-decoded as windows-1252) -> unicode
# codepoint -> (encoded as UTF-8) -> what's actually stored in the file.
# We build the forward table then invert it.
# ---------------------------------------------------------------------
_WIN1252_HIGH = {
    0x80: 0x20AC, 0x81: 0x0081, 0x82: 0x201A, 0x83: 0x0192, 0x84: 0x201E,
    0x85: 0x2026, 0x86: 0x2020, 0x87: 0x2021, 0x88: 0x02C6, 0x89: 0x2030,
    0x8A: 0x0160, 0x8B: 0x2039, 0x8C: 0x0152, 0x8D: 0x008D, 0x8E: 0x017D,
    0x8F: 0x008F, 0x90: 0x0090, 0x91: 0x2018, 0x92: 0x2019, 0x93: 0x201C,
    0x94: 0x201D, 0x95: 0x2022, 0x96: 0x2013, 0x97: 0x2014, 0x98: 0x02DC,
    0x99: 0x2122, 0x9A: 0x0161, 0x9B: 0x203A, 0x9C: 0x0153, 0x9D: 0x009D,
    0x9E: 0x017E, 0x9F: 0x0178,
}


def _build_reverse_table():
    """codepoint(int) -> original SJIS byte value(int), for str.translate."""
    table = {}
    for byte in range(0x100):
        cp = _WIN1252_HIGH.get(byte, byte)
        table[cp] = byte
    return table


_REV_TABLE = _build_reverse_table()


def recover_sjis_bytes(line: bytes) -> bytes:
    """Reverse the UTF-8(windows-1252(SJIS)) mojibake for one raw line."""
    s = line.decode("utf-8")
    # translate every char to its recovered byte value, then pack to bytes
    mapped = s.translate(_REV_TABLE)
    return mapped.encode("latin-1")


def iter_records(path: Path, reclen: int):
    """Yield recovered fixed-length SJIS byte records from a mojibake file."""
    with open(path, "rb") as f:
        for raw in f:
            raw = raw.rstrip(b"\r\n")
            if not raw:
                continue
            b = recover_sjis_bytes(raw)
            if len(b) != reclen:
                # Unexpected -- skip rather than crash the whole run, but
                # this should not happen given the verified fixed length.
                continue
            yield b


def sjis_field(b: bytes, lo: int, hi: int) -> str:
    return b[lo:hi].decode("cp932", errors="replace").strip("　 ")


def ascii_field(b: bytes, lo: int, hi: int) -> str:
    return b[lo:hi].decode("ascii", errors="replace")


# ---------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------

def parse_hn(path: Path) -> dict:
    """HN.txt -> {breeding_id: name}"""
    hn_map = {}
    for b in iter_records(path, HN_RECLEN):
        hid = ascii_field(b, 11, 21)
        name = sjis_field(b, 40, 76)
        if hid and name:
            hn_map[hid] = name
    return hn_map


def parse_um(path: Path) -> dict:
    """UM.txt -> {horse_id: {birth_year, sire_id, sire_name, dam_id,
    dam_name, damsire_id, damsire_name}}"""
    um_map = {}
    for b in iter_records(path, UM_RECLEN):
        hid = ascii_field(b, 11, 21)
        if not hid:
            continue
        birth = ascii_field(b, 38, 46)
        birth_year = birth[:4] if birth[:4].isdigit() else None

        def block(i):
            off = 204 + 46 * i
            bid = ascii_field(b, off, off + 10)
            bname = sjis_field(b, off + 10, off + 46)
            return (bid or None), (bname or None)

        sire_id, sire_name = block(0)
        dam_id, dam_name = block(1)
        damsire_id, damsire_name = block(4)
        um_map[hid] = {
            "birth_year": birth_year,
            "sire_id": sire_id, "sire_name": sire_name,
            "dam_id": dam_id, "dam_name": dam_name,
            "damsire_id": damsire_id, "damsire_name": damsire_name,
        }
    return um_map


def parse_sk(path: Path):
    """SK.txt -> list of dicts {horse_id, birth_year, sire_id, dam_id,
    damsire_id}"""
    rows = []
    for b in iter_records(path, SK_RECLEN):
        hid = ascii_field(b, 11, 21)
        if not hid:
            continue
        birth = ascii_field(b, 21, 29)
        birth_year = birth[:4] if birth[:4].isdigit() else None
        ped = b[66:206]
        sire_id = ped[0:10].decode("ascii", errors="replace") or None
        dam_id = ped[10:20].decode("ascii", errors="replace") or None
        damsire_id = ped[40:50].decode("ascii", errors="replace") or None
        rows.append({
            "horse_id": hid,
            "birth_year": birth_year,
            "sire_id": sire_id,
            "dam_id": dam_id,
            "damsire_id": damsire_id,
        })
    return rows


# ---------------------------------------------------------------------
# Build combined blood rows
# ---------------------------------------------------------------------

def build_blood_rows(sk_rows, hn_map, um_map):
    rows = []
    sk_ids = set()

    for r in sk_rows:
        hid = r["horse_id"]
        sk_ids.add(hid)
        sire_id, dam_id, damsire_id = r["sire_id"], r["dam_id"], r["damsire_id"]
        um_self = um_map.get(hid)

        sire_name = hn_map.get(sire_id) if sire_id else None
        if not sire_name and um_self:
            sire_name = um_self.get("sire_name")

        damsire_name = hn_map.get(damsire_id) if damsire_id else None
        if not damsire_name and um_self:
            damsire_name = um_self.get("damsire_name")

        rows.append((hid, sire_id, dam_id, damsire_id, sire_name, damsire_name))

    # Pre-2021 (or any horse SK doesn't cover) -- fall back to UM's own
    # embedded pedigree text (and its ids, since we have them for free).
    for hid, rec in um_map.items():
        if hid in sk_ids:
            continue
        rows.append((
            hid,
            rec.get("sire_id"),
            rec.get("dam_id"),
            rec.get("damsire_id"),
            rec.get("sire_name"),
            rec.get("damsire_name"),
        ))

    return rows, sk_ids


def write_blood_table(rows):
    conn = sqlite3.connect(str(DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute("DROP TABLE IF EXISTS blood")
        cur.execute(
            """
            CREATE TABLE blood (
                horse_id     TEXT PRIMARY KEY,
                sire_id      TEXT,
                dam_id       TEXT,
                damsire_id   TEXT,
                sire_name    TEXT,
                damsire_name TEXT
            )
            """
        )
        cur.executemany(
            "INSERT OR REPLACE INTO blood "
            "(horse_id, sire_id, dam_id, damsire_id, sire_name, damsire_name) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------
# Validation: 30 random SK-covered horses, compare HN-derived sire/damsire
# name against UM's own embedded pedigree for the same horse_id (ground
# truth cross-check), when that horse also has a UM record.
# ---------------------------------------------------------------------

def validate(sk_rows, hn_map, um_map, n=30, seed=42):
    candidates = [r for r in sk_rows if r["horse_id"] in um_map]
    rng = random.Random(seed)
    sample = rng.sample(candidates, min(n, len(candidates)))

    matched = 0
    checked = 0
    details = []
    for r in sample:
        hid = r["horse_id"]
        um_self = um_map[hid]
        sk_sire_name = hn_map.get(r["sire_id"])
        sk_damsire_name = hn_map.get(r["damsire_id"])
        um_sire_name = um_self.get("sire_name")
        um_damsire_name = um_self.get("damsire_name")

        sire_ok = (sk_sire_name is not None and sk_sire_name == um_sire_name)
        damsire_ok = (sk_damsire_name is not None and sk_damsire_name == um_damsire_name)
        checked += 1
        if sire_ok and damsire_ok:
            matched += 1
        details.append((hid, sk_sire_name, um_sire_name, sk_damsire_name, um_damsire_name, sire_ok, damsire_ok))

    return matched, checked, details


# ---------------------------------------------------------------------
# Stats for the report
# ---------------------------------------------------------------------

def report_stats(rows, sk_ids, um_map):
    total = len(rows)
    sire_name_nonnull = sum(1 for r in rows if r[4] is not None)

    year_counts = {}
    year_filled = {}
    for r in rows:
        hid = r[0]
        year = None
        if hid in um_map:
            year = um_map[hid].get("birth_year")
        if year is None and len(hid) >= 4 and hid[:4].isdigit():
            year = hid[:4]
        if year and 2021 <= int(year) <= 2026:
            year_counts[year] = year_counts.get(year, 0) + 1
            if r[4] is not None:
                year_filled[year] = year_filled.get(year, 0) + 1

    print(f"total horse_id rows        : {total}")
    print(f"  from SK (2021+ centric)  : {len(sk_ids)}")
    print(f"  from UM only (pre-2021)  : {total - len(sk_ids)}")
    print(f"sire_name non-NULL         : {sire_name_nonnull} ({sire_name_nonnull/total:.1%})")
    print("2021-2026 birth-year coverage (rows / sire_name filled):")
    for y in sorted(year_counts):
        c = year_counts[y]
        f = year_filled.get(y, 0)
        print(f"  {y}: {c:6d} rows, sire_name filled {f:6d} ({f/c:.1%})")


def main():
    print("Parsing HN.txt ...", file=sys.stderr)
    hn_map = parse_hn(HN_PATH)
    print(f"  HN records: {len(hn_map)}", file=sys.stderr)

    print("Parsing UM.txt (large file, this takes a bit) ...", file=sys.stderr)
    um_map = parse_um(UM_PATH)
    print(f"  UM records: {len(um_map)}", file=sys.stderr)

    print("Parsing SK.txt ...", file=sys.stderr)
    sk_rows = parse_sk(SK_PATH)
    print(f"  SK records: {len(sk_rows)}", file=sys.stderr)

    print("Validating 30 random SK horses against UM ground truth ...", file=sys.stderr)
    matched, checked, details = validate(sk_rows, hn_map, um_map, n=30)
    print(f"  validation: {matched}/{checked} fully matched (sire+damsire name)", file=sys.stderr)
    for d in details:
        print(f"    horse={d[0]} SK/HN.sire={d[1]!r} UM.sire={d[2]!r} match={d[5]} | "
              f"SK/HN.damsire={d[3]!r} UM.damsire={d[4]!r} match={d[6]}", file=sys.stderr)

    print("Building blood rows ...", file=sys.stderr)
    rows, sk_ids = build_blood_rows(sk_rows, hn_map, um_map)
    print(f"  total blood rows: {len(rows)}", file=sys.stderr)

    print("Writing blood table to jvdata.sqlite ...", file=sys.stderr)
    write_blood_table(rows)

    print("\n=== blood table stats ===")
    report_stats(rows, sk_ids, um_map)


if __name__ == "__main__":
    main()
