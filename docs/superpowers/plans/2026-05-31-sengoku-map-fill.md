# 戦国・国盗り 地図差し替え（旧国境界の塗り分け）実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 既存ゲームの円ノード地図を、CODH旧国境界データ（CC BY-NC・非商用）を使った「実際の旧国境界の塗り分け地図」へ差し替える。

**Architecture:** 地図ジオメトリは Drive外（`C:\dev`）でのオフライン前処理（mapshaper＋依存なしnodeスクリプト）で静的な `src/data/geo.js` に固める。ゲーム本体はビルドレスを維持し、`render.js` の地図描画だけを円→塗り分けpathへ置換する。エンジン/データ/セーブ/入力は不変。

**Tech Stack:** Vanilla JS (ESM) / SVG `<path>` / テスト node:test / 前処理は mapshaper（Drive外でnpm導入）＋依存なしnodeスクリプト。

---

## 前提・規約（全タスク共通）

- **ゲーム本体**: `g:\マイドライブ\YNFactory-cc\sengoku-game`（独立gitリポ・依存ゼロ・テストは `node --test`）。コミット末尾に必ず:
  ```
  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  ```
- **前処理の作業場**: `C:\dev\sengoku-geo`（Drive外。`npm install` が可能）。ここで mapshaper を使う。**前処理スクリプト・原GeoJSONはゲームリポにコミットしない**。生成物 `geo.js` だけをゲームリポへコピーしてコミットする。
- **テストは node:test**（vitest不可）: `import { describe, it } from 'node:test'; import assert from 'node:assert/strict';`
- **不変ファイル**: `src/engine/*`, `src/ai/*`, `src/data/provinces.js`, `src/data/daimyo.js`, `src/engine/save.js`, `src/ui/input.js`, `src/main.js`。
- **ライセンス（CC BY-NC）必須クレジット**（geo.js冒頭コメント・ゲーム内フッター・README に掲示）:
  > 『旧国・旧郡境界データセット』（CODH作成）「幕末明治地勢地図境界データ」（人間文化研究機構作成）を加工 doi:10.20676/00000454

- **生成する `src/data/geo.js` の形（インターフェース固定）**:
  ```js
  /* 地図データ出典（CC BY-NC）: 『旧国・旧郡境界データセット』（CODH作成）… doi:10.20676/00000454 */
  export const MAP_VIEWBOX = '<minx> <miny> <w> <h>';  // 例 '0 0 760 1040'
  export const GEO = { owari: 'M…Z', mikawa: 'M…Z', /* …66国 */ };       // id → 塗り用SVGパス
  export const GEO_LABEL = { owari: [x, y], /* …66国 */ };               // id → ラベル座標(SVG空間)
  ```

- **66国ID一覧**（`provinces.js` の `PROVINCES[].id`。geo は過不足なくこれを満たす）:
  satsuma, osumi, hyuga, higo, chikugo, hizen, chikuzen, buzen, bungo, nagato, suo, aki, iwami, bingo, bitchu, bizen, mimasaka, inaba, hoki, izumo, oki, iyo, tosa, sanuki, awa, awaji, harima, tajima, settsu, kawachi, izumi, yamashiro, yamato, kii, iga, omi_s, omi_n, wakasa, tango, tanba, ise, owari, mino, mikawa, totomi, suruga, kai, shinano, hida, echizen, kaga, noto, etchu, echigo, izu, sagami, musashi, kozuke, shimotsuke, shimosa, kazusa, awa_kanto, hitachi, mutsu, dewa, ezo

---

## Task 1: CODH旧国・旧郡GeoJSONを取得（前処理・調査）

> このタスクは外部データの取得・構造把握を伴う調査タスク。コントローラ（または調査可能なエージェント）が `C:\dev\sengoku-geo` で実施する。

**Files:**
- Create: `C:\dev\sengoku-geo\kuni.geojson`（旧国ポリゴン）
- Create: `C:\dev\sengoku-geo\gun.geojson`（旧郡ポリゴン。近江分割に使用）
- Create: `C:\dev\sengoku-geo\SOURCE.md`（取得元URL・取得日・ライセンス・名称プロパティ名を記録）

- [ ] **Step 1: 作業ディレクトリ作成と取得**

`https://geoshape.ex.nii.ac.jp/kg/` を起点に、旧国・旧郡の GeoJSON を取得する。取得手段の候補（上から順に試す）:
1. `/kg/resource/` の一覧ページから旧国一括 or 各国GeoJSONのリンク
2. ベクトルタイル `/kg/vector/` の元GeoJSON/TopoJSON配布
3. データのDOI（doi:10.20676/00000454）先の配布ファイル
4. CODH/CODH関連のGitHubミラー

