#!/usr/bin/env python3
"""KDP用の表紙画像 (1600x2560 JPG) を生成する。

使い方: python3 make_cover.py [出力パス]
Noto Sans CJK JP (fonts-noto-cjk) が必要。
"""
import sys
from PIL import Image, ImageDraw, ImageFont

W, H = 1600, 2560
NAVY = (18, 38, 66)
NAVY_DARK = (10, 22, 40)
ORANGE = (232, 118, 44)
WHITE = (245, 247, 250)
GRAY = (170, 185, 200)

FONT_TTC = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
FONT_TTC_REG = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"


def jp_font(path, size):
    """ttc から JP フェイスを探して返す"""
    for i in range(10):
        try:
            f = ImageFont.truetype(path, size, index=i)
        except OSError:
            break
        if "JP" in "".join(f.getname()):
            return f
    return ImageFont.truetype(path, size, index=0)


def draw_centered(draw, y, text, font, fill):
    w = draw.textlength(text, font=font)
    draw.text(((W - w) / 2, y), text, font=font, fill=fill)
    return y + font.size


def main(out_path):
    img = Image.new("RGB", (W, H), NAVY)
    d = ImageDraw.Draw(img)

    # 背景: 上下方向のグラデーション
    for y in range(H):
        t = y / H
        c = tuple(int(NAVY[i] + (NAVY_DARK[i] - NAVY[i]) * t) for i in range(3))
        d.line([(0, y), (W, y)], fill=c)

    # 装飾: 歯車モチーフ(同心円+放射) 右上に薄く
    cx, cy, r = W - 180, 420, 340
    for rr in (r, int(r * 0.72), int(r * 0.45)):
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr],
                  outline=(60, 90, 130), width=6)
    import math
    for k in range(12):
        a = k * math.pi / 6
        x1 = cx + int(r * 0.45 * math.cos(a))
        y1 = cy + int(r * 0.45 * math.sin(a))
        x2 = cx + int(r * math.cos(a))
        y2 = cy + int(r * math.sin(a))
        d.line([(x1, y1), (x2, y2)], fill=(60, 90, 130), width=6)

    f_small = jp_font(FONT_TTC, 72)
    f_title1 = jp_font(FONT_TTC, 190)
    f_title2 = jp_font(FONT_TTC, 250)
    f_sub = jp_font(FONT_TTC_REG, 64)
    f_badge = jp_font(FONT_TTC, 58)

    # 上部キャッチ
    draw_centered(d, 260, "人手不足の時代を生き抜く", f_small, GRAY)

    # タイトル
    draw_centered(d, 620, "町工場の", f_title1, WHITE)
    draw_centered(d, 880, "生成AI", f_title2, ORANGE)
    draw_centered(d, 1200, "仕事術", f_title2, WHITE)

    # オレンジの帯 + サブタイトル
    d.rectangle([0, 1660, W, 1900], fill=ORANGE)
    draw_centered(d, 1700, "中小製造業の現場・事務・営業を", f_sub, NAVY_DARK)
    draw_centered(d, 1795, "まるごと効率化する実践ガイド", f_sub, NAVY_DARK)

    # 下部バッジ
    draw_centered(d, 2080, "コピペで使えるプロンプトテンプレート15本収録", f_badge, WHITE)
    draw_centered(d, 2190, "情報漏えい対策ルール・導入90日計画つき", f_badge, GRAY)

    img.save(out_path, "JPEG", quality=92)
    print(f"saved: {out_path} ({W}x{H})")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "cover.jpg")
