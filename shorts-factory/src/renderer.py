"""FFmpeg による動画合成。

画像群 → zoompan(Ken Burns) → xfade連結 → タイトル帯/クレジットoverlay
→ ASS字幕焼き込み → 音声(loudnorm) → final.mp4 (1080x1920, H.264+AAC)

ASSのタイミングは tts_voicevox が実測した各キューの start/end をそのまま使う。
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .config import CONFIG

W = int(CONFIG.get("video", "width", default=1080))
H = int(CONFIG.get("video", "height", default=1920))
FPS = int(CONFIG.get("video", "fps", default=30))
FF = CONFIG.get("ffmpeg", default="ffmpeg")


def _run(cmd: list[str], log_name: str, cwd: Path) -> None:
    log = CONFIG.logs_dir / f"{log_name}.log"
    with open(log, "ab") as lf:
        lf.write(("\n$ " + " ".join(map(str, cmd)) + "\n").encode())
        proc = subprocess.run([str(c) for c in cmd], stdout=lf, stderr=lf, cwd=str(cwd))
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg失敗 rc={proc.returncode}（{log} 参照）")


def _font(size: int, black: bool = True) -> ImageFont.FreeTypeFont:
    name = "NotoSansJP-Black.otf" if black else "NotoSansJP-Bold.otf"
    return ImageFont.truetype(str(CONFIG.fonts_dir / name), size)


# ---------- タイトル帯・クレジットのオーバーレイPNG ----------

def make_overlay(title: str, credit: str, out_path: Path) -> None:
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # タイトルを最大2行に分割
    lines = _split_title(title)
    fsize = 64 if max(len(l) for l in lines) > 11 else 72
    f = _font(fsize)
    line_h = fsize + 18
    pad_x, pad_y = 44, 30
    text_w = max(draw.textbbox((0, 0), l, font=f)[2] for l in lines)
    band_w = min(text_w + pad_x * 2, W - 60)
    band_h = line_h * len(lines) + pad_y * 2 - 10
    bx = (W - band_w) // 2
    by = 110

    # 帯（ダーク半透明 + アクセント下線）
    draw.rounded_rectangle(
        (bx, by, bx + band_w, by + band_h), radius=28, fill=(12, 14, 24, 215)
    )
    draw.rounded_rectangle(
        (bx + 24, by + band_h - 12, bx + band_w - 24, by + band_h - 4),
        radius=4,
        fill=(94, 234, 212, 255),
    )
    ty = by + pad_y - 6
    for l in lines:
        bb = draw.textbbox((0, 0), l, font=f)
        draw.text(((W - (bb[2] - bb[0])) // 2, ty), l, font=f, fill=(255, 255, 255, 255))
        ty += line_h

    # 小タグ
    tag = "毎日AI活用術"
    tf = _font(34, black=False)
    tb = draw.textbbox((0, 0), tag, font=tf)
    tw = tb[2] - tb[0]
    tagx = (W - tw - 48) // 2
    draw.rounded_rectangle((tagx, by - 62, tagx + tw + 48, by - 8), radius=24, fill=(94, 234, 212, 235))
    draw.text((tagx + 24, by - 56), tag, font=tf, fill=(10, 20, 30, 255))

    # クレジット（下部・小さく）
    cf = _font(28, black=False)
    cb = draw.textbbox((0, 0), credit, font=cf)
    draw.text(((W - (cb[2] - cb[0])) // 2, H - 64), credit, font=cf, fill=(255, 255, 255, 175))

    img.save(out_path, "PNG")


def _split_title(title: str) -> list[str]:
    title = title.strip()
    if len(title) <= 13:
        return [title]

    def ok(p: int) -> bool:
        if not (4 <= p <= len(title) - 4):
            return False
        a, b = title[p - 1], title[p]
        # 数字・英字の連なり、数字+助数詞（3分・10秒等）の途中では割らない
        joined = a + b
        if re.match(r"[0-9A-Za-z][0-9A-Za-z]", joined):
            return False
        if re.match(r"[0-9][分秒回個本通日円倍人時]", joined):
            return False
        return True

    center = len(title) // 2
    # 優先: 区切り記号の直後 → 助詞の直後 → 中央付近の割ってよい位置
    candidates = sorted(range(4, len(title) - 3), key=lambda p: abs(p - center))
    for p in candidates:
        if title[p - 1] in "】、。!？?！・ )）" and ok(p):
            return [title[:p], title[p:]]
    for p in candidates:
        if title[p - 1] in "のをがでにはと" and ok(p):
            return [title[:p], title[p:]]
    for p in candidates:
        if ok(p):
            return [title[:p], title[p:]]
    return [title[:center], title[center:]]


# ---------- ASS字幕 ----------

def _ass_time(t: float) -> str:
    h = int(t // 3600)
    m = int(t % 3600 // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def make_ass(cues: list[dict], total_dur: float, out_path: Path) -> None:
    font = CONFIG.get("subtitle", "font", default="Noto Sans JP")
    size = int(CONFIG.get("subtitle", "fontsize", default=76))
    mv = int(CONFIG.get("subtitle", "margin_v", default=600))
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},{size},&H00FFFFFF,&H00FFFFFF,&H00141414,&H96000000,1,0,0,0,100,100,1,0,1,4.5,1.8,2,40,40,{mv},1
Style: Emphasis,{font},{size},&H00FFFFFF,&H00FFFFFF,&H00141414,&H96000000,1,0,0,0,100,100,1,0,1,4.5,1.8,2,40,40,{mv},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for i, c in enumerate(cues):
        start = c["start"]
        end = cues[i + 1]["start"] if i + 1 < len(cues) else min(c["end"] + 0.5, total_dur)
        style = "Emphasis" if c.get("emphasis") else "Default"
        text = "\\N".join(l.replace("{", "｛").replace("}", "｝") for l in c["display"])
        lines.append(
            f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},{style},,0,0,0,,{text}\n"
        )
    out_path.write_text("".join(lines), encoding="utf-8")


# ---------- 背景動画（Ken Burns + xfade） ----------

def render_background(images: list[Path], total_dur: float, work: Path) -> Path:
    xfade = float(CONFIG.get("video", "xfade_sec", default=0.5))
    n = len(images)
    base = (total_dur + 0.4 + xfade * (n - 1)) / n  # xfadeで失われる分を上乗せ

    segs = []
    for i, img_path in enumerate(images):
        # 1.5xに拡大してからzoompan（ジッタ軽減）
        big = work / f"big_{i:02d}.png"
        with Image.open(img_path) as im:
            im.convert("RGB").resize((1620, 2880), Image.LANCZOS).save(big, "PNG")
        frames = int(round((base + xfade) * FPS))
        rate = 0.12
        if i % 2 == 0:
            zexpr = f"1+{rate}*on/{frames}"
        else:
            zexpr = f"1+{rate}-{rate}*on/{frames}"
        seg = work / f"seg_{i:02d}.mp4"
        _run(
            [
                FF, "-y", "-i", big,
                "-vf",
                (
                    f"zoompan=z='{zexpr}':x='(iw-iw/zoom)/2':y='(ih-ih/zoom)/2'"
                    f":d={frames}:fps={FPS}:s={W}x{H},format=yuv420p"
                ),
                "-frames:v", str(frames),
                "-c:v", "libx264", "-crf", "18", "-preset", "fast",
                seg.name,
            ],
            "render",
            work,
        )
        segs.append(seg)
        big.unlink(missing_ok=True)

    if n == 1:
        return segs[0]

    # xfadeチェーン
    inputs: list[str] = []
    for s in segs:
        inputs += ["-i", s.name]
    fc = []
    prev = "[0:v]"
    offset = base
    for i in range(1, n):
        out = f"[v{i}]"
        fc.append(
            f"{prev}[{i}:v]xfade=transition=fade:duration={xfade}:offset={offset:.3f}{out}"
        )
        prev = out
        offset += base
    bg = work / "bg.mp4"
    _run(
        [FF, "-y", *inputs, "-filter_complex", ";".join(fc), "-map", prev,
         "-c:v", "libx264", "-crf", "18", "-preset", "fast", bg.name],
        "render",
        work,
    )
    return bg


# ---------- 最終合成 ----------

def measure_loudnorm(voice_wav: Path, work: Path) -> dict | None:
    """2パスloudnorm用の実測値を取得する。"""
    import json as _json

    proc = subprocess.run(
        [FF, "-i", str(voice_wav), "-af",
         f"loudnorm=I={CONFIG.get('verify', 'lufs_target', default=-14.0)}:TP=-1.5:LRA=11:print_format=json",
         "-f", "null", "-"],
        capture_output=True, text=True, cwd=str(work),
    )
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", proc.stderr, re.DOTALL)
    if not m:
        return None
    try:
        return _json.loads(m.group(0))
    except _json.JSONDecodeError:
        return None


def compose_final(
    bg: Path,
    overlay: Path,
    ass: Path,
    voice_wav: Path,
    total_dur: float,
    work: Path,
    crf: int | None = None,
    measured: dict | None = None,
) -> Path:
    # libassへ渡すパスはcwd相対にして日本語/空白入り絶対パスのエスケープ問題を回避
    fonts_local = work / "fonts"
    if not fonts_local.exists():
        shutil.copytree(CONFIG.fonts_dir, fonts_local)
    lufs = float(CONFIG.get("verify", "lufs_target", default=-14.0))
    crf = crf or int(CONFIG.get("video", "crf", default=23))
    ln = f"loudnorm=I={lufs}:TP=-1.5:LRA=11"
    if measured:
        ln += (
            f":measured_I={measured['input_i']}:measured_TP={measured['input_tp']}"
            f":measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}"
            f":offset={measured.get('target_offset', 0)}:linear=true"
        )
    final = work / "final.mp4"
    _run(
        [
            FF, "-y",
            "-i", bg.name,
            "-i", overlay.name,
            "-i", voice_wav.name,
            "-filter_complex",
            f"[0:v][1:v]overlay=0:0[ov];[ov]ass={ass.name}:fontsdir=fonts[v]",
            "-map", "[v]", "-map", "2:a",
            "-af", ln,
            "-c:v", "libx264", "-crf", str(crf), "-preset", "medium",
            "-pix_fmt", "yuv420p", "-r", str(FPS),
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-movflags", "+faststart",
            "-t", f"{total_dur:.3f}",
            final.name,
        ],
        "render",
        work,
    )
    return final


def extract_previews(final: Path, cues: list[dict], work: Path, n: int = 3) -> list[Path]:
    """字幕表示中のフレームを抽出（人間の目視確認用）。"""
    picks = [cues[int(len(cues) * r)] for r in (0.15, 0.5, 0.85)][:n]
    outs = []
    for i, c in enumerate(picks):
        t = (c["start"] + c["end"]) / 2
        p = work / f"preview_{i}.jpg"
        _run([FF, "-y", "-ss", f"{t:.2f}", "-i", final.name, "-frames:v", "1", "-q:v", "3", p.name],
             "render", work)
        outs.append(p)
    return outs
