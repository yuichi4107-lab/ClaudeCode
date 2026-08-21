---
name: picture-book-kdp
description: Create and revise Amazon KDP children's picture books / 絵本 from concept through 32-page manuscript, gender-neutral page planning, illustration prompts, page previews, fixed-layout Kindle EPUB, paperback / ペーパーバック interior and cover PDFs, KDP metadata, optional generic LP/QR CTA, and quality reports. Use when the user asks to make, continue, package, revise, publish, or standardize a KDP picture book, 絵本, or personalized picture-book sales funnel.
---

# Picture Book KDP Production

Use this skill for YNFactory children's picture-book projects intended for Amazon KDP and optional personalized-order upsells.

## Start

1. Confirm the current date with a tool.
2. In `YNFactory-cc`, read `.company/secretary/HANDOFF.md` and the latest file under `.company/secretary/todos/` before project exploration.
3. If the user did not specify the project folder, create or use:
   - `.company/outputs/picture-books/<YYYY-MM-DD>-<slug>/`
   - Use the tool-confirmed creation date in Asia/Tokyo. Example: `.company/outputs/picture-books/2026-06-13-kaigara-no-chiisana-koe/`.
   - Do not rename older pre-date folders unless the user explicitly asks.
4. Define the work briefly before execution:
   - goal
   - scope
   - output paths
   - completion checklist
   - quality checks
5. If KDP print dimensions, page-count rules, barcodes, or cover requirements matter, verify current official KDP help pages before finalizing dimensions.

## Default Product Strategy

Build the KDP book as a satisfying generic product. Use the end matter to lead readers to a separate personalized product.

- KDP book: generic, complete, sellable by itself.
- Personalized product: sold separately as data delivery, not as per-order KDP customization.
- CTA: "世界で1つだけの絵本を作りませんか？"
- LP: generic service LP that can serve multiple picture books, not a single-book-only LP.
- Default brand:
  - author display name: `Yuichi`
  - publisher: `YN出版`
  - operator: `YNファクトリー`
  - operator URL: `https://www.ynfactory.online/`
  - contact email: `y-nakada@yn-factory.com`

## Startup Inputs

Use sensible defaults when the user wants speed. Ask only for missing inputs that materially change the book.

- title and theme
- target child age, default `3〜5歳`
- buyer, default `parents, grandparents, gift buyers`
- page count, default `32`
- trim size, default `8.25 x 8.25 inch`
- print type, default `full color / premium color paperback`
- personalization hooks: child name, favorite things, family members, memory, message, occasion
- LP URL for QR, default from `KDP出版用/QR_LP_URL.txt` if present

## 32-Page Structure

Default structure:

- P01: title page
- P02: dedication/copyright or quiet opening
- P03-P30: picture-book story
- P31: parent/grandparent reading note
- P32: CTA and book introduction

Rules:

- Separate the story and end matter clearly.
- P31 should be labeled for adults, e.g. `保護者の方へ`.
- P32 should be labeled as a special-version guide and/or book information.
- Use `書籍紹介` as the reader-facing label for colophon-like information. Avoid `奥付` as a visible heading unless the user explicitly asks.
- Do not include `制作協力` unless the user explicitly asks.
- Keep the generic edition gender-neutral unless the user specifies otherwise.
- Avoid awkward second-person phrasing such as forced `きみ`; prefer natural neutral narration and prompts.

## Manuscript Outputs

Create or update:

```text
project.md
manuscript/story_text.md
manuscript/page_plan.md
manuscript/layout_notes.md
manuscript/page_image_prompts.md
manuscript/character_defs.json
PIPELINE_REPORT.md
QUALITY_REPORT.md
progress.json
```

Because final picture-book artifacts are large and are not committed to
GitHub, mirror the completed project folder to the Google Drive copy of
`YNFactory-cc` using the same relative path. For example, after creating
`.company/outputs/picture-books/<YYYY-MM-DD>-<slug>/` in the local working
copy, also copy it to the Drive-side
`YNFactory-cc/.company/outputs/picture-books/<YYYY-MM-DD>-<slug>/`. Treat this
as artifact storage only; do not use the Drive folder as the Git worktree or
execution cwd.

Story-writing guidance:

- Keep child-facing pages short and read-aloud friendly.
- Make each page one emotional beat.
- Use concrete, gentle images that parents and grandparents can understand quickly.
- Build personalization hooks into the plan without exposing placeholder weirdness in the generic edition.
- For P32, include CTA, QR prompt, and book introduction, for example:
  - title
  - subtitle
  - author as `著者: Yuichi` unless the user explicitly specifies a different author name
  - publisher
  - operator
  - contact email

