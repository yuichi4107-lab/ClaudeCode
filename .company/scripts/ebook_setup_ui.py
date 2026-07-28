#!/usr/bin/env python3
"""Local click-choice setup UI for ebook projects.

This is a small localhost-only form used when Codex's built-in selectable
question UI is unavailable in the current collaboration mode.
"""

from __future__ import annotations

import argparse
import json
import re
import socket
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = ROOT / ".company" / "outputs" / "ebook-setup-inputs"
JST = ZoneInfo("Asia/Tokyo")


QUESTIONS = [
    {
        "id": "theme_handling",
        "title": "テーマの扱い",
        "options": [
            {
                "value": "use_input",
                "label": "テーマ中心",
                "description": "入力されたテーマを中心に据えて、広げすぎずに整理します。",
                "recommended": True,
            },
            {
                "value": "expand",
                "label": "少し広げる",
                "description": "周辺テーマ、歴史、社会的背景、関連する議論まで含めます。",
            },
            {
                "value": "narrow",
                "label": "絞り込む",
                "description": "健康、美容、検証など特定の切り口に寄せます。",
            },
        ],
    },
    {
        "id": "target_reader",
        "title": "想定読者",
        "options": [
            {
                "value": "beginner",
                "label": "初心者",
                "description": "初めて知る人にもわかる、やさしい導入にします。",
                "recommended": True,
            },
            {
                "value": "health_interest",
                "label": "健康関心層",
                "description": "自然療法や身体への関心がある読者向けにします。",
            },
            {
                "value": "verification",
                "label": "検証派",
                "description": "真偽や根拠の強さを冷静に見たい読者向けにします。",
            },
        ],
    },
    {
        "id": "book_type",
        "title": "本の型",
        "options": [
            {
                "value": "intro",
                "label": "やさしい入門書",
                "description": "全体像、歴史、主張、注意点を順番に整理します。",
                "recommended": True,
            },
            {
                "value": "verification",
                "label": "検証型",
                "description": "肯定・否定の主張を並べ、根拠の強さを評価します。",
            },
            {
                "value": "case_story",
                "label": "事例中心",
                "description": "ケースや体験談を読み物として配置します。",
            },
        ],
    },
    {
        "id": "tone",
        "title": "文体",
        "options": [
            {
                "value": "gentle",
                "label": "やさしい",
                "description": "です・ます調で、専門用語をかみ砕きます。",
                "recommended": True,
            },
            {
                "value": "calm_expert",
                "label": "落ち着いた専門書風",
                "description": "少し硬めに、信頼感を優先して書きます。",
            },
            {
                "value": "conversational",
                "label": "会話調",
                "description": "読みやすさと親しみやすさを優先します。",
            },
        ],
    },
    {
        "id": "length",
        "title": "文字量",
        "options": [
            {
                "value": "50000",
                "label": "約50,000字",
                "description": "標準的な電子書籍として、深さと制作速度のバランスを取ります。",
                "recommended": True,
            },
            {
                "value": "25000",
                "label": "約25,000字",
                "description": "短めにまとめ、早く出版できる形にします。",
            },
            {
                "value": "100000",
                "label": "約100,000字",
                "description": "本格的に掘り下げる長編にします。",
            },
        ],
    },
    {
        "id": "image_density",
        "title": "画像密度",
        "options": [
            {
                "value": "diagram_rich",
                "label": "図解多め",
                "description": "仕組み、比較、注意点を図解で理解しやすくします。",
                "recommended": True,
            },
            {
                "value": "standard",
                "label": "標準",
                "description": "章ごとに数点、本文を邪魔しない程度に入れます。",
            },
            {
                "value": "few",
                "label": "少なめ",
                "description": "文字中心で、必要な箇所だけ画像を入れます。",
            },
        ],
    },
]


def slugify(text: str) -> str:
    text = text.strip().lower()
    if not text:
        return "ebook"
    ascii_text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    if ascii_text:
        return ascii_text[:60]
    return "ebook-setup"


def pick_port(host: str, preferred: int) -> int:
    for port in range(preferred, preferred + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host, port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"ポート {preferred}〜{preferred + 49} に空きがありません。ほかのアプリを終了してから、もう一度お試しください。")