`curl -sL` で取得（ネットワーク可を確認済み）。TopoJSONで配布される場合は mapshaper で GeoJSON化（Step 3で導入する mapshaper を使用）。

- [ ] **Step 2: 構造確認（受入基準）**

取得GeoJSONについて以下を確認し `SOURCE.md` に記録:
- 旧国フィーチャ数が概ね **80〜90**（85前後）であること
- 各フィーチャの **国名プロパティ名**（例 `name` / `N` / `kuni` 等）と値の表記（例「尾張国」「尾張」）
- 旧郡GeoJSONの **国名・郡名プロパティ名**
- 座標系（経緯度 EPSG:4326 想定）

確認コマンド例:
```bash
node -e "const g=require('C:/dev/sengoku-geo/kuni.geojson'); console.log(g.features.length); console.log(Object.keys(g.features[0].properties)); console.log(g.features.slice(0,5).map(f=>f.properties))"
```
Expected: フィーチャ数と、国名を含むプロパティキーが判明する。

- [ ] **Step 3: mapshaper を Drive外に導入**

```bash
cd C:\dev\sengoku-geo && npm init -y && npm install mapshaper
```
Expected: `node_modules/.bin/mapshaper` が使える（Drive外なので install 成功）。

> 取得が全手段で不可の場合は BLOCKED として報告（仕様書§9のフォールバック判断へ）。

---

## Task 2: 85旧国→66国IDの対応表を作成

**Files:**
- Create: `C:\dev\sengoku-geo\mapping.js`（CODH国名→当方ID、近江郡の南北割当、結合グループ）
- Create: `C:\dev\sengoku-geo\check-mapping.mjs`（網羅性チェック）

- [ ] **Step 1: 対応表を作成**

`mapping.js`（CommonJS or ESM、後続スクリプトと整合する形式で）:
```js
// CODHの旧国「名称」→ 当方の国ID。Task1で判明した実際の表記に合わせること。
// 例として「尾張国」表記を仮定（実表記に合わせて調整）。
export const KUNI_TO_ID = {
  '薩摩国':'satsuma','大隅国':'osumi','日向国':'hyuga','肥後国':'higo',
  '筑後国':'chikugo','肥前国':'hizen','筑前国':'chikuzen','豊前国':'buzen','豊後国':'bungo',
  '長門国':'nagato','周防国':'suo','安芸国':'aki','石見国':'iwami','備後国':'bingo',
  '備中国':'bitchu','備前国':'bizen','美作国':'mimasaka','因幡国':'inaba','伯耆国':'hoki',
  '出雲国':'izumo','隠岐国':'oki','伊予国':'iyo','土佐国':'tosa','讃岐国':'sanuki',
  '阿波国':'awa','淡路国':'awaji','播磨国':'harima','但馬国':'tajima','摂津国':'settsu',
  '河内国':'kawachi','和泉国':'izumi','山城国':'yamashiro','大和国':'yamato','紀伊国':'kii',
  '伊賀国':'iga','若狭国':'wakasa','丹後国':'tango','丹波国':'tanba','伊勢国':'ise',
  '尾張国':'owari','美濃国':'mino','三河国':'mikawa','遠江国':'totomi','駿河国':'suruga',
  '甲斐国':'kai','信濃国':'shinano','飛騨国':'hida','越前国':'echizen','加賀国':'kaga',
  '能登国':'noto','越中国':'etchu','越後国':'echigo','伊豆国':'izu','相模国':'sagami',
  '武蔵国':'musashi','上野国':'kozuke','下野国':'shimotsuke','下総国':'shimosa',
  '上総国':'kazusa','安房国':'awa_kanto','常陸国':'hitachi',
  // —— 結合（複数CODH旧国→当方1国）——
  '陸奥国':'mutsu','陸中国':'mutsu','陸前国':'mutsu','磐城国':'mutsu','岩代国':'mutsu',
  '羽前国':'dewa','羽後国':'dewa','出羽国':'dewa',
  // 北海道11国 → ezo（実表記に合わせ全て ezo に割当）
  '渡島国':'ezo','後志国':'ezo','胆振国':'ezo','石狩国':'ezo','天塩国':'ezo','北見国':'ezo',
  '日高国':'ezo','十勝国':'ezo','釧路国':'ezo','根室国':'ezo','千島国':'ezo',
};
// 近江は CODH では1国。旧郡で南北に分ける。北近江=omi_n / 南近江=omi_s。
// 旧郡名は Task1 の旧郡データ表記に合わせること。
export const OMI_NORTH_GUN = ['坂田郡','浅井郡','伊香郡','高島郡']; // 北近江(浅井)
export const OMI_SOUTH_GUN = ['滋賀郡','栗太郡','野洲郡','蒲生郡','神崎郡','愛知郡','犬上郡','甲賀郡']; // 南近江(六角)
```

