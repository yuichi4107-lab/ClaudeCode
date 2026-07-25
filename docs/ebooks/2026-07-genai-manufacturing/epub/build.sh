#!/bin/bash
# EPUB ビルドスクリプト
# 必要: pandoc, python3 + Pillow, fonts-noto-cjk
# 使い方: cd docs/ebooks/2026-07-genai-manufacturing && bash epub/build.sh
set -euo pipefail

cd "$(dirname "$0")/.."
mkdir -p build

# 表紙生成
python3 epub/make_cover.py build/cover.jpg

# 扉ページの重複を除去した前付けを生成
# (書名・サブタイトルは pandoc がメタデータから title page を作るため、
#  manuscript/00 の冒頭 H1/H2 を落とし「はじめに」を章タイトルに昇格させる)
sed -e '1,5d' -e 's/^## はじめに/# はじめに/' \
    manuscript/00_front-matter.md > build/00_front-matter.md

pandoc epub/metadata.yaml \
    build/00_front-matter.md \
    manuscript/01_chapter1.md \
    manuscript/02_chapter2.md \
    manuscript/03_chapter3.md \
    manuscript/04_chapter4.md \
    manuscript/05_chapter5.md \
    manuscript/06_chapter6.md \
    manuscript/07_chapter7.md \
    manuscript/08_chapter8.md \
    manuscript/09_back-matter.md \
    -o build/book.epub \
    --toc --toc-depth=1 \
    --split-level=1 \
    --css=epub/epub.css \
    --epub-cover-image=build/cover.jpg \
    --metadata=toc-title:目次

rm build/00_front-matter.md
echo "built: build/book.epub"
