---
name: openai-image-gen
description: Deprecated guardrail for image generation. Use when a task requests ChatGPT Images / gpt-image-2 / OpenAI-family image generation, or when another workflow is about to call the OpenAI Images API directly. Do not use OpenAI Images API, API keys, SDK calls, or local Pillow/procedural substitutes. For ChatGPT/OpenAI-family image requests, prepare prompts and generate only through ChatGPT Pro Web / ChatGPT Images 2.0 / gpt-image-2 (manually, or via the codeximage queue handoff for batch jobs), then save and verify the returned images. If the user explicitly asks for Gemini/NanoBanana2 generation instead, use the nanobanana2-image-gen skill (API-key based, separate workflow) rather than this guardrail.
---

# OpenAI Image Gen Guardrail

## Current Rule

This skill name is kept for compatibility, but the old API workflow is disabled.

For image generation that asks for ChatGPT Images, gpt-image-2, gpt-image2.0, OpenAI-family image generation, KDP art, note art, manga pages, or cover art:

- Use ChatGPT Pro Web / ChatGPT Images 2.0 / `gpt-image-2`.
- Do not use OpenAI Images API, API keys, SDK calls, `client.images.generate`, `client.images.edit`, or paid API fallback.
- Do not generate final deliverables with local procedural drawing, Pillow-generated art, or placeholder cards.
- Do not silently switch to Gemini, NanoBanana, or another image engine. If the user explicitly requests a Gemini/NanoBanana workflow, use that workflow separately.
- If ChatGPT Pro Web generation cannot be completed in the current run, preserve prompts and references and mark the image stage `pending_gpt_image2_web` or `blocked_gpt_image2_web`. Do not pretend final art exists.

## Workflow

1. Confirm the task asks for image generation and identify:
   - requested count
   - aspect ratio / size
   - output folder and filenames
   - reference images
   - style constraints
   - quality checks
2. Prepare one prompt per output. Keep prompts self-contained and include required filename/page id.
3. Use ChatGPT Pro Web / ChatGPT Images 2.0 / `gpt-image-2` to generate the images.
4. Save the returned image files to the requested output folder.
5. Verify:
   - file exists
   - count and filenames match the manifest
   - visual style matches the request
   - no placeholder/Pillow/procedural final art was substituted
6. Write a short report with status:
   - `completed_gpt_image2_web`
   - `partial_gpt_image2_web`
   - `pending_gpt_image2_web`
   - `blocked_gpt_image2_web`

## gpt-image-2 仕様リファレンス（ChatGPT Web手動生成時の参考）

APIは使わないが、gpt-image-2 のネイティブ仕様はWeb経由の生成・プロンプト設計時にも変わらないため参考として残す。

### 対応サイズ

| 値 | ピクセル | 用途例 |
|----|---------|--------|
| `1024x1024` | 1024×1024 | SNSアイコン、正方形素材 |
| `1024x1536` | 1024×1536 | マンガコマ、書籍カバー、縦長（デフォルト） |
| `1536x1024` | 1536×1024 | 横長バナー、YouTubeサムネイル |
| `auto` | モデル任せ | 判断を OpenAI に委ねる |

※ NanoBanana2 のような `9:16` や `4:5` 等の任意アスペクト比は非対応（4種のネイティブサイズのみ）。

### 対応画質（API時代の料金目安: 1024x1536 1枚あたり）

| 値 | 料金目安 | 用途例 |
|----|----------|--------|
| `low` | $0.016 | テスト、ラフ、大量生成 |
| `medium` | $0.063 | 通常用途（デフォルト） |
| `high` | $0.21 | 最終版、印刷物 |
| `auto` | 不定 | OpenAI任せ |

※ 料金はAPI直叩き時の目安（現在は禁止）。ChatGPT Pro Web経由ではサブスクリプション内で生成される。

## Prompt Package Fallback

When direct ChatGPT Pro Web generation is unavailable, create a prompt package instead of calling an API:

```text
<output-folder>/
|-- image_prompts.md
|-- manifest.json
`-- report.md
```

The report must state that final images are not generated yet.

## Hard Stops

Stop before execution if a plan requires:

- OpenAI Images API or any API-key based OpenAI image call
- installing or importing the OpenAI SDK for image generation
- running scripts that call image APIs
- using Pillow/procedural/local generated art as final requested images
- marking a KDP/note/manga image deliverable complete without real ChatGPT Pro Web `gpt-image-2` outputs
