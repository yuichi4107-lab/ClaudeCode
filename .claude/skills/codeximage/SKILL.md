---
name: codeximage
description: "Process Codex image-generation handoff jobs placed in `.company/codex/queue/`. Use when the user asks to run or check a Codex image job, generate manga/page/cover images without an API key, process queue contents with Codex/ChatGPT image generation, save outputs to `.company/codex/done/job_id/`, archive the original queue folder to `.company/codex/archive/job_id_input/`, and empty the queue afterward. This is the batch/queue-based execution path for ChatGPT Images 2.0 / gpt-image-2 jobs (same underlying constraint as the openai-image-gen guardrail: no OpenAI Images API, no API keys). For a single ad-hoc image (no queue folder), use openai-image-gen's manual ChatGPT Pro Web flow instead. For Gemini/NanoBanana2 API-based generation, use nanobanana2-image-gen instead."
---

# Codex Image Queue

## Workflow

Use this skill for the recurring queue-based image generation handoff.

1. Confirm date with a tool, then read project context in this order:
   - `HANDOFF.md` if present
   - latest TODO history under `.company/secretary/todos/`
   - `.company/codex/queue/`
2. Inspect `.company/codex/queue/`.
   - Ignore `desktop.ini`.
   - If multiple job folders exist, process each folder separately.
   - Read `TASK.md`, `START_HERE.md`, `manifest.json`, CSV files, and relevant reference images.
3. Define the job requirements briefly before execution:
   - goal
   - scope
   - output paths
   - completion checklist
   - quality checks
4. Generate images without using API keys.
   - Use ChatGPT Pro Web / ChatGPT Images 2.0 / `gpt-image-2` through the Codex/ChatGPT-side image generation path, not `gen_manga_bundle.py` API execution or any OpenAI Images API route.
   - Do not substitute local procedural/Pillow/placeholder art for requested final images. If `gpt-image-2` generation cannot be completed, mark the job `partial` or `failed` and keep prompts/manifests for retry.
   - Extract prompts from `manifest.json` or CSV.
   - When reference images are present, view them and summarize their visual traits into the generation prompt.
   - Preserve page IDs and output filenames from the manifest.
5. Save outputs to:
   - `.company/codex/done/job_id/`
   - pages under `.company/codex/done/<job_id>/pages/`
   - cover as `.company/codex/done/<job_id>/cover.png`
6. Create or update these files in the done folder:
   - `progress.json`
   - `report.md`
   - `DONE.txt`
7. Archive the original input folder after outputs are verified:
   - move or copy `.company/codex/queue/<job_id>/` to `.company/codex/archive/job_id_input/`
   - keep the generated outputs in `done`, not only in `archive`
8. Empty `.company/codex/queue/` after confirming:
   - required outputs exist in `done`
   - original input exists in `archive/<job_id>_input/`
   - queue cleanup is approved when it involves deleting local files

## Output Rules

For a manga bundle job, use this done structure:

```text
.company/codex/done/<job_id>/
|-- pages/
|   |-- page_002.png
|   |-- page_003.png
|   `-- ...
|-- cover.png
|-- progress.json
|-- report.md
`-- DONE.txt
```

`progress.json` should include:

```json
{
  "job_id": "<job_id>",
  "status": "success|partial|failed",
  "generation_mode": "chatgpt_plus_image_generation_manual_codex",
  "generated_pages": [],
  "cover_generated": true,
  "needs_manual_review_pages": [],
  "note": "Automated API OCR/Vision QC was not run; manual review recommended."
}
```

Mark `needs_manual_review_pages` for pages containing Japanese text unless OCR or manual review confirms accuracy.

## Quality Checks

Before reporting completion, verify:

- all expected PNGs exist in `done`
- filenames match the manifest
- cover and page images are not swapped
- `progress.json`, `report.md`, and `DONE.txt` exist
- the original queue folder has been archived to `archive/<job_id>_input/`
- `queue` is empty, except it may briefly contain system files such as `desktop.ini` before cleanup

If generated Japanese text is visibly wrong, report it clearly and regenerate that page if practical.

## Safety

- Do not use, print, request, or store API keys for this workflow.
- Do not delete queue contents until outputs and archive are verified.
- Deleting local files requires explicit user confirmation at action time.
- Leave original generated image files in Codex's generated image cache; copy them into `done` instead of moving them.
