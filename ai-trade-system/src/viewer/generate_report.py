"""
ステップ4: 判定結果を画像付きHTMLレポートとして生成する
画像をBase64埋め込みにすることで、ブラウザで直接開ける
"""
import os
import sys
import json
import base64
from pathlib import Path


def image_to_base64(image_path):
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def generate_report(result_json_path, output_html_path=None):
    with open(result_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    result_dir = os.path.dirname(result_json_path)
    charts_dir = os.path.join(result_dir, "charts")

    config = data["config"]
    stats = data["stats"]
    trades = data.get("trades", [])
    metadata = data.get("metadata", [])

    # トレード結果をマップ化
    trade_map = {}
    for t in trades:
        trade_map[t["chart_image"]] = t

    # 画像カードHTML生成
    cards_html = []
    for m in metadata:
        img_path = os.path.join(charts_dir, m["file"])
        if not os.path.exists(img_path):
            continue

        b64 = image_to_base64(img_path)
        detected = m.get("detected", 0)
        badge_cls = "detected" if detected == 1 else "not-detected"
        badge_text = "DETECTED" if detected == 1 else "NOT"

        trade = trade_map.get(m["file"])
        trade_html = ""
        if trade:
            pnl_cls = "pnl-pos" if trade["net_pnl_pct"] >= 0 else "pnl-neg"
            win_cls = "win" if trade["win"] else "loss"
            win_text = "WIN" if trade["win"] else "LOSS"
            trade_html = f"""
            <div class="trade-info">
                <span class="badge {win_cls}">{win_text}</span>
                <span class="{pnl_cls}">{'+' if trade['net_pnl_pct']>=0 else ''}{trade['net_pnl_pct']:.2f}%</span>
                <span class="prices">{trade['entry_price']:.1f} → {trade['exit_price']:.1f}</span>
            </div>"""

        end_ts = m.get("end_ts", "")
        if isinstance(end_ts, str) and len(end_ts) > 16:
            end_ts = end_ts[:16]

        cards_html.append(f"""
        <div class="card" data-detected="{detected}">
            <img src="data:image/png;base64,{b64}" alt="{m['file']}">
            <div class="info">
                <span class="ts">{end_ts}</span>
                <span class="badge {badge_cls}">{badge_text}</span>
            </div>
            {trade_html}
        </div>""")

    # エクイティカーブデータ
    equity_json = json.dumps(stats.get("equity_curve", []))

    html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<title>Backtest Report - {config['pattern']}</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; background:#1a1a2e; color:#e0e0e0; padding:20px; }}
h1 {{ font-size:20px; margin-bottom:6px; }}
.subtitle {{ color:#888; font-size:13px; margin-bottom:20px; }}
.stats {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:10px; margin-bottom:24px; }}
.stat {{ background:#16213e; border-radius:8px; padding:12px; text-align:center; }}
.stat .val {{ font-size:22px; font-weight:bold; }}
.stat .lbl {{ font-size:11px; color:#888; margin-top:2px; }}
.pos .val {{ color:#26a69a; }}
.neg .val {{ color:#ef5350; }}
#equity {{ background:#16213e; border-radius:8px; padding:16px; margin-bottom:24px; }}
#equity canvas {{ width:100%; height:180px; }}
.filters {{ display:flex; gap:8px; margin-bottom:16px; }}
.filters button {{ padding:6px 14px; border-radius:4px; border:1px solid #0f3460; background:#1a1a2e; color:#e0e0e0; cursor:pointer; font-size:13px; }}
.filters button.active {{ background:#e94560; border-color:#e94560; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(260px,1fr)); gap:10px; }}
.card {{ background:#16213e; border-radius:8px; overflow:hidden; display:block; }}
.card.hidden {{ display:none; }}
.card img {{ width:100%; aspect-ratio:1; object-fit:cover; display:block; }}
.info {{ padding:8px 10px; font-size:12px; display:flex; justify-content:space-between; align-items:center; }}
.ts {{ color:#888; }}
.badge {{ padding:2px 8px; border-radius:4px; font-size:11px; font-weight:bold; }}
.badge.detected {{ background:#26a69a; color:#fff; }}
.badge.not-detected {{ background:#333; color:#666; }}
.badge.win {{ background:#26a69a; color:#fff; }}
.badge.loss {{ background:#ef5350; color:#fff; }}
.trade-info {{ padding:0 10px 8px; font-size:11px; display:flex; align-items:center; gap:8px; }}
.pnl-pos {{ color:#26a69a; }}
.pnl-neg {{ color:#ef5350; }}
.prices {{ color:#666; }}
</style>
</head>
<body>
<h1>Backtest Report: {config['pattern']} ({config['direction']})</h1>
<div class="subtitle">BTC/USDT 4h | Window: {config['window_size']} bars | Step: {config['step']} | Hold: {config['hold_bars']} bars | Fee: {config['fee_rate']*100:.1f}%</div>

<div class="stats">
    <div class="stat"><div class="val">{stats['total_trades']}</div><div class="lbl">シグナル数</div></div>
    <div class="stat {'pos' if stats['win_rate_pct']>=50 else 'neg'}"><div class="val">{stats['win_rate_pct']:.1f}%</div><div class="lbl">勝率</div></div>
    <div class="stat {'pos' if stats['profit_factor']>=1 else 'neg'}"><div class="val">{stats['profit_factor']:.2f}</div><div class="lbl">PF</div></div>
    <div class="stat {'pos' if stats['total_return_pct']>=0 else 'neg'}"><div class="val">{stats['total_return_pct']:.2f}%</div><div class="lbl">累積損益</div></div>
    <div class="stat pos"><div class="val">{stats['avg_win_pct']:.2f}%</div><div class="lbl">平均利益</div></div>
    <div class="stat neg"><div class="val">{stats['avg_loss_pct']:.2f}%</div><div class="lbl">平均損失</div></div>
    <div class="stat neg"><div class="val">{stats['max_drawdown_pct']:.2f}%</div><div class="lbl">最大DD</div></div>
    <div class="stat"><div class="val">{len(metadata)}</div><div class="lbl">スキャン数</div></div>
</div>

<div id="equity">
    <div style="font-size:14px;margin-bottom:8px;color:#a0a0c0;">エクイティカーブ（累積損益 %）</div>
    <canvas id="eq-canvas"></canvas>
</div>

<div class="filters">
    <button class="active" onclick="filter('all',this)">全て ({len(metadata)})</button>
    <button onclick="filter('1',this)">検出のみ ({sum(1 for m in metadata if m.get('detected')==1)})</button>
    <button onclick="filter('0',this)">未検出のみ ({sum(1 for m in metadata if m.get('detected')!=1)})</button>
</div>

<div class="grid" id="grid">
{''.join(cards_html)}
</div>

<script>
function filter(v, btn) {{
    document.querySelectorAll('.filters button').forEach(b=>b.classList.remove('active'));
    btn.classList.add('active');
    document.querySelectorAll('.card').forEach(c => {{
        if (v==='all') c.classList.remove('hidden');
        else if (v==='1') c.classList.toggle('hidden', c.dataset.detected!=='1');
        else c.classList.toggle('hidden', c.dataset.detected!=='0');
    }});
}}

// エクイティカーブ描画
(function() {{
    const curve = {equity_json};
    if (curve.length < 2) return;
    const canvas = document.getElementById('eq-canvas');
    const dpr = window.devicePixelRatio||1;
    canvas.width = canvas.clientWidth*dpr;
    canvas.height = 180*dpr;
    const ctx = canvas.getContext('2d');
    ctx.scale(dpr,dpr);
    const W=canvas.clientWidth, H=180;
    const pad={{t:10,b:20,l:50,r:10}};
    const cW=W-pad.l-pad.r, cH=H-pad.t-pad.b;
    const mx=Math.max(...curve,0), mn=Math.min(...curve,0), rng=(mx-mn)||1;
    function tX(i){{return pad.l+(i/(curve.length-1))*cW;}}
    function tY(v){{return pad.t+cH*(1-(v-mn)/rng);}}
    ctx.fillStyle='#16213e'; ctx.fillRect(0,0,W,H);
    ctx.strokeStyle='#444'; ctx.lineWidth=1; ctx.setLineDash([4,4]);
    ctx.beginPath(); ctx.moveTo(pad.l,tY(0)); ctx.lineTo(W-pad.r,tY(0)); ctx.stroke();
    ctx.setLineDash([]);
    ctx.strokeStyle=curve[curve.length-1]>=0?'#26a69a':'#ef5350'; ctx.lineWidth=2;
    ctx.beginPath();
    curve.forEach((v,i)=>{{if(i===0)ctx.moveTo(tX(i),tY(v));else ctx.lineTo(tX(i),tY(v));}});
    ctx.stroke();
    ctx.fillStyle='#888'; ctx.font='11px monospace'; ctx.textAlign='right';
    ctx.fillText(mx.toFixed(1)+'%',pad.l-5,pad.t+10);
    ctx.fillText(mn.toFixed(1)+'%',pad.l-5,H-pad.b);
    ctx.fillText('0%',pad.l-5,tY(0)+4);
}})();
</script>
</body>
</html>"""

    if output_html_path is None:
        output_html_path = os.path.join(result_dir, "report.html")

    with open(output_html_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Report generated: {output_html_path}")
    return output_html_path


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate backtest HTML report")
    parser.add_argument("result_json", help="Path to result.json")
    parser.add_argument("--output", default=None, help="Output HTML path")
    args = parser.parse_args()
    generate_report(args.result_json, args.output)