- [ ] **Step 2: 網羅性チェックスクリプト**

`check-mapping.mjs`:
```js
import fs from 'node:fs';
import { KUNI_TO_ID } from './mapping.js';
const IDS = "satsuma osumi hyuga higo chikugo hizen chikuzen buzen bungo nagato suo aki iwami bingo bitchu bizen mimasaka inaba hoki izumo oki iyo tosa sanuki awa awaji harima tajima settsu kawachi izumi yamashiro yamato kii iga omi_s omi_n wakasa tango tanba ise owari mino mikawa totomi suruga kai shinano hida echizen kaga noto etchu echigo izu sagami musashi kozuke shimotsuke shimosa kazusa awa_kanto hitachi mutsu dewa ezo".split(' ');
const kuni = JSON.parse(fs.readFileSync('./kuni.geojson','utf8'));
const NAMEPROP = process.argv[2] || 'name'; // Task1で判明した名称プロパティ
const names = kuni.features.map(f => f.properties[NAMEPROP]);
const unmapped = names.filter(n => !(n in KUNI_TO_ID));
const mappedIds = new Set(Object.values(KUNI_TO_ID).concat(['omi_s','omi_n'])); // 近江は郡分割で別途
const missing = IDS.filter(id => !mappedIds.has(id));
console.log('CODH旧国数:', names.length);
console.log('未対応のCODH国名:', unmapped);
console.log('当方IDで未カバー:', missing);
if (unmapped.length || missing.length) process.exit(1);
console.log('OK: 全対応');
```

- [ ] **Step 3: 実行して網羅を確認**

```bash
cd C:\dev\sengoku-geo && node check-mapping.mjs <名称プロパティ名>
```
Expected: `OK: 全対応`（未対応・未カバーが0）。差分があれば mapping.js を調整して再実行。近江(omi_s/omi_n)は郡分割で担保するため KUNI_TO_ID には近江を入れず、`missing` 判定では除外済み。

---

## Task 3: ジオ処理して `geo.js` を生成

**Files:**
- Create: `C:\dev\sengoku-geo\build-geo.mjs`（mapshaper呼び出し＋SVG→geo.js抽出。依存なし部分）
- Create: `C:\dev\sengoku-geo\out\map.svg`（mapshaper出力・中間）
- Create: `C:\dev\sengoku-geo\out\geo.js`（最終生成物）

- [ ] **Step 1: フィーチャに当方IDを付与し、結合・分割・簡略化・投影してSVG出力**

mapshaper コマンド列（`mapping.js`/Task1の実プロパティ名に合わせる）。近江以外と近江を別処理して結合する:
```bash
cd C:\dev\sengoku-geo
set MS=node_modules\.bin\mapshaper

# (a) 旧国: 当方IDを付与（近江は一旦 'OMI' に）→ ID単位で dissolve（結合）
%MS% kuni.geojson ^
  -each "id = require('./mapping.js').KUNI_TO_ID[this.properties.<NAMEPROP>] || (this.properties.<NAMEPROP>.indexOf('近江')>=0 ? 'OMI' : 'UNMAPPED')" ^
  -filter "id !== 'UNMAPPED' && id !== 'OMI'" ^
  -dissolve2 id ^
  -o kuni_main.geojson

# (b) 近江: 旧郡を南北に割当→omi_n/omi_s に dissolve
%MS% gun.geojson ^
  -filter "this.properties.<KUNI_PROP>.indexOf('近江')>=0" ^
  -each "id = require('./mapping.js').OMI_NORTH_GUN.indexOf(this.properties.<GUN_PROP>)>=0 ? 'omi_n' : 'omi_s'" ^
  -dissolve2 id ^
  -o omi.geojson

# (c) 結合 → 簡略化 → 投影 → SVG（id属性付き）
%MS% combine-files kuni_main.geojson omi.geojson ^
  -merge-layers force ^
  -simplify 8% keep-shapes ^
  -proj webmercator ^
  -o out/map.svg id-field=id
```
Expected: `out/map.svg` に `<path ... id="owari" d="..."/>` が66国ぶん。`<path ... id="UNMAPPED">` が無いこと（あれば mapping を修正）。