def html_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def render_page(theme: str, mode: str) -> bytes:
    questions_json = json.dumps(QUESTIONS, ensure_ascii=False)
    theme_json = json.dumps(theme, ensure_ascii=False)
    mode_json = json.dumps(mode, ensure_ascii=False)
    safe_theme = html_escape(theme)
    safe_mode = html_escape(mode)
    html = f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>電子書籍 初回設定</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #17202a;
      --muted: #5b6472;
      --line: #d9dee7;
      --paper: #fbfcfe;
      --panel: #ffffff;
      --accent: #0f766e;
      --accent-soft: #e6f3f1;
      --warn: #9a5b13;
      --blue: #1d4ed8;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Hiragino Sans", "Yu Gothic", sans-serif;
      background: var(--paper);
      color: var(--ink);
      line-height: 1.6;
    }}
    main {{
      width: min(1120px, calc(100vw - 32px));
      margin: 0 auto;
      padding: 28px 0 44px;
    }}
    header {{
      display: grid;
      gap: 8px;
      padding: 18px 0 22px;
      border-bottom: 1px solid var(--line);
    }}
    h1 {{
      margin: 0;
      font-size: clamp(24px, 3vw, 36px);
      letter-spacing: 0;
    }}
    .meta, .note {{
      color: var(--muted);
      font-size: 14px;
    }}
    .note {{
      padding: 12px 14px;
      background: #fff7ed;
      border: 1px solid #fed7aa;
      color: var(--warn);
      border-radius: 8px;
      margin-top: 8px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 18px;
      margin-top: 22px;
    }}
    fieldset {{
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      padding: 16px;
      margin: 0;
    }}
    legend {{
      font-weight: 700;
      padding: 0 6px;
    }}
    .choices {{
      display: grid;
      gap: 10px;
      margin-top: 10px;
    }}
    .choice {{
      display: grid;
      grid-template-columns: 22px 1fr;
      gap: 10px;
      align-items: start;
      min-height: 76px;
      padding: 12px;
      border: 1px solid var(--line);
      border-radius: 8px;
      cursor: pointer;
      background: #fff;
    }}
    .choice:hover {{
      border-color: #9fb6c5;
      background: #f8fbfc;
    }}
    .choice:has(input:checked) {{
      border-color: var(--accent);
      background: var(--accent-soft);
      box-shadow: inset 0 0 0 1px var(--accent);
    }}
    input[type="radio"] {{
      width: 18px;
      height: 18px;
      margin-top: 3px;
      accent-color: var(--accent);
    }}
    .choice-title {{
      font-weight: 700;
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
    }}
    .badge {{
      font-size: 12px;
      color: var(--blue);
      border: 1px solid #bfdbfe;
      background: #eff6ff;
      border-radius: 999px;
      padding: 1px 8px;
      font-weight: 600;
    }}
    .desc {{
      color: var(--muted);
      font-size: 13px;
      margin-top: 3px;
    }}
    .free {{
      margin-top: 18px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      padding: 16px;
    }}
    textarea {{
      width: 100%;
      min-height: 118px;
      resize: vertical;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      font: inherit;
    }}
    .actions {{
      display: flex;
      align-items: center;
      gap: 12px;
      margin-top: 18px;
      flex-wrap: wrap;
    }}
    button {{
      border: 0;
      border-radius: 8px;
      background: var(--accent);
      color: #fff;
      padding: 12px 18px;
      font-weight: 700;
      font-size: 15px;
      cursor: pointer;
    }}
    button:hover {{ filter: brightness(0.96); }}
    #status {{
      color: var(--muted);
      font-size: 14px;
    }}
    .saved {{
      margin-top: 16px;
      padding: 14px;
      border: 1px solid #bbf7d0;
      background: #f0fdf4;
      color: #166534;
      border-radius: 8px;
      display: none;
      word-break: break-all;
    }}
    @media (max-width: 780px) {{
      .grid {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>電子書籍 初回設定</h1>
      <div class="meta">テーマ: <strong>{safe_theme}</strong> / モード: {safe_mode}</div>
      <div class="note">健康・医療に関わる表現は、効果を断定せず、根拠の強さと未検証部分を分けて扱います。</div>
    </header>

    <form id="setup-form">
      <section id="questions" class="grid"></section>

      <section class="free">
        <label for="free_text"><strong>自由記述</strong></label>
        <p class="meta">入れたい論点、避けたい表現、タイトル案、著者名などがあれば書いてください。</p>
        <textarea id="free_text" name="free_text" placeholder="例: 医療効果は断定せず、読み物として面白く。歴史と科学的検証を分けてほしい。"></textarea>
      </section>

      <div class="actions">
        <button type="submit">この内容を保存</button>
        <span id="status">選択後、保存ボタンを押してください。</span>
      </div>
      <div id="saved" class="saved"></div>
    </form>
  </main>

  <script>
    const questions = {questions_json};
    const container = document.getElementById("questions");

    function render() {{
      container.innerHTML = questions.map((q) => `
        <fieldset>
          <legend>${{q.title}}</legend>
          <div class="choices">
            ${{q.options.map((opt, index) => `
              <label class="choice">
                <input type="radio" name="${{q.id}}" value="${{opt.value}}" ${{opt.recommended ? "checked" : ""}}>
                <span>
                  <span class="choice-title">
                    ${{opt.label}}
                    ${{opt.recommended ? '<span class="badge">おすすめ</span>' : ""}}
                  </span>
                  <span class="desc">${{opt.description}}</span>
                </span>
              </label>
            `).join("")}}
          </div>
        </fieldset>
      `).join("");
    }}

    function selectedLabel(question, value) {{
      const opt = question.options.find((item) => item.value === value);
      return opt ? opt.label : value;
    }}

    document.getElementById("setup-form").addEventListener("submit", async (event) => {{
      event.preventDefault();
      const answers = {{}};
      for (const question of questions) {{
        const selected = document.querySelector(`input[name="${{question.id}}"]:checked`);
        if (!selected) {{
          document.getElementById("status").textContent = `${{question.title}}を選択してください。`;
          return;
        }}
        answers[question.id] = {{
          value: selected.value,
          label: selectedLabel(question, selected.value),
        }};
      }}
      const payload = {{
        theme: {theme_json},
        mode: {mode_json},
        answers,
        free_text: document.getElementById("free_text").value.trim(),
        safety_policy: "健康・医療効果は断定せず、根拠の強さと未検証部分を分けて表現する",
      }};
      document.getElementById("status").textContent = "保存中です...";
      const response = await fetch("/submit", {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify(payload),
      }});
      const result = await response.json();
      if (!response.ok) {{
        document.getElementById("status").textContent = result.error || "保存できませんでした。";
        return;
      }}
      document.getElementById("status").textContent = "保存しました。";
      const saved = document.getElementById("saved");
      saved.style.display = "block";
      saved.textContent = `保存先: ${{result.path}}`;
    }});

    render();
  </script>
</body>
</html>
"""
    return html.encode("utf-8")


class SetupHandler(BaseHTTPRequestHandler):
    server_version = "EbookSetupUI/1.0"

    def log_message(self, fmt: str, *args: object) -> None:
        return

    @property
    def app(self) -> "SetupServer":
        return self.server  # type: ignore[return-value]

    def send_json(self, status: HTTPStatus, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            params = parse_qs(parsed.query)
            theme = params.get("theme", [self.app.theme])[0] or self.app.theme
            mode = params.get("mode", [self.app.mode])[0] or self.app.mode
            body = render_page(theme=theme, mode=mode)
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/latest":
            if self.app.latest_path and self.app.latest_path.exists():
                self.send_json(
                    HTTPStatus.OK,
                    {
                        "path": str(self.app.latest_path),
                        "data": json.loads(self.app.latest_path.read_text(encoding="utf-8")),
                    },
                )
                return
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "まだ保存済みの初回設定がありません。フォームで選択して保存してください。"})
            return
        self.send_json(HTTPStatus.NOT_FOUND, {"error": "指定されたページは見つかりません。"})

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/submit":
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "指定されたページは見つかりません。"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "入力データの形式が正しくありません。画面を再読み込みしてから、もう一度保存してください。"})
            return

        now = datetime.now(JST)
        theme = str(payload.get("theme") or self.app.theme)
        payload["created_at"] = now.isoformat()
        payload["source"] = "local_ebook_setup_ui"

        out_dir = self.app.output_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{now.strftime('%Y%m%d-%H%M%S')}-{slugify(theme)}-setup.json"
        out_path = out_dir / filename
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        latest_path = out_dir / "latest.json"
        latest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.app.latest_path = latest_path

        self.send_json(HTTPStatus.OK, {"ok": True, "path": str(out_path)})


class SetupServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], theme: str, mode: str, output_dir: Path):
        super().__init__(server_address, SetupHandler)
        self.theme = theme
        self.mode = mode
        self.output_dir = output_dir
        self.latest_path: Path | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="電子書籍制作の初回設定を選ぶローカル画面を起動します。")
    parser.add_argument("--theme", default="ソマチッド", help="初回設定画面に表示するテーマです。")
    parser.add_argument("--mode", default="theme-to-ebook", help="制作フローの表示名です。")
    parser.add_argument("--host", default="127.0.0.1", help="待受先ホスト（既定: 127.0.0.1）")
    parser.add_argument("--port", type=int, default=8765, help="優先して使うポート番号（既定: 8765）")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="設定JSONの保存先ディレクトリです。",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    port = pick_port(args.host, args.port)
    server = SetupServer((args.host, port), theme=args.theme, mode=args.mode, output_dir=args.output_dir)
    query = urlencode({"theme": args.theme, "mode": args.mode})
    url = f"http://{args.host}:{port}/?{query}"
    print(f"ebook_setup_ui_url={url}", flush=True)
    print(f"ebook_setup_output_dir={args.output_dir}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