## Image and Layout Workflow

Create page images and preview pages in a stable square format.

Default execution is end-to-end. Do not split a normal daily/new-book run into
separate manuscript, image-generation, layout, and upload-prep phases when the
available tools can continue. In the same run, proceed through final
ChatGPT/Codex-side image generation, image integration, text-overlay pages,
layout previews, fixed-layout Kindle EPUB, paperback interior PDF, paperback
cover PDF, KDP metadata, the four official `UPLOAD_` files, and verification.
Only stop at `pending` or `blocked` when the image-generation/build tools are
actually unavailable or repeatedly failing; preserve prompts/manifests and state
the blocker clearly.

Recommended project paths:

```text
images/pages/page_001.png
images/pages/page_001.jpg
layout/preview_pages/page_001.jpg
layout/contact_preview_025_032.jpg
layout/fixed_layout_source/
KDP出版用/
```

Default raster geometry:

- page canvas: `2475 x 2475 px`
- print intent: `8.25 x 8.25 inch` at 300dpi
- keep text inside safe margins
- avoid text overlap and button/text overflow
- for the final back matter, inspect P31 and P32 visually
- For this workflow, use a square cover image for Kindle/eBook cover handling in `KDP出版用/`; do not place a vertical eBook cover candidate in `KDP出版用/`.

Image generation rules:

- Default final art generation should use ChatGPT Pro Web / ChatGPT Images 2.0 / `gpt-image-2` through the ChatGPT/Codex-side image generation path.
- Do not treat local procedural/Pillow placeholder art as final KDP art.
- Do not create `KDP出版用/UPLOAD_` EPUB/PDF/cover files from local procedural/Pillow placeholder art. If final `gpt-image-2` art is not integrated yet, keep draft EPUB/PDF/cover files under `_not_for_upload/` or prefix them with `PREVIEW_`, and mark `progress.json` as `pending_gpt_image2_final_art` or `blocked_gpt_image2_final_art`.
- A project is not `completed_ready_for_owner_preview` until all 32 final page images, and the final cover when applicable, are generated with ChatGPT Pro Web / ChatGPT Images 2.0 / `gpt-image-2` and integrated into the build.
- Do not switch to OpenAI API / `openai-image-gen` for picture-book final art.
- If the environment cannot complete ChatGPT `gpt-image-2` generation in the current run, preserve the full prompt/manifest package and mark the image stage as blocked or pending instead of pretending final art was generated.
- If generating images through Codex/ChatGPT in a queued workflow, use the local `codeximage` workflow and keep the original page IDs and filenames.

## Kindle Fixed-Layout EPUB

Build the Kindle edition as 32 single pages, not as forced spreads.

Required checks:

- XHTML pages: `32`
- image pages: `32`
- image size: `2475 x 2475`
- OPF has `rendition:layout` = `pre-paginated`
- OPF has `rendition:orientation` = `portrait`
- OPF has `rendition:spread` = `none`
- each spine item has `page-spread-center`
- each XHTML page has viewport `width=2475,height=2475`
- `zipfile.testzip()` returns `None`

If Kindle Previewer shows two page turns as one page, rebuild the EPUB with `rendition:spread=none` and `page-spread-center` on all pages.

## Paperback PDFs

KDP paperback needs two upload files:

- interior PDF
- wraparound cover PDF containing back cover + spine + front cover

Use clear upload filenames in `KDP出版用/` so the owner can identify exactly what to upload:

```text
UPLOAD_01_Kindle電子書籍_EPUB_<slug>.epub
UPLOAD_02_Kindle電子書籍_表紙_正方形_<slug>.jpg
UPLOAD_03_ペーパーバック_本文PDF_<slug>.pdf
UPLOAD_04_ペーパーバック_表紙PDF_<slug>.pdf
README_アップロード対象.md
```

Only files beginning with `UPLOAD_` are upload candidates. Put drafts, previews, old names, and non-upload helper files under `_not_for_upload/` or name them with `INFO_` / `PREVIEW_` prefixes.

Important: although KDP's public eBook marketing-cover guidance recommends a vertical 1,600 x 2,560 px cover, this project workflow intentionally keeps only the square cover candidate in `KDP出版用/` unless the user asks to restore a vertical marketing cover.

Default trim and print assumptions:

- trim: `8.25 x 8.25 inch`
- full color, premium color
- page count: `32`
- bleed: `0.125 inch`

Interior PDF with bleed:

```text
trim: 8.25 x 8.25 inch
PDF page size: 8.375 x 8.5 inch
PDF page size: 212.72 x 215.90 mm
PDF page size: 603 x 612 pt
```

Cover PDF for 32-page premium color paperback:

```text
spine width = 32 pages x 0.002347 inch = 0.075104 inch = 1.91 mm
cover width = 0.125 + 8.25 + spine + 8.25 + 0.125 = 16.825104 inch
cover height = 0.125 + 8.25 + 0.125 = 8.5 inch
PDF page size = 1211.41 x 612 pt
```

Cover rules:

- no spine text for short books; KDP requires enough pages for spine text, and 32 pages is too short
- do not draw a visible barcode frame, white box, border, or placeholder text such as `Barcode space` on the paperback cover PDF; keep any needed barcode placement room as natural background space instead
- keep important text at least `0.25 inch` away from trim/edge areas
- front cover must visibly include the registered Japanese title, registered Japanese subtitle, and author name. The default author name is exactly `Yuichi`. Title should be the main heading, subtitle should be smaller and visually distinct, and author name should be readable inside the safe area.
- back cover should include the generic personalized-picture-book CTA and QR code inside a back-cover information frame or equivalent readable area, while keeping the lower-right barcode area naturally quiet for KDP's automatic barcode. Do not place the CTA QR over the KDP barcode area.
- keep cover PDF under KDP's practical recommended size where possible
- write a `KDP出版用/paperback_size_spec.md` with the final settings and calculations

If page count, paper type, or trim size changes, recalculate the spine and cover dimensions before exporting.

## LP and QR CTA

When the book includes a personalized upsell:

1. Store the QR destination in `KDP出版用/QR_LP_URL.txt`.
2. Generate `KDP出版用/qr_lp.png`.
3. Put the QR on P32, not in the KDP product description.
   - Place the CTA QR code inside the same visible `書籍紹介` / book-introduction frame as the P32 CTA text, not floating outside that frame.
   - Place the QR immediately below the book-introduction / CTA text by default, so the reader sees the CTA sentence and QR as one connected block.
   - Size the P32 `書籍紹介` frame to wrap the CTA text and QR with comfortable margins; avoid a page-sized frame with large unused blank space.
   - Also place the same CTA and QR on the paperback back cover, inside the back-cover information frame, away from the lower-right KDP barcode area.
4. If creating an LP, put it under `lp/ehon/` unless the user specifies another path.
5. Make the LP generic:
   - no single-book-only dependence
   - no duplicate of the book's P32 CTA image inside the LP
   - clear privacy handling for photos and personal information
   - FAQ includes revision policy when requested; default revision answer can be `2回まで。ただし修正により納品時期が遅れることがあります。`
6. If publishing the LP to GitHub Pages, verify:
   - public URL returns HTTP 200
   - HTML no longer references deleted assets
   - QR URL matches the public URL

## KDP Metadata

Create/update in `KDP出版用/`:

```text
書籍情報.md
ジャンル・キーワード.md
書籍紹介文_HTML.html
```

`書籍情報.md` must include title and subtitle readings:

- Use katakana for all Japanese furigana fields.
- Output both furigana and romanized text for the title.
- Output both furigana and romanized text for the subtitle.

Metadata must avoid direct external URL/order-form promotion in the KDP description. Keep personalized-order promotion in the book's end matter and LP.

`ジャンル・キーワード.md` must include keyword candidates in a `3×7` table: 3 rows or sets, 7 keyword candidates per row, 21 keyword candidates total.

Default author metadata:

- `KDP出版用/書籍情報.md`: `著者: Yuichi`
- `project.md`: `著者: Yuichi`
- P32 book-introduction page: `著者: Yuichi`
- Kindle square cover and paperback front cover: visible author name `Yuichi`

Remember to tell the user that AI-generated content must be declared in KDP if AI-generated images/text were used.

## Quality Loop

Before completion, verify and report:

- required files exist
- P31/P32 visually inspected
- PDF page counts and dimensions via `pdfinfo`
- EPUB zip test and fixed-layout metadata
- paperback front cover includes exact registered title, exact registered subtitle, and author name `Yuichi`
- paperback back cover includes CTA text and QR code, without drawing a barcode box or occupying the lower-right automatic barcode area
- `ジャンル・キーワード.md` has a `3×7` keyword table
- QR URL and public LP status when applicable
- Drive mirror exists at the same relative path for generated artifacts that are ignored by GitHub
- no missing local or public image assets
- `PIPELINE_REPORT.md`, `QUALITY_REPORT.md`, and `progress.json` updated

Use concise quality scoring in `QUALITY_REPORT.md`; pass threshold is `85/100`.

## Final Response

Summarize:

- what was created or changed
- exact upload files for KDP
- trim/cover dimensions
- validation results
- remaining manual check: open in Kindle Previewer/KDP Previewer before publishing