> プロパティ名 `<NAMEPROP>`/`<KUNI_PROP>`/`<GUN_PROP>` は Task1 の実値に置換する。`-each` の `require('./mapping.js')` が効かない環境では、mapping を JSON 化して `-each` 内に展開、または事前に node で id 付与した GeoJSON を作ってから mapshaper に渡す。

- [ ] **Step 2: SVG→geo.js 抽出スクリプト（依存なしnode）**

`build-geo.mjs`:
```js
import fs from 'node:fs';
const svg = fs.readFileSync('./out/map.svg', 'utf8');

// 各 <path ... id="X" ... d="Y" .../>（id/d は順不同）を抽出
const paths = {};
for (const m of svg.matchAll(/<path\b[^>]*?\/?>/g)) {
  const tag = m[0];
  const id = (tag.match(/\bid="([^"]+)"/) || [])[1];
  const d = (tag.match(/\bd="([^"]+)"/) || [])[1];
  if (id && d) paths[id] = d;
}

// 全座標から全体bbox と 各国のラベル点（頂点平均）を算出（SVG空間そのまま）
function coords(d) {
  const nums = (d.match(/-?\d*\.?\d+(?:e-?\d+)?/gi) || []).map(Number);
  const pts = [];
  for (let i = 0; i + 1 < nums.length; i += 2) pts.push([nums[i], nums[i + 1]]);
  return pts;
}
let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
const label = {};
for (const [id, d] of Object.entries(paths)) {
  const pts = coords(d);
  let sx = 0, sy = 0;
  for (const [x, y] of pts) {
    sx += x; sy += y;
    if (x < minX) minX = x; if (x > maxX) maxX = x;
    if (y < minY) minY = y; if (y > maxY) maxY = y;
  }
  label[id] = [Math.round((sx / pts.length) * 10) / 10, Math.round((sy / pts.length) * 10) / 10];
}
const pad = 5;
const vb = `${Math.floor(minX - pad)} ${Math.floor(minY - pad)} ${Math.ceil(maxX - minX + pad * 2)} ${Math.ceil(maxY - minY + pad * 2)}`;

const credit = "/* 地図データ出典（CC BY-NC）: 『旧国・旧郡境界データセット』（CODH作成）「幕末明治地勢地図境界データ」（人間文化研究機構作成）を加工 doi:10.20676/00000454 */\n";
let out = credit;
out += `export const MAP_VIEWBOX = '${vb}';\n`;
out += 'export const GEO = {\n' + Object.entries(paths).map(([id, d]) => `  ${id}: '${d}',`).join('\n') + '\n};\n';
out += 'export const GEO_LABEL = {\n' + Object.entries(label).map(([id, p]) => `  ${id}: [${p[0]}, ${p[1]}],`).join('\n') + '\n};\n';
fs.writeFileSync('./out/geo.js', out);
console.log('paths:', Object.keys(paths).length, 'viewBox:', vb);
```

- [ ] **Step 3: 実行**

```bash
cd C:\dev\sengoku-geo && node build-geo.mjs
```
Expected: `paths: 66 viewBox: ...`。66未満なら Task2/Step1 のmappingを修正して再生成。

---

## Task 4: geo.js をゲームに取り込み、網羅テスト（TDD）

**Files:**
- Create: `sengoku-game/src/data/geo.js`（Task3の生成物をコピー）
- Test: `sengoku-game/tests/geo.test.js`

- [ ] **Step 1: 生成物をコピー**

```bash
copy C:\dev\sengoku-geo\out\geo.js "g:\マイドライブ\YNFactory-cc\sengoku-game\src\data\geo.js"
```

- [ ] **Step 2: 網羅テストを書く**

`sengoku-game/tests/geo.test.js`:
```js
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { PROVINCES } from '../src/data/provinces.js';
import { GEO, GEO_LABEL, MAP_VIEWBOX } from '../src/data/geo.js';

const ids = PROVINCES.map(p => p.id);

describe('geo data', () => {
  it('MAP_VIEWBOX は数値4つ', () => {
    const n = MAP_VIEWBOX.trim().split(/\s+/).map(Number);
    assert.equal(n.length, 4);
    assert.ok(n.every(Number.isFinite));
  });
  it('GEO は全66国IDを非空パスでカバー', () => {
    for (const id of ids) {
      assert.ok(typeof GEO[id] === 'string' && GEO[id].length > 0, `GEO missing ${id}`);
      assert.ok(/^[Mm]/.test(GEO[id].trim()), `GEO[${id}] not a path`);
    }
  });
  it('GEO に余分なIDが無い', () => {
    for (const id of Object.keys(GEO)) assert.ok(ids.includes(id), `extra ${id}`);
  });
  it('GEO_LABEL は全IDを viewBox 範囲内で持つ', () => {
    const [mx, my, w, h] = MAP_VIEWBOX.trim().split(/\s+/).map(Number);
    for (const id of ids) {
      const lab = GEO_LABEL[id];
      assert.ok(Array.isArray(lab) && lab.length === 2, `label missing ${id}`);
      assert.ok(lab[0] >= mx && lab[0] <= mx + w, `label x oob ${id}`);
      assert.ok(lab[1] >= my && lab[1] <= my + h, `label y oob ${id}`);
    }
  });
});
```

- [ ] **Step 3: 実行（pass）**

```bash
cd "g:/マイドライブ/YNFactory-cc/sengoku-game" && node --test tests/geo.test.js
```
Expected: pass 4 / fail 0。落ちる場合は geo.js（=前処理）側を修正。

- [ ] **Step 4: 全テスト＋コミット**

```bash
node --test
git add src/data/geo.js tests/geo.test.js
git commit -m "$(printf 'feat: add old-province boundary geo data (CODH, CC BY-NC)\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```
Expected: 全60テスト（既存56＋geo4）pass。

---

## Task 5: render.js の地図描画を塗り分けpathへ置換

**Files:**
- Modify: `sengoku-game/src/ui/render.js`（`renderMap` と先頭import）

- [ ] **Step 1: import に geo を追加**

`render.js` 先頭の import 群に追加:
```js
import { GEO, GEO_LABEL, MAP_VIEWBOX } from '../data/geo.js';
```

- [ ] **Step 2: `renderMap` を置換**

既存の `renderMap`（円ノード＋隣接線）を、次の実装に丸ごと置き換える:
```js
const SVGNS = 'http://www.w3.org/2000/svg';

export function renderMap(state, selectedId) {
  const svg = document.getElementById('map');
  svg.setAttribute('viewBox', MAP_VIEWBOX);
  svg.innerHTML = '';

  // 国の塗り分け（所有者色）
  for (const p of Object.values(state.provinces)) {
    const d = GEO[p.id];
    if (!d) { console.warn('geo path 欠落:', p.id); continue; }
    const path = document.createElementNS(SVGNS, 'path');
    path.setAttribute('d', d);
    path.setAttribute('fill', state.daimyo[p.owner].color);
    path.setAttribute('class', 'prov-fill' + (p.id === selectedId ? ' selected' : ''));
    path.setAttribute('data-prov', p.id);
    svg.appendChild(path);
  }

  // 国名ラベル
  for (const p of Object.values(state.provinces)) {
    const lab = GEO_LABEL[p.id];
    if (!lab) continue;
    const t = document.createElementNS(SVGNS, 'text');
    t.setAttribute('x', lab[0]);
    t.setAttribute('y', lab[1]);
    t.setAttribute('class', 'prov-label');
    t.textContent = p.name;
    svg.appendChild(t);
  }
}
```

- [ ] **Step 3: 全テスト（回帰確認）＋コミット**

```bash
cd "g:/マイドライブ/YNFactory-cc/sengoku-game" && node --test
git add src/ui/render.js
git commit -m "$(printf 'feat: render filled province polygons instead of nodes\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```
Expected: 全テスト pass（renderはDOM依存だがimport追加でエンジンテストは不変。`node --test` が緑）。

---

## Task 6: 地図スタイルと帰属クレジット表示

**Files:**
- Modify: `sengoku-game/styles.css`
- Modify: `sengoku-game/index.html`

- [ ] **Step 1: styles.css に塗り分け用スタイルとクレジット欄を追加**

`styles.css` の地図関連（`.prov-node`/`.prov-link`/`.prov-label` 付近）に追記/調整:
```css
.prov-fill { stroke:#16130f; stroke-width:0.8; cursor:pointer; transition:opacity .1s; }
.prov-fill:hover { opacity:.82; }
.prov-fill.selected { stroke:#fff; stroke-width:2.4; }
.prov-label { fill:#fff; font-size:11px; text-anchor:middle; pointer-events:none;
  paint-order:stroke; stroke:#0009; stroke-width:2px; }
#credits { font-size:11px; opacity:.55; padding:3px 10px; background:#1c1a17;
  border-top:1px solid #443d33; }
#credits a { color:#9bb; }
```

- [ ] **Step 2: index.html にクレジット欄を追加**

`index.html` の `</main>`（ゲーム画面）の直後あたり、`<div id="modal">` の前に追加:
```html
  <footer id="credits">
    地図データ: 『旧国・旧郡境界データセット』（CODH作成）「幕末明治地勢地図境界データ」（人間文化研究機構作成）を加工 doi:10.20676/00000454（CC BY-NC・非商用利用）
  </footer>
```

- [ ] **Step 3: コミット**

```bash
cd "g:/マイドライブ/YNFactory-cc/sengoku-game"
git add styles.css index.html
git commit -m "$(printf 'feat: style filled map and show CC BY-NC credit\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

## Task 7: ブラウザ実機検証・README更新・仕上げ

**Files:**
- Modify: `sengoku-game/README.md`（地図データの出典・ライセンス追記）

- [ ] **Step 1: サーバ起動＆ブラウザ検証（Playwright）**

```bash
cd "g:/マイドライブ/YNFactory-cc/sengoku-game" && python -m http.server 8000   # 別ターミナル(background)
```
http://localhost:8000 を開き、大名を選んで以下を確認:
- [ ] 地図が日本列島の形になり、66国が旧国境界で塗られている
- [ ] 国をクリックで選択でき、選択国の枠が強調される
- [ ] 国名ラベルが読める
- [ ] 出陣で攻略すると国の塗り色が変わる（自色が広がる）
- [ ] フッターにCC BY-NCクレジットが表示されている
- [ ] コンソールエラー0（favicon 404 は除く）

- [ ] **Step 2: README に出典・ライセンスを追記**

`README.md` に節を追加:
```markdown
## 地図データの出典・ライセンス
本ゲームの地図は『旧国・旧郡境界データセット』（CODH作成）「幕末明治地勢地図境界データ」（人間文化研究機構作成）を加工して使用しています（doi:10.20676/00000454）。
ライセンスは CC BY-NC（表示・非商用）。**本ゲームは非商用利用に限ります。**
```

- [ ] **Step 3: 不具合があれば修正（render/css/geo）**

見つかった問題は「原因（render表示 or geo前処理）を切り分け→修正→再描画確認」。geo起因なら前処理（Task3）をやり直して geo.js を再生成。

- [ ] **Step 4: コミット**

```bash
cd "g:/マイドライブ/YNFactory-cc/sengoku-game"
git add README.md
git commit -m "$(printf 'docs: credit map data source and license in README\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

## Self-Review（計画と仕様の突き合わせ）

**1. 仕様カバレッジ**
- 66国を実旧国境界で塗り分け → Task3生成＋Task5描画 ✓
- 所有者色・征服で色が広がる → Task5（fill=所有者色、毎描画で反映）✓
- クリック選択・選択強調 → Task5（data-prov＋selected）＋既存input.js（不変）✓
- 国名ラベル → Task5（GEO_LABEL）✓
- CC BY-NCクレジット（ゲーム内・README・geo.js冒頭）→ Task6/Task7/Task3 ✓
- 66国網羅の自動チェック → Task4 geo.test.js ✓
- 85→66対応（結合/近江分割/北海道・陸奥・出羽）→ Task2/Task3 ✓
- ビルドレス維持・前処理はDrive外 → 前提＋Task1/3 ✓
- 既存56テスト不変 → Task4/5 で `node --test` 緑を確認 ✓
- input/engine/data/save/main 不変 → 変更ファイルに含めず ✓

**2. プレースホルダ検査**
- レンダラ/テスト/CSS/抽出スクリプトは実コードを記載。Task1（データ取得）とTask3のmapshaperコマンドは外部データ構造に依存するため、`<NAMEPROP>` 等の実プロパティ名を Task1 で確定して差し込む手順を明示（調査タスクとして正当。受入基準＝geo.test.js）。

**3. 型・名称整合**
- `geo.js` は `MAP_VIEWBOX`(文字列) / `GEO`(id→path文字列) / `GEO_LABEL`(id→[x,y]) を全タスクで一貫使用 ✓
- `render.js` の import と Task4 のテスト import が一致 ✓
- 66国IDは provinces.js と一致（前提に列挙）✓
- `.prov-fill` / `.selected` / `.prov-label` のCSSクラスと render の付与クラスが一致 ✓
