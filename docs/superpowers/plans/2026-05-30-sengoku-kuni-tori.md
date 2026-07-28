# 戦国・国盗り戦略ゲーム 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 戦国時代を舞台に、フルマップ（60超の旧国）で「開始→拡張→全国統一」まで一通り遊べるブラウザ版の国盗り戦略シミュレーションを実装する。

**Architecture:** 素のHTML/CSS/JS（ビルドレス・ESモジュール）。ゲーム計算（経済・合戦・外交・AI・勝敗）はDOM非依存の純粋関数として `src/engine` `src/ai` に置き、`src/data` の静的データと `src/ui` の描画を分離する。乱数は注入式でテスト決定性を確保する。

**Tech Stack:** Vanilla JavaScript (ESM) / SVG / localStorage / テストは **Node標準の `node:test`（依存ゼロ・node_modules不要）** / ローカル配信は `python -m http.server`。

> 補足: 作業ツリーが Google Drive マウント（g:\）上にあり、`npm install` がDrive上で失敗する（GVFSがbin/symlinkを書けない）。そのため Vitest は使わず、Node内蔵の `node:test` + `node:assert/strict` でテストする。これにより依存ゼロ・完全移植可能を維持する。

---

## 前提・規約（全タスク共通）

- **作業ディレクトリ**: 以後の全コマンド・相対パスは `sengoku-game/` を cwd とする（Task 0 で作成）。
- **git**: 親リポジトリの `.git` は外部パスを指す dangling 状態で機能しないため、本プロジェクトは `sengoku-game/` 直下に**独立した git リポジトリ**を作って管理する（Task 0）。各コミットのメッセージ末尾には次の行を付ける:

  ```
  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  ```

- **テスト規約（重要）**: 本計画のテストコードは可読性のため **vitest 記法（`describe/it/expect`）で記載**しているが、**実行時は Node 標準の `node:test` に読み替える**。コントローラが各タスクの dispatch 時に下表で変換済みのコードを実装者へ渡す。

  | vitest | node:test (`import { describe, it } from 'node:test'; import assert from 'node:assert/strict'`) |
  |---|---|
  | `import { describe, it, expect } from 'vitest'` | `import { describe, it } from 'node:test';`<br>`import assert from 'node:assert/strict';` |
  | `expect(a).toBe(b)` | `assert.equal(a, b)` |
  | `expect(a).toEqual(b)` | `assert.deepEqual(a, b)` |
  | `expect(a).toContain(x)` | `assert.ok(a.includes(x))` |
  | `expect(a).toBeGreaterThan(n)` / `toBeGreaterThanOrEqual(n)` | `assert.ok(a > n)` / `assert.ok(a >= n)` |
  | `expect(a).toBeLessThanOrEqual(n)` | `assert.ok(a <= n)` |
  | `expect(a, msg).toBe(true)` / `.toBeTruthy()` | `assert.ok(a, msg)` |

  - 全テスト実行: `node --test`（`tests/*.test.js` を自動検出）
  - 単一ファイル実行: `node --test tests/<name>.test.js`（計画中の `npm test -- <name>` はこれに読み替える）
  - `npm install` は不要（依存ゼロ）。

- **モジュール一覧と責務**（この構成で固定）:

  | ファイル | 責務 | 依存 |
  |---|---|---|
  | `src/data/provinces.js` | 60超の国データ（静的） | なし |
  | `src/data/daimyo.js` | 1560年シナリオの大名＋SCENARIO_1560 | provinces |
  | `src/engine/util.js` | `clamp` 等の小ユーティリティ | なし |
  | `src/engine/state.js` | 状態生成・参照ヘルパ | util |
  | `src/engine/economy.js` | 収入・維持・民忠（純粋） | state |
  | `src/engine/combat.js` | 合戦自動解決（純粋） | util |
  | `src/engine/diplomacy.js` | 同盟の判定・管理 | state |
  | `src/engine/victory.js` | 滅亡処理・勝敗判定 | state |
  | `src/ai/ai.js` | AI意思決定（純粋） | state, combat, util |
  | `src/engine/turn.js` | ターン進行統括（季節開始/行動適用/AI/終了） | 上記すべて |
  | `src/engine/save.js` | localStorage セーブ/ロード | なし |
  | `src/ui/render.js` | state→DOM描画 | state |
  | `src/ui/input.js` | UIイベント配線 | なし |
  | `src/main.js` | 全体配線・開始画面・ループ | 全部 |

- **データモデル（確定フィールド）**

  ```js
  // Province
  { id, name, region, x, y, neighbors:[id], terrain, baseKokudaka,
    owner, agri, commerce, troops, castle, loyalty, rations }
  // Daimyo
  { id, name, family, color, isPlayer, capital,
    stats:{ valor, politics, intellect }, gold, alive, aiPersonality }
  // GameState
  { year, season, provinces:{[id]:Province}, daimyo:{[id]:Daimyo},
    alliances:[[idA,idB]], playerId, log:[{turn,type,text}], status }
  ```

- **アクション型**（AI・プレイヤー共通）

  ```js
  { type:'develop', province, kind:'agri'|'commerce' }
  { type:'recruit', province }
  { type:'train',   province }
  { type:'attack',  from, to, troops }
  { type:'propose_alliance', to }
  ```

---

## Task 0: プロジェクト雛形・ツール・git初期化

**Files:**
- Create: `sengoku-game/package.json`
- Create: `sengoku-game/.gitignore`
- Create: `sengoku-game/README.md`
- Create: `sengoku-game/index.html`（最小骨格）
- Create: `sengoku-game/src/main.js`（空エクスポート）
- Create: `sengoku-game/tests/smoke.test.js`

- [ ] **Step 1: ディレクトリ作成（リポジトリ root から）**

Run:
```bash
mkdir -p sengoku-game/src/data sengoku-game/src/engine sengoku-game/src/ai sengoku-game/src/ui sengoku-game/tests
```

- [ ] **Step 2: package.json を作成**

`sengoku-game/package.json`（依存ゼロ・`node:test` を使用）:
```json
{
  "name": "sengoku-kuni-tori",
  "version": "0.1.0",
  "private": true,
  "type": "module",
  "scripts": {
    "test": "node --test",
    "start": "python -m http.server 8000"
  }
}
```

- [ ] **Step 3: .gitignore と README を作成**

`sengoku-game/.gitignore`:
```
node_modules/
.DS_Store
*.log
```

`sengoku-game/README.md`:
```markdown
# 戦国・国盗り戦略ゲーム

ブラウザで動く戦国時代の国盗り戦略シミュレーション（ビルドレス）。

## 遊び方
1. `python -m http.server 8000` をこのディレクトリで実行
2. ブラウザで http://localhost:8000 を開く

## テスト
依存ゼロ。`npm test`（= `node --test`）を実行（Node 18+）。
```

- [ ] **Step 4: index.html と main.js の最小骨格**

`sengoku-game/index.html`:
```html
<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>戦国・国盗り</title>
  <link rel="stylesheet" href="styles.css" />
</head>
<body>
  <div id="app">読み込み中…</div>
  <script type="module" src="src/main.js"></script>
</body>
</html>
```

`sengoku-game/src/main.js`:
```js
// 全体配線は Task 14 で実装する
export const APP_NAME = '戦国・国盗り';
```

- [ ] **Step 5: スモークテストを書く**

`sengoku-game/tests/smoke.test.js`:
```js
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { APP_NAME } from '../src/main.js';

describe('smoke', () => {
  it('main.js を import できる', () => {
    assert.equal(APP_NAME, '戦国・国盗り');
  });
});
```

- [ ] **Step 6: テスト実行（成功を確認）**

Run（sengoku-game 内で）:
```bash
node --test
```
Expected: 1 passed（smoke）。`npm install` は不要（依存ゼロ）。

- [ ] **Step 7: git 初期化＆コミット**

Run:
```bash
git init
git add .
git commit -m "$(printf 'chore: scaffold sengoku-game project\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```
Expected: 初回コミット作成（node_modules は無視される）

---

## Task 1: util.js（clamp）

**Files:**
- Create: `src/engine/util.js`
- Test: `tests/util.test.js`

- [ ] **Step 1: 失敗するテストを書く**

`tests/util.test.js`:
```js
import { describe, it, expect } from 'vitest';
import { clamp } from '../src/engine/util.js';

describe('clamp', () => {
  it('範囲内はそのまま', () => expect(clamp(5, 0, 10)).toBe(5));
  it('下限でクランプ', () => expect(clamp(-3, 0, 10)).toBe(0));
  it('上限でクランプ', () => expect(clamp(99, 0, 10)).toBe(10));
});
```

- [ ] **Step 2: 実行して失敗を確認**

Run: `npm test -- util`
Expected: FAIL（`clamp` is not defined / module not found）

- [ ] **Step 3: 実装**

`src/engine/util.js`:
```js
export function clamp(v, lo, hi) {
  return Math.max(lo, Math.min(hi, v));
}
```

- [ ] **Step 4: 実行して成功を確認**

Run: `npm test -- util`
Expected: 3 passed

- [ ] **Step 5: コミット**

```bash
git add src/engine/util.js tests/util.test.js
git commit -m "$(printf 'feat: add clamp util\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

## Task 2: state.js（状態生成・参照ヘルパ）＋テスト用フィクスチャ

**Files:**
- Create: `src/engine/state.js`
- Create: `tests/helpers.js`（以後のエンジンテスト共通の小世界＋乱数）
- Test: `tests/state.test.js`

- [ ] **Step 1: テスト用ヘルパ（フィクスチャ）を作成**

`tests/helpers.js`:
```js
// 3国2大名の小世界。エンジン純粋関数のテスト専用（史実データには依存しない）。
export function makeTestScenario() {
  return {
    year: 1560,
    season: 0,
    playerId: 'd1',
    provinces: [
      { id:'a', name:'A', region:'X', x:0.30, y:0.30, neighbors:['b'],
        terrain:'plain', baseKokudaka:50,
        owner:'d1', agri:40, commerce:40, troops:3000, castle:20, loyalty:70, rations:5000 },
      { id:'b', name:'B', region:'X', x:0.50, y:0.40, neighbors:['a','c'],
        terrain:'plain', baseKokudaka:40,
        owner:'d2', agri:30, commerce:30, troops:1500, castle:15, loyalty:60, rations:3000 },
      { id:'c', name:'C', region:'X', x:0.70, y:0.50, neighbors:['b'],
        terrain:'mountain', baseKokudaka:30,
        owner:'d2', agri:30, commerce:30, troops:2000, castle:25, loyalty:65, rations:4000 },
    ],
    daimyo: [
      { id:'d1', name:'D1', family:'D1家', color:'#cc3333', isPlayer:false, capital:'a',
        stats:{ valor:80, politics:70, intellect:75 }, gold:2000, alive:true, aiPersonality:'balanced' },
      { id:'d2', name:'D2', family:'D2家', color:'#3366cc', isPlayer:false, capital:'c',
        stats:{ valor:60, politics:50, intellect:55 }, gold:1500, alive:true, aiPersonality:'aggressive' },
    ],
  };
}

// 決定的な乱数源（テスト用）
export const fixed = (v) => () => v;          // 常に v
export const seq = (arr) => {                  // 順に返し、尽きたら最後を反復
  let i = 0;
  return () => arr[Math.min(i++, arr.length - 1)];
};
```

- [ ] **Step 2: 失敗するテストを書く**

`tests/state.test.js`:
```js
import { describe, it, expect } from 'vitest';
import { makeTestScenario } from './helpers.js';
import {
  createInitialState, provincesOf, totalTroops, areAllied, daimyoStrength,
} from '../src/engine/state.js';

describe('state', () => {
  it('createInitialState はマップ化・ディープクローン・playerId設定する', () => {
    const sc = makeTestScenario();
    const s = createInitialState(sc, 'd1');
    expect(s.provinces.a.name).toBe('A');
    expect(s.daimyo.d1.isPlayer).toBe(true);
    expect(s.daimyo.d2.isPlayer).toBe(false);
    expect(s.playerId).toBe('d1');
    expect(s.status).toBe('playing');
    // ディープクローン：元データを変更しても state は不変
    sc.provinces[0].troops = 1;
    expect(s.provinces.a.troops).toBe(3000);
  });

  it('provincesOf は所有国の配列を返す', () => {
    const s = createInitialState(makeTestScenario(), 'd1');
    expect(provincesOf(s, 'd2').map(p => p.id).sort()).toEqual(['b', 'c']);
  });

  it('totalTroops は所有国の兵力合計', () => {
    const s = createInitialState(makeTestScenario(), 'd1');
    expect(totalTroops(s, 'd2')).toBe(3500);
  });

  it('areAllied は同盟ペアを双方向で判定', () => {
    const s = createInitialState(makeTestScenario(), 'd1');
    expect(areAllied(s, 'd1', 'd2')).toBe(false);
    s.alliances.push(['d1', 'd2']);
    expect(areAllied(s, 'd1', 'd2')).toBe(true);
    expect(areAllied(s, 'd2', 'd1')).toBe(true);
  });

  it('daimyoStrength = 総兵力 + 国数*2000', () => {
    const s = createInitialState(makeTestScenario(), 'd1');
    expect(daimyoStrength(s, 'd1')).toBe(3000 + 1 * 2000);
    expect(daimyoStrength(s, 'd2')).toBe(3500 + 2 * 2000);
  });
});
```

- [ ] **Step 3: 実行して失敗を確認**

Run: `npm test -- state`
Expected: FAIL（module not found）

- [ ] **Step 4: 実装**

`src/engine/state.js`:
```js
const PROVINCE_STRENGTH_WEIGHT = 2000;

export function createInitialState(scenario, playerId = scenario.playerId) {
  const provinces = {};
  for (const p of scenario.provinces) {
    provinces[p.id] = { ...p, neighbors: [...p.neighbors] };
  }
  const daimyo = {};
  for (const d of scenario.daimyo) {
    daimyo[d.id] = { ...d, stats: { ...d.stats }, isPlayer: d.id === playerId };
  }
  return {
    year: scenario.year,
    season: scenario.season,
    provinces,
    daimyo,
    alliances: [],
    playerId,
    log: [],
    status: 'playing',
  };
}

export function provincesOf(state, daimyoId) {
  return Object.values(state.provinces).filter(p => p.owner === daimyoId);
}

export function totalTroops(state, daimyoId) {
  return provincesOf(state, daimyoId).reduce((sum, p) => sum + p.troops, 0);
}

export function areAllied(state, a, b) {
  return state.alliances.some(
    ([x, y]) => (x === a && y === b) || (x === b && y === a),
  );
}

export function daimyoStrength(state, daimyoId) {
  return totalTroops(state, daimyoId)
    + provincesOf(state, daimyoId).length * PROVINCE_STRENGTH_WEIGHT;
}
```

- [ ] **Step 5: 実行して成功を確認**

Run: `npm test -- state`
Expected: 5 passed

- [ ] **Step 6: コミット**

```bash
git add src/engine/state.js tests/helpers.js tests/state.test.js
git commit -m "$(printf 'feat: add game state factory and query helpers\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

## Task 3: economy.js（収入・維持・民忠）

**Files:**
- Create: `src/engine/economy.js`
- Test: `tests/economy.test.js`

- [ ] **Step 1: 失敗するテストを書く**

`tests/economy.test.js`:
```js
import { describe, it, expect } from 'vitest';
import { makeTestScenario } from './helpers.js';
import { createInitialState } from '../src/engine/state.js';
import { goldIncome, rationIncome, upkeep, applyEconomy } from '../src/engine/economy.js';

describe('economy', () => {
  const A = () => createInitialState(makeTestScenario(), 'd1').provinces.a;

  it('goldIncome = round(石高*商業/100*(0.5+民忠/200)*8)', () => {
    expect(goldIncome(A())).toBe(136); // 50*0.4*0.85*8
  });
  it('rationIncome は季節係数を反映（春1.0 / 秋2.0）', () => {
    expect(rationIncome(A(), 0)).toBe(600);   // 50*0.4*1.0*30
    expect(rationIncome(A(), 2)).toBe(1200);  // 秋
  });
  it('upkeep = round(兵力*0.5)', () => {
    expect(upkeep(A())).toBe(1500);
  });

  it('applyEconomy: 通常は金加算・兵糧収支・民忠+2', () => {
    const s = createInitialState(makeTestScenario(), 'd1');
    applyEconomy(s);
    expect(s.daimyo.d1.gold).toBe(2000 + 136);
    expect(s.provinces.a.rations).toBe(5000 + 600 - 1500); // 4100
    expect(s.provinces.a.loyalty).toBe(72);
  });

  it('applyEconomy: 兵糧不足で餓死＋民忠-5', () => {
    const s = createInitialState(makeTestScenario(), 'd1');
    s.provinces.a.rations = 0;            // 収入600 < 維持1500 → 不足900
    applyEconomy(s);
    expect(s.provinces.a.rations).toBe(0);
    expect(s.provinces.a.troops).toBe(3000 - 1800); // lost = 900/0.5
    expect(s.provinces.a.loyalty).toBe(65);
  });
});
```

- [ ] **Step 2: 実行して失敗を確認**

Run: `npm test -- economy`
Expected: FAIL（module not found）

- [ ] **Step 3: 実装**

`src/engine/economy.js`:
```js
export const GOLD_FACTOR = 8;
export const RATIONS_FACTOR = 30;
export const SEASON_RATION = [1.0, 1.0, 2.0, 0.5]; // 春/夏/秋/冬
export const UPKEEP_PER_TROOP = 0.5;
export const LOYALTY_REGEN = 2;
export const STARVE_LOYALTY_PENALTY = 5;

export function goldIncome(p) {
  return Math.round(p.baseKokudaka * (p.commerce / 100) * (0.5 + p.loyalty / 200) * GOLD_FACTOR);
}

export function rationIncome(p, season) {
  return Math.round(p.baseKokudaka * (p.agri / 100) * SEASON_RATION[season] * RATIONS_FACTOR);
}

export function upkeep(p) {
  return Math.round(p.troops * UPKEEP_PER_TROOP);
}

// state を更新し、発生イベントの配列を返す
export function applyEconomy(state) {
  const events = [];
  for (const p of Object.values(state.provinces)) {
    state.daimyo[p.owner].gold += goldIncome(p);
    p.rations += rationIncome(p, state.season);
    const up = upkeep(p);
    if (p.rations >= up) {
      p.rations -= up;
      p.loyalty = Math.min(100, p.loyalty + LOYALTY_REGEN);
    } else {
      const deficit = up - p.rations;
      p.rations = 0;
      const lost = Math.round(deficit / UPKEEP_PER_TROOP);
      p.troops = Math.max(0, p.troops - lost);
      p.loyalty = Math.max(0, p.loyalty - STARVE_LOYALTY_PENALTY);
      events.push({ turn: `${state.year}-${state.season}`, type: 'starvation',
        text: `${p.name}で兵糧不足。兵${lost}を失った` });
    }
  }
  return events;
}
```

- [ ] **Step 4: 実行して成功を確認**

Run: `npm test -- economy`
Expected: 5 passed

- [ ] **Step 5: コミット**

```bash
git add src/engine/economy.js tests/economy.test.js
git commit -m "$(printf 'feat: add economy (income, upkeep, loyalty)\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

## Task 4: combat.js（合戦自動解決）

**Files:**
- Create: `src/engine/combat.js`
- Test: `tests/combat.test.js`

- [ ] **Step 1: 失敗するテストを書く**

`tests/combat.test.js`:
```js
import { describe, it, expect } from 'vitest';
import { fixed } from './helpers.js';
import { terrainMul, resolveBattle } from '../src/engine/combat.js';

describe('combat', () => {
  it('terrainMul: plain1.0 / coast1.1 / mountain1.3 / 既定1.0', () => {
    expect(terrainMul('plain')).toBe(1.0);
    expect(terrainMul('coast')).toBe(1.1);
    expect(terrainMul('mountain')).toBe(1.3);
    expect(terrainMul('unknown')).toBe(1.0);
  });

  it('攻撃側が圧倒すると captured=true、守備は壊走', () => {
    const r = resolveBattle(
      { atkTroops:5000, atkValor:80, atkTrained:false,
        defTroops:1000, defValor:50, terrain:'plain', castle:20 },
      fixed(0.5), // roll = 0.85 + 0.5*0.30 = 1.0
    );
    // attackPower=9000, defensePower=1800, ratio=5
    expect(r.captured).toBe(true);
    expect(r.atkLosses).toBe(300);   // 5000*clamp(0.30/5=0.06)
    expect(r.defLosses).toBe(1000);  // routed
  });

  it('攻撃側が劣勢だと captured=false、両者損耗', () => {
    const r = resolveBattle(
      { atkTroops:1000, atkValor:50, atkTrained:false,
        defTroops:3000, defValor:70, terrain:'mountain', castle:30 },
      fixed(0.5),
    );
    // attackPower=1500, defensePower=8619, ratio≈0.174
    expect(r.captured).toBe(false);
    expect(r.atkLosses).toBe(252);   // 1000*clamp(0.30*0.174+0.20)
    expect(r.defLosses).toBe(150);   // 3000*clamp(0.25*0.174→0.05)
  });

  it('守備兵0なら captured=true', () => {
    const r = resolveBattle(
      { atkTroops:1000, atkValor:50, atkTrained:false,
        defTroops:0, defValor:50, terrain:'plain', castle:0 },
      fixed(0.5),
    );
    expect(r.captured).toBe(true);
  });
});
```

- [ ] **Step 2: 実行して失敗を確認**

Run: `npm test -- combat`
Expected: FAIL（module not found）

- [ ] **Step 3: 実装**

`src/engine/combat.js`:
```js
import { clamp } from './util.js';

export function terrainMul(terrain) {
  switch (terrain) {
    case 'coast': return 1.1;
    case 'mountain': return 1.3;
    default: return 1.0; // plain / 未知
  }
}

// 純粋関数。rng は () => [0,1)
export function resolveBattle(p, rng = Math.random) {
  const atkRoll = 0.85 + rng() * 0.30;
  const defRoll = 0.85 + rng() * 0.30;
  const attackPower = p.atkTroops * (1 + p.atkValor / 100)
    * (p.atkTrained ? 1.1 : 1.0) * atkRoll;
  const defensePower = p.defTroops * (1 + p.defValor / 100)
    * terrainMul(p.terrain) * (1 + p.castle / 100) * defRoll;
  const ratio = defensePower === 0 ? Infinity : attackPower / defensePower;
  const captured = ratio >= 1;

  let atkLosses;
  let defLosses;
  if (captured) {
    atkLosses = Math.round(p.atkTroops * clamp(0.30 / ratio, 0.05, 0.60));
    defLosses = p.defTroops; // 壊走
  } else {
    atkLosses = Math.round(p.atkTroops * clamp(0.30 * ratio + 0.20, 0.10, 0.70));
    defLosses = Math.round(p.defTroops * clamp(0.25 * ratio, 0.05, 0.50));
  }
  return { attackPower, defensePower, ratio, atkLosses, defLosses, captured };
}
```

- [ ] **Step 4: 実行して成功を確認**

Run: `npm test -- combat`
Expected: 4 passed

- [ ] **Step 5: コミット**

```bash
git add src/engine/combat.js tests/combat.test.js
git commit -m "$(printf 'feat: add auto-resolve combat\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

## Task 5: diplomacy.js（同盟）

**Files:**
- Create: `src/engine/diplomacy.js`
- Test: `tests/diplomacy.test.js`

- [ ] **Step 1: 失敗するテストを書く**

`tests/diplomacy.test.js`:
```js
import { describe, it, expect } from 'vitest';
import { makeTestScenario, fixed } from './helpers.js';
import { createInitialState, areAllied } from '../src/engine/state.js';
import { evaluateAllianceProposal, formAlliance, breakAlliance } from '../src/engine/diplomacy.js';

describe('diplomacy', () => {
  it('弱者から強者(aggressive)への提案は拒否されやすい', () => {
    // d1(strength5000) → d2(strength7500): ratio0.667→base0.2, d2 aggressive -0.2 → 0
    const s = createInitialState(makeTestScenario(), 'd1');
    expect(evaluateAllianceProposal(s, 'd1', 'd2', fixed(0.0))).toBe(false);
  });

  it('強者から弱者(balanced)への提案は受諾されやすい', () => {
    // d2(7500) → d1(5000): ratio1.5→base0.7, d1 balanced 0 → 0.7
    const s = createInitialState(makeTestScenario(), 'd1');
    expect(evaluateAllianceProposal(s, 'd2', 'd1', fixed(0.5))).toBe(true);  // 0.5<0.7
    expect(evaluateAllianceProposal(s, 'd2', 'd1', fixed(0.9))).toBe(false); // 0.9>0.7
  });

  it('formAlliance / breakAlliance が双方向に効く', () => {
    const s = createInitialState(makeTestScenario(), 'd1');
    formAlliance(s, 'd1', 'd2');
    expect(areAllied(s, 'd2', 'd1')).toBe(true);
    formAlliance(s, 'd1', 'd2'); // 二重追加されない
    expect(s.alliances.length).toBe(1);
    breakAlliance(s, 'd2', 'd1');
    expect(areAllied(s, 'd1', 'd2')).toBe(false);
  });
});
```

- [ ] **Step 2: 実行して失敗を確認**

Run: `npm test -- diplomacy`
Expected: FAIL（module not found）

- [ ] **Step 3: 実装**

`src/engine/diplomacy.js`:
```js
import { areAllied, daimyoStrength } from './state.js';
import { clamp } from './util.js';

const PERSONALITY_BONUS = { aggressive: -0.2, balanced: 0.0, defensive: 0.2 };

// 受け手 toId が fromId の同盟提案を受諾するか（純粋判定）
export function evaluateAllianceProposal(state, fromId, toId, rng = Math.random) {
  const ratio = daimyoStrength(state, fromId) / daimyoStrength(state, toId);
  let chance;
  if (ratio >= 1.2) chance = 0.7;       // 提案者が強い → 庇護を得たい
  else if (ratio <= 0.8) chance = 0.2;  // 提案者が弱い → 旨味少ない
  else chance = 0.4;
  chance = clamp(chance + (PERSONALITY_BONUS[state.daimyo[toId].aiPersonality] ?? 0), 0, 1);
  return rng() < chance;
}

export function formAlliance(state, a, b) {
  if (!areAllied(state, a, b)) state.alliances.push([a, b]);
}

export function breakAlliance(state, a, b) {
  state.alliances = state.alliances.filter(
    ([x, y]) => !((x === a && y === b) || (x === b && y === a)),
  );
}
```

- [ ] **Step 4: 実行して成功を確認**

Run: `npm test -- diplomacy`
Expected: 3 passed

- [ ] **Step 5: コミット**

```bash
git add src/engine/diplomacy.js tests/diplomacy.test.js
git commit -m "$(printf 'feat: add alliance diplomacy\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

## Task 6: victory.js（滅亡処理・勝敗判定）

**Files:**
- Create: `src/engine/victory.js`
- Test: `tests/victory.test.js`

- [ ] **Step 1: 失敗するテストを書く**

`tests/victory.test.js`:
```js
import { describe, it, expect } from 'vitest';
import { makeTestScenario } from './helpers.js';
import { createInitialState, areAllied } from '../src/engine/state.js';
import { provinceCount, updateEliminations, checkStatus } from '../src/engine/victory.js';

describe('victory', () => {
  it('provinceCount は所有国数', () => {
    const s = createInitialState(makeTestScenario(), 'd1');
    expect(provinceCount(s, 'd2')).toBe(2);
  });

  it('版図0の大名は滅亡し、同盟も掃除される', () => {
    const s = createInitialState(makeTestScenario(), 'd1');
    s.alliances.push(['d1', 'd2']);
    s.provinces.b.owner = 'd1';
    s.provinces.c.owner = 'd1'; // d2 の版図0
    const ev = updateEliminations(s);
    expect(s.daimyo.d2.alive).toBe(false);
    expect(areAllied(s, 'd1', 'd2')).toBe(false);
    expect(ev.some(e => e.type === 'elimination')).toBe(true);
  });

  it('本拠陥落でも他国が残れば本拠を移転して存続', () => {
    const s = createInitialState(makeTestScenario(), 'd1');
    s.provinces.b.owner = 'd1';        // d1 は a,b を保有・本拠a
    s.provinces.a.owner = 'd2';        // 本拠a を失う（bは残る）
    updateEliminations(s);
    expect(s.daimyo.d1.alive).toBe(true);
    expect(s.daimyo.d1.capital).toBe('b');
  });

  it('checkStatus: 全国掌握で won / プレイヤー消滅で lost', () => {
    const s = createInitialState(makeTestScenario(), 'd1');
    s.provinces.b.owner = 'd1';
    s.provinces.c.owner = 'd1';
    updateEliminations(s);
    expect(checkStatus(s)).toBe('won');

    const s2 = createInitialState(makeTestScenario(), 'd1');
    s2.provinces.a.owner = 'd2';
    updateEliminations(s2);
    expect(checkStatus(s2)).toBe('lost');
  });
});
```

- [ ] **Step 2: 実行して失敗を確認**

Run: `npm test -- victory`
Expected: FAIL（module not found）

- [ ] **Step 3: 実装**

`src/engine/victory.js`:
```js
import { provincesOf } from './state.js';

export function provinceCount(state, daimyoId) {
  return provincesOf(state, daimyoId).length;
}

function removeAllAlliancesOf(state, daimyoId) {
  state.alliances = state.alliances.filter(([x, y]) => x !== daimyoId && y !== daimyoId);
}

// 滅亡処理＋本拠移転。発生イベント配列を返す
export function updateEliminations(state) {
  const events = [];
  for (const d of Object.values(state.daimyo)) {
    if (!d.alive) continue;
    const owned = provincesOf(state, d.id);
    if (owned.length === 0) {
      d.alive = false;
      removeAllAlliancesOf(state, d.id);
      events.push({ turn: `${state.year}-${state.season}`, type: 'elimination',
        text: `${d.name}が滅亡した` });
    } else if (state.provinces[d.capital]?.owner !== d.id) {
      // 本拠を失ったが他国は残る → 残存国の先頭へ移転
      d.capital = owned[0].id;
      events.push({ turn: `${state.year}-${state.season}`, type: 'capital_move',
        text: `${d.name}が本拠を${owned[0].name}へ移した` });
    }
  }
  return events;
}

// 勝敗を判定して state.status を更新し、文字列を返す
export function checkStatus(state) {
  const total = Object.keys(state.provinces).length;
  const player = state.daimyo[state.playerId];
  if (!player.alive) state.status = 'lost';
  else if (provinceCount(state, state.playerId) === total) state.status = 'won';
  else state.status = 'playing';
  return state.status;
}
```

- [ ] **Step 4: 実行して成功を確認**

Run: `npm test -- victory`
Expected: 4 passed

- [ ] **Step 5: コミット**

```bash
git add src/engine/victory.js tests/victory.test.js
git commit -m "$(printf 'feat: add elimination and victory checks\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

## Task 7: ai.js（AI意思決定）

**Files:**
- Create: `src/ai/ai.js`
- Test: `tests/ai.test.js`

- [ ] **Step 1: 失敗するテストを書く**

`tests/ai.test.js`:
```js
import { describe, it, expect } from 'vitest';
import { makeTestScenario, fixed } from './helpers.js';
import { createInitialState } from '../src/engine/state.js';
import { decideActions } from '../src/ai/ai.js';

describe('ai.decideActions', () => {
  it('aggressive大名は資金があれば徴兵し、勝てない敵には出陣しない', () => {
    const s = createInitialState(makeTestScenario(), 'd1'); // d2=aggressive, b,c所有
    const acts = decideActions(s, 'd2', fixed(0.5));
    expect(acts.filter(a => a.type === 'recruit').length).toBe(2); // b,c
    expect(acts.some(a => a.type === 'attack')).toBe(false);        // d2はd1に勝てない
  });

  it('勝てる弱い隣国には出陣する', () => {
    const s = createInitialState(makeTestScenario(), 'd1');
    s.daimyo.d1.aiPersonality = 'aggressive';
    s.provinces.a.troops = 8000;   // 圧倒的
    s.provinces.b.troops = 500;    // 弱い隣国(d2)
    s.provinces.b.castle = 5;
    const acts = decideActions(s, 'd1', fixed(0.5));
    expect(acts.some(a => a.type === 'attack' && a.from === 'a' && a.to === 'b')).toBe(true);
  });

  it('返すアクションは必ず自分の所有国を参照する', () => {
    const s = createInitialState(makeTestScenario(), 'd1');
    const acts = decideActions(s, 'd2', fixed(0.5));
    const owned = new Set(['b', 'c']);
    for (const a of acts) {
      if (a.province) expect(owned.has(a.province)).toBe(true);
      if (a.from) expect(owned.has(a.from)).toBe(true);
    }
  });
});
```

- [ ] **Step 2: 実行して失敗を確認**

Run: `npm test -- ai`
Expected: FAIL（module not found）

- [ ] **Step 3: 実装**

`src/ai/ai.js`:
```js
import { provincesOf, daimyoStrength, areAllied } from '../engine/state.js';
import { terrainMul } from '../engine/combat.js';

export const RECRUIT_COST = 200;
export const DEVELOP_COST = 100;
export const RECRUIT_TARGET = 4000;
export const AGGRO = { aggressive: 0.9, balanced: 1.1, defensive: 1.4 };
export const ALLIANCE_RATIO = 1.5;

// 純粋関数: state は読むだけ、アクション配列を返す
export function decideActions(state, daimyoId, rng = Math.random) {
  const me = state.daimyo[daimyoId];
  const mine = provincesOf(state, daimyoId);
  const actions = [];
  let gold = me.gold;

  // 1) 内政：各国に最大1つ
  for (const p of mine) {
    if (gold >= RECRUIT_COST && me.aiPersonality === 'aggressive' && p.troops < RECRUIT_TARGET) {
      actions.push({ type: 'recruit', province: p.id });
      gold -= RECRUIT_COST;
    } else if (gold >= DEVELOP_COST) {
      const kind = p.agri <= p.commerce ? 'agri' : 'commerce';
      actions.push({ type: 'develop', province: p.id, kind });
      gold -= DEVELOP_COST;
    }
  }

  // 2) 軍事：勝てそうな隣接敵国へ（defensive は出陣しない）
  if (me.aiPersonality !== 'defensive') {
    let best = null; // { from, to, defScore }
    for (const p of mine) {
      for (const nId of p.neighbors) {
        const n = state.provinces[nId];
        if (!n || n.owner === daimyoId) continue;
        if (areAllied(state, daimyoId, n.owner)) continue;
        const estAtk = p.troops * (1 + me.stats.valor / 100);
        const defValor = state.daimyo[n.owner].stats.valor;
        const estDef = n.troops * (1 + defValor / 100) * terrainMul(n.terrain) * (1 + n.castle / 100);
        if (estAtk > estDef * AGGRO[me.aiPersonality] && p.troops > 0) {
          if (!best || estDef < best.defScore) best = { from: p.id, to: n.id, defScore: estDef };
        }
      }
    }
    if (best) actions.push({ type: 'attack', from: best.from, to: best.to,
      troops: state.provinces[best.from].troops });
  }

  // 3) 外交：自分よりはるかに強い隣接勢力へ同盟提案
  const neighborsDaimyo = new Set();
  for (const p of mine) {
    for (const nId of p.neighbors) {
      const n = state.provinces[nId];
      if (n && n.owner !== daimyoId) neighborsDaimyo.add(n.owner);
    }
  }
  let target = null; let targetStr = 0;
  const myStr = daimyoStrength(state, daimyoId);
  for (const otherId of neighborsDaimyo) {
    if (areAllied(state, daimyoId, otherId)) continue;
    const s = daimyoStrength(state, otherId);
    if (s / myStr >= ALLIANCE_RATIO && s > targetStr) { target = otherId; targetStr = s; }
  }
  if (target && (me.aiPersonality === 'defensive' || rng() < 0.3)) {
    actions.push({ type: 'propose_alliance', to: target });
  }

  return actions;
}
```

- [ ] **Step 4: 実行して成功を確認**

Run: `npm test -- ai`
Expected: 3 passed

- [ ] **Step 5: コミット**

```bash
git add src/ai/ai.js tests/ai.test.js
git commit -m "$(printf 'feat: add AI decision making\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

## Task 8: turn.js（ターン進行統括）

**Files:**
- Create: `src/engine/turn.js`
- Test: `tests/turn.test.js`

- [ ] **Step 1: 失敗するテストを書く**

`tests/turn.test.js`:
```js
import { describe, it, expect } from 'vitest';
import { makeTestScenario, fixed } from './helpers.js';
import { createInitialState } from '../src/engine/state.js';
import { applyAction, startSeason, runAIPhase, endTurn } from '../src/engine/turn.js';

describe('turn.applyAction', () => {
  it('develop: 開発度+gain・金-100', () => {
    const s = createInitialState(makeTestScenario(), 'd1');
    applyAction(s, 'd1', { type:'develop', province:'a', kind:'commerce' }, fixed(0.5));
    expect(s.provinces.a.commerce).toBe(40 + 9); // round(5+70/20)=9
    expect(s.daimyo.d1.gold).toBe(2000 - 100);
  });

  it('recruit: 兵力+gain・民忠-8・金-200', () => {
    const s = createInitialState(makeTestScenario(), 'd1');
    applyAction(s, 'd1', { type:'recruit', province:'a' }, fixed(0.5));
    expect(s.provinces.a.troops).toBe(3000 + 1080); // round(800+70*4)
    expect(s.provinces.a.loyalty).toBe(70 - 8);
    expect(s.daimyo.d1.gold).toBe(2000 - 200);
  });

  it('attack 成功: 所有者が変わり守備兵が入れ替わる', () => {
    const s = createInitialState(makeTestScenario(), 'd1');
    s.provinces.a.troops = 8000; // 圧勝条件
    s.provinces.b.troops = 500;
    s.provinces.b.castle = 5;
    applyAction(s, 'd1', { type:'attack', from:'a', to:'b', troops:8000 }, fixed(0.5));
    expect(s.provinces.b.owner).toBe('d1');
    expect(s.provinces.a.troops).toBe(0); // 出撃して空に
    expect(s.provinces.b.troops).toBeGreaterThan(0); // 残存兵が駐留
  });

  it('attack 不正(非隣接)は無視される', () => {
    const s = createInitialState(makeTestScenario(), 'd1');
    const before = JSON.stringify(s.provinces);
    applyAction(s, 'd1', { type:'attack', from:'a', to:'c', troops:3000 }, fixed(0.5)); // a-c は非隣接
    expect(JSON.stringify(s.provinces)).toBe(before);
  });

  it('金不足の develop は無視される', () => {
    const s = createInitialState(makeTestScenario(), 'd1');
    s.daimyo.d1.gold = 50;
    applyAction(s, 'd1', { type:'develop', province:'a', kind:'agri' }, fixed(0.5));
    expect(s.provinces.a.agri).toBe(40);
    expect(s.daimyo.d1.gold).toBe(50);
  });
});

describe('turn flow', () => {
  it('startSeason は経済を適用し金が増える', () => {
    const s = createInitialState(makeTestScenario(), 'd1');
    startSeason(s);
    expect(s.daimyo.d1.gold).toBe(2000 + 136);
  });

  it('endTurn: AI行動後に季節が進み status は playing', () => {
    const s = createInitialState(makeTestScenario(), 'd1');
    endTurn(s, fixed(0.5));
    expect(s.season).toBe(1);
    expect(['playing','won','lost']).toContain(s.status);
  });

  it('endTurn: 冬→春で年が進む', () => {
    const s = createInitialState(makeTestScenario(), 'd1');
    s.season = 3;
    endTurn(s, fixed(0.5));
    expect(s.season).toBe(0);
    expect(s.year).toBe(1561);
  });
});
```

- [ ] **Step 2: 実行して失敗を確認**

Run: `npm test -- turn`
Expected: FAIL（module not found）

- [ ] **Step 3: 実装**

`src/engine/turn.js`:
```js
import { provincesOf, areAllied } from './state.js';
import { applyEconomy } from './economy.js';
import { resolveBattle } from './combat.js';
import { evaluateAllianceProposal, formAlliance } from './diplomacy.js';
import { updateEliminations, checkStatus } from './victory.js';
import { decideActions } from '../ai/ai.js';

export const DEVELOP_COST = 100;
export const RECRUIT_COST = 200;
export const RECRUIT_LOYALTY_COST = 8;
export const NEW_CONQUEST_LOYALTY = 50;

function log(state, type, text) {
  state.log.push({ turn: `${state.year}-${state.season}`, type, text });
}

// 1アクションを適用（検証込み）。state を更新する。
export function applyAction(state, daimyoId, action, rng = Math.random) {
  const d = state.daimyo[daimyoId];
  if (!d || !d.alive) return;

  if (action.type === 'develop') {
    const p = state.provinces[action.province];
    if (!p || p.owner !== daimyoId || d.gold < DEVELOP_COST) return;
    const gain = Math.round(5 + d.stats.politics / 20);
    if (action.kind === 'agri') p.agri = Math.min(100, p.agri + gain);
    else p.commerce = Math.min(100, p.commerce + gain);
    d.gold -= DEVELOP_COST;
    return;
  }

  if (action.type === 'recruit') {
    const p = state.provinces[action.province];
    if (!p || p.owner !== daimyoId || d.gold < RECRUIT_COST) return;
    const gain = Math.round(800 + d.stats.politics * 4);
    p.troops += gain;
    p.loyalty = Math.max(0, p.loyalty - RECRUIT_LOYALTY_COST);
    d.gold -= RECRUIT_COST;
    return;
  }

  if (action.type === 'train') {
    const p = state.provinces[action.province];
    if (!p || p.owner !== daimyoId) return;
    p.trained = true;
    return;
  }

  if (action.type === 'attack') {
    const from = state.provinces[action.from];
    const to = state.provinces[action.to];
    if (!from || !to) return;
    if (from.owner !== daimyoId) return;
    if (to.owner === daimyoId) return;
    if (!from.neighbors.includes(to.id)) return;
    if (areAllied(state, daimyoId, to.owner)) return;
    if (from.troops <= 0) return;

    const atkTroops = from.troops;
    from.troops = 0; // 出撃
    const result = resolveBattle({
      atkTroops,
      atkValor: d.stats.valor,
      atkTrained: from.trained === true,
      defTroops: to.troops,
      defValor: state.daimyo[to.owner].stats.valor,
      terrain: to.terrain,
      castle: to.castle,
    }, rng);
    from.trained = false;

    const survivors = Math.max(0, atkTroops - result.atkLosses);
    if (result.captured) {
      const loserId = to.owner;
      const loserName = state.daimyo[loserId].name;
      to.owner = daimyoId;
      to.troops = survivors;
      to.loyalty = NEW_CONQUEST_LOYALTY;
      to.trained = false;
      log(state, 'battle', `${d.name}が${to.name}を攻略（対${loserName}）`);
    } else {
      to.troops = Math.max(0, to.troops - result.defLosses);
      from.troops = survivors; // 撤退して帰還
      log(state, 'battle', `${d.name}の${to.name}攻めは失敗`);
    }
    return;
  }

  if (action.type === 'propose_alliance') {
    const toId = action.to;
    if (!state.daimyo[toId] || !state.daimyo[toId].alive) return;
    if (areAllied(state, daimyoId, toId)) return;
    if (evaluateAllianceProposal(state, daimyoId, toId, rng)) {
      formAlliance(state, daimyoId, toId);
      log(state, 'diplomacy', `${d.name}と${state.daimyo[toId].name}が同盟`);
    } else {
      log(state, 'diplomacy', `${state.daimyo[toId].name}は同盟を拒否`);
    }
  }
}

// 季節開始：経済適用
export function startSeason(state) {
  const ev = applyEconomy(state);
  for (const e of ev) state.log.push(e);
  return ev;
}

// 全AI大名の行動
export function runAIPhase(state, rng = Math.random) {
  for (const id of Object.keys(state.daimyo)) {
    const d = state.daimyo[id];
    if (!d.alive || d.isPlayer) continue;
    for (const action of decideActions(state, id, rng)) {
      applyAction(state, id, action, rng);
    }
  }
}

// 季節を1つ進める
function advanceSeason(state) {
  state.season = (state.season + 1) % 4;
  if (state.season === 0) state.year += 1;
}

// 「ターン終了」: AI→滅亡処理→勝敗判定→（継続なら）次季節開始
export function endTurn(state, rng = Math.random) {
  runAIPhase(state, rng);
  for (const e of updateEliminations(state)) state.log.push(e);
  checkStatus(state);
  if (state.status === 'playing') {
    advanceSeason(state);
    startSeason(state);
    for (const e of updateEliminations(state)) state.log.push(e);
    checkStatus(state);
  }
  return state.status;
}
```

- [ ] **Step 4: 実行して成功を確認**

Run: `npm test -- turn`
Expected: 8 passed

- [ ] **Step 5: 全テスト実行（回帰確認）**

Run: `npm test`
Expected: ここまでの全テスト pass（util/state/economy/combat/diplomacy/victory/ai/turn/smoke）

- [ ] **Step 6: コミット**

```bash
git add src/engine/turn.js tests/turn.test.js
git commit -m "$(printf 'feat: add turn orchestration (actions, AI phase, end turn)\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

## Task 9: 史実データ（provinces.js / daimyo.js）＋整合テスト

> **このタスクはコードではなくデータ整備**。正しさは「整合テスト（完全なコードとして下に定義）」が機械的に保証する。整合テストを**先に**書き、それを満たすように 60超の国・1560年版図・大名ロスターを埋める。データ量が多いため、編纂には deep-research スキルや Workflow（複数エージェントで編纂→突き合わせ）を活用してよい。能力値・石高は「史実の雰囲気を出す簡略値」とし、**隣接対称性・所属網羅・本拠妥当性などの構造**をテストで担保する。

**Files:**
- Create: `src/data/provinces.js`
- Create: `src/data/daimyo.js`
- Test: `tests/data.test.js`

- [ ] **Step 1: 整合テストを書く（これがデータの仕様）**

`tests/data.test.js`:
```js
import { describe, it, expect } from 'vitest';
import { PROVINCES } from '../src/data/provinces.js';
import { DAIMYO, SCENARIO_1560 } from '../src/data/daimyo.js';

const byId = Object.fromEntries(PROVINCES.map(p => [p.id, p]));
const daimyoIds = new Set(DAIMYO.map(d => d.id));

describe('province data integrity', () => {
  it('60国以上ある', () => {
    expect(PROVINCES.length).toBeGreaterThanOrEqual(60);
  });
  it('id は一意', () => {
    expect(new Set(PROVINCES.map(p => p.id)).size).toBe(PROVINCES.length);
  });
  it('座標は 0..1 の範囲', () => {
    for (const p of PROVINCES) {
      expect(p.x).toBeGreaterThanOrEqual(0); expect(p.x).toBeLessThanOrEqual(1);
      expect(p.y).toBeGreaterThanOrEqual(0); expect(p.y).toBeLessThanOrEqual(1);
    }
  });
  it('隣接は実在ID・自己参照なし・双方向対称', () => {
    for (const p of PROVINCES) {
      for (const n of p.neighbors) {
        expect(n).not.toBe(p.id);
        expect(byId[n], `${p.id}->${n}`).toBeTruthy();
        expect(byId[n].neighbors).toContain(p.id);
      }
    }
  });
  it('グラフは連結（孤立国なし）', () => {
    const seen = new Set([PROVINCES[0].id]);
    const stack = [PROVINCES[0].id];
    while (stack.length) {
      const cur = byId[stack.pop()];
      for (const n of cur.neighbors) if (!seen.has(n)) { seen.add(n); stack.push(n); }
    }
    expect(seen.size).toBe(PROVINCES.length);
  });
  it('所有者は実在の大名ID', () => {
    for (const p of PROVINCES) expect(daimyoIds.has(p.owner), p.id).toBe(true);
  });
  it('terrain は既定値のいずれか', () => {
    for (const p of PROVINCES) expect(['plain','coast','mountain']).toContain(p.terrain);
  });
});

describe('daimyo data integrity', () => {
  it('id は一意', () => {
    expect(new Set(DAIMYO.map(d => d.id)).size).toBe(DAIMYO.length);
  });
  it('能力値は 1..100', () => {
    for (const d of DAIMYO) for (const k of ['valor','politics','intellect']) {
      expect(d.stats[k]).toBeGreaterThanOrEqual(1);
      expect(d.stats[k]).toBeLessThanOrEqual(100);
    }
  });
  it('全大名が1国以上を所有', () => {
    const owners = new Set(PROVINCES.map(p => p.owner));
    for (const d of DAIMYO) expect(owners.has(d.id), d.id).toBe(true);
  });
  it('本拠は自領内', () => {
    for (const d of DAIMYO) expect(byId[d.capital]?.owner, d.id).toBe(d.id);
  });
  it('aiPersonality は既定値のいずれか', () => {
    for (const d of DAIMYO) expect(['aggressive','balanced','defensive']).toContain(d.aiPersonality);
  });
});

describe('scenario', () => {
  it('SCENARIO_1560 が provinces/daimyo を内包し year=1560', () => {
    expect(SCENARIO_1560.year).toBe(1560);
    expect(SCENARIO_1560.provinces.length).toBe(PROVINCES.length);
    expect(SCENARIO_1560.daimyo.length).toBe(DAIMYO.length);
  });
});
```

- [ ] **Step 2: 実行して失敗を確認**

Run: `npm test -- data`
Expected: FAIL（module not found）

- [ ] **Step 3: provinces.js を作成（下の形式で60国超を網羅）**

`src/data/provinces.js`（形式の具体例。実際は旧国名を網羅し、整合テストを満たすこと）:
```js
// 各国: 動的状態(owner/agri/commerce/troops/castle/loyalty/rations)の初期値込み。
// 座標は日本列島を 0..1 に正規化したおおよその位置（西=小x, 北=小y）。
export const PROVINCES = [
  // —— 中部・東海（例。本拠・隣接の形式を示す）——
  { id:'owari', name:'尾張', region:'東海', x:0.560, y:0.520, terrain:'plain',
    neighbors:['mino','mikawa','ise','iga_n'], baseKokudaka:57,
    owner:'oda', agri:45, commerce:55, troops:4000, castle:25, loyalty:70, rations:8000 },
  { id:'mikawa', name:'三河', region:'東海', x:0.585, y:0.530, terrain:'plain',
    neighbors:['owari','totomi','shinano_s'], baseKokudaka:35,
    owner:'imagawa', agri:40, commerce:35, troops:2500, castle:20, loyalty:65, rations:5000 },
  { id:'mino', name:'美濃', region:'東海', x:0.555, y:0.485, terrain:'mountain',
    neighbors:['owari','hida','shinano_w','omi_e','ise'], baseKokudaka:54,
    owner:'saito', agri:40, commerce:40, troops:3000, castle:25, loyalty:60, rations:6000 },
  // … 以降、近畿/中国/四国/九州/北陸/関東/東北/甲信越/島嶼 を網羅して
  //    PROVINCES.length >= 60 とし、整合テスト（隣接対称・連結・所属網羅）を満たす。
];
```

> 編纂指針（整合テストを満たすための必須ルール）:
> 1. 旧国名（尾張・三河…）を 60国以上列挙。海を挟む隣接（例: 安芸—伊予、薩摩—大隅と日向、淡路経由など）は妥当な海路として `coast` の国同士を相互に隣接させ、四国・九州・本州・北海道南部が**1つの連結グラフ**になるようにする。
> 2. `neighbors` は必ず**双方向**で記述（A に B を入れたら B にも A を入れる）。
> 3. 1560年時点の主要勢力の版図に沿って `owner` を割当（織田=尾張、今川=駿河遠江三河、武田=甲斐信濃、上杉=越後、北条=相模武蔵、毛利=安芸ほか中国、長宗我部=土佐、島津=薩摩大隅 等）。判別が難しい小国は地域の有力大名 or 中小大名IDに寄せる。
> 4. `baseKokudaka` は史実石高の概数、`terrain` は地勢（山国=mountain、沿岸=coast、平野=plain）。

- [ ] **Step 4: daimyo.js を作成（主要＋中小大名）**

`src/data/daimyo.js`（形式の具体例。実際は provinces.js の owner を全て満たす大名を定義）:
```js
import { PROVINCES } from './provinces.js';

export const DAIMYO = [
  { id:'oda', name:'織田信長', family:'織田家', color:'#d23b3b', isPlayer:false, capital:'owari',
    stats:{ valor:87, politics:80, intellect:90 }, gold:3000, alive:true, aiPersonality:'aggressive' },
  { id:'imagawa', name:'今川義元', family:'今川家', color:'#d2a13b', isPlayer:false, capital:'suruga',
    stats:{ valor:75, politics:82, intellect:78 }, gold:3500, alive:true, aiPersonality:'balanced' },
  { id:'takeda', name:'武田信玄', family:'武田家', color:'#b03030', isPlayer:false, capital:'kai',
    stats:{ valor:92, politics:85, intellect:94 }, gold:3000, alive:true, aiPersonality:'aggressive' },
  { id:'uesugi', name:'上杉謙信', family:'上杉家', color:'#3b6fd2', isPlayer:false, capital:'echigo',
    stats:{ valor:96, politics:70, intellect:85 }, gold:2800, alive:true, aiPersonality:'aggressive' },
  { id:'hojo', name:'北条氏康', family:'北条家', color:'#3bb0a1', isPlayer:false, capital:'sagami',
    stats:{ valor:82, politics:90, intellect:84 }, gold:3200, alive:true, aiPersonality:'defensive' },
  { id:'mori', name:'毛利元就', family:'毛利家', color:'#6fae3b', isPlayer:false, capital:'aki',
    stats:{ valor:80, politics:88, intellect:97 }, gold:3000, alive:true, aiPersonality:'balanced' },
  // … provinces.js の全 owner を満たすよう、斎藤・長尾・島津・長宗我部・大友・
  //    龍造寺・浅井・朝倉・三好・里見・伊達・最上 などを必要数だけ定義する。
];

export const SCENARIO_1560 = {
  year: 1560,
  season: 0,
  playerId: 'oda',  // 既定。開始画面で上書きされる
  provinces: PROVINCES,
  daimyo: DAIMYO,
};
```

- [ ] **Step 5: 整合テストが通るまでデータを補完**

Run: `npm test -- data`
Expected: 全 integrity テスト pass（落ちたテストのメッセージで「どの国の隣接が非対称か」「所有者不明の国はどれか」等が分かるので、それを潰す）

- [ ] **Step 6: 手動スポットチェック**

主要大名の本拠と版図が史実の大枠と合っているか（織田＝尾張、武田＝甲斐信濃、上杉＝越後 等）を目視確認する。

- [ ] **Step 7: コミット**

```bash
git add src/data/provinces.js src/data/daimyo.js tests/data.test.js
git commit -m "$(printf 'feat: add 1560 historical provinces and daimyo dataset\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

## Task 10: index.html / styles.css（UI骨格）

**Files:**
- Modify: `index.html`
- Create: `styles.css`

- [ ] **Step 1: index.html を本実装の骨格に差し替え**

`index.html`:
```html
<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>戦国・国盗り</title>
  <link rel="stylesheet" href="styles.css" />
</head>
<body>
  <!-- 開始画面 -->
  <section id="start-screen">
    <h1>戦国・国盗り</h1>
    <p>大名を選んで天下統一を目指せ（1560年）</p>
    <div id="daimyo-picker"></div>
  </section>

  <!-- ゲーム画面 -->
  <main id="game-screen" hidden>
    <header id="topbar">
      <span id="turn-label"></span>
      <span id="player-stats"></span>
      <span id="topbar-actions">
        <button id="btn-save">セーブ</button>
        <button id="btn-load">ロード</button>
        <button id="btn-end-turn">ターン終了 ▶</button>
      </span>
    </header>
    <div id="layout">
      <div id="map-wrap"><svg id="map" viewBox="0 0 1000 1000" preserveAspectRatio="xMidYMid meet"></svg></div>
      <aside id="side-panel"></aside>
    </div>
    <footer id="bottom">
      <div id="log"></div>
      <div id="ranking"></div>
    </footer>
  </main>

  <!-- モーダル -->
  <div id="modal" hidden><div id="modal-box"><p id="modal-text"></p><button id="modal-ok">OK</button></div></div>

  <script type="module" src="src/main.js"></script>
</body>
</html>
```

- [ ] **Step 2: styles.css を作成**

`styles.css`:
```css
* { box-sizing: border-box; }
body { margin:0; font-family: system-ui, "Hiragino Kaku Gothic ProN", sans-serif;
  background:#1c1a17; color:#eee; }
button { cursor:pointer; background:#3a352e; color:#eee; border:1px solid #5a5247;
  border-radius:4px; padding:4px 10px; }
button:hover:not(:disabled) { background:#4a443b; }
button:disabled { opacity:.4; cursor:not-allowed; }

#start-screen { max-width:900px; margin:40px auto; text-align:center; }
#daimyo-picker { display:flex; flex-wrap:wrap; gap:10px; justify-content:center; margin-top:20px; }
.daimyo-card { border:1px solid #5a5247; border-radius:6px; padding:10px 14px; min-width:150px;
  background:#26231f; cursor:pointer; }
.daimyo-card:hover { background:#332f29; }
.daimyo-card .swatch { display:inline-block; width:12px; height:12px; border-radius:50%; margin-right:6px; }

#topbar { display:flex; align-items:center; gap:16px; padding:8px 14px; background:#2a2620;
  border-bottom:1px solid #443d33; }
#topbar-actions { margin-left:auto; display:flex; gap:8px; }
#layout { display:flex; height: calc(100vh - 210px); }
#map-wrap { flex:1; overflow:hidden; background:#10213a; }
#map { width:100%; height:100%; }
.prov-node { stroke:#0008; stroke-width:3; cursor:pointer; }
.prov-node.selected { stroke:#fff; stroke-width:6; }
.prov-link { stroke:#ffffff22; stroke-width:2; }
.prov-label { fill:#fff; font-size:18px; text-anchor:middle; pointer-events:none; }

#side-panel { width:300px; padding:12px; background:#22201c; overflow-y:auto; border-left:1px solid #443d33; }
.cmd-row { display:flex; gap:6px; flex-wrap:wrap; margin-top:8px; }
.stat { display:flex; justify-content:space-between; border-bottom:1px solid #ffffff14; padding:2px 0; }

#bottom { display:flex; height:150px; border-top:1px solid #443d33; }
#log { flex:1; overflow-y:auto; padding:8px; font-size:13px; }
#log .entry { border-bottom:1px solid #ffffff10; padding:2px 0; }
#ranking { width:260px; overflow-y:auto; padding:8px; border-left:1px solid #443d33; font-size:13px; }

#modal { position:fixed; inset:0; background:#000a; display:flex; align-items:center; justify-content:center; }
#modal-box { background:#2a2620; padding:24px; border-radius:8px; text-align:center; min-width:280px; }
```

- [ ] **Step 3: 表示確認**

Run: `python -m http.server 8000`（別ターミナル）→ ブラウザで http://localhost:8000 を開く
Expected: 「戦国・国盗り」の見出しが表示される（中身の配線は Task 14。エラーがコンソールに出ないこと）

- [ ] **Step 4: コミット**

```bash
git add index.html styles.css
git commit -m "$(printf 'feat: add UI skeleton (html, css)\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

## Task 11: ui/render.js（描画）

**Files:**
- Create: `src/ui/render.js`

> UIは手動確認のためユニットテストは作らない。`render(state, selectedId)` は state を読み取り DOM を再構築する純粋描画（副作用はDOM更新のみ）。ボタンには `data-*` 属性を付け、ハンドラ配線は Task 12/14 が担う。

- [ ] **Step 1: render.js を実装**

`src/ui/render.js`:
```js
import { provincesOf, totalTroops } from '../engine/state.js';
import { goldIncome } from '../engine/economy.js';

const SEASONS = ['春', '夏', '秋', '冬'];

export function renderTopbar(state) {
  document.getElementById('turn-label').textContent = `${state.year}年 ${SEASONS[state.season]}`;
  const p = state.daimyo[state.playerId];
  const provs = provincesOf(state, state.playerId).length;
  document.getElementById('player-stats').textContent =
    `${p.name}　金:${p.gold}　兵:${totalTroops(state, state.playerId)}　国:${provs}`;
}

export function renderMap(state, selectedId) {
  const svg = document.getElementById('map');
  svg.innerHTML = '';
  const X = (v) => v * 1000;
  const Y = (v) => v * 1000;
  // 隣接線（重複描画を避けるため id 昇順ペアのみ）
  for (const p of Object.values(state.provinces)) {
    for (const nId of p.neighbors) {
      if (p.id < nId && state.provinces[nId]) {
        const n = state.provinces[nId];
        const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        line.setAttribute('x1', X(p.x)); line.setAttribute('y1', Y(p.y));
        line.setAttribute('x2', X(n.x)); line.setAttribute('y2', Y(n.y));
        line.setAttribute('class', 'prov-link');
        svg.appendChild(line);
      }
    }
  }
  // ノード
  for (const p of Object.values(state.provinces)) {
    const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    const c = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    c.setAttribute('cx', X(p.x)); c.setAttribute('cy', Y(p.y));
    c.setAttribute('r', 16 + Math.min(14, p.troops / 700));
    c.setAttribute('fill', state.daimyo[p.owner].color);
    c.setAttribute('class', 'prov-node' + (p.id === selectedId ? ' selected' : ''));
    c.setAttribute('data-prov', p.id);
    g.appendChild(c);
    const t = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    t.setAttribute('x', X(p.x)); t.setAttribute('y', Y(p.y) - 22);
    t.setAttribute('class', 'prov-label');
    t.textContent = p.name;
    g.appendChild(t);
    svg.appendChild(g);
  }
}

function statRow(label, value) {
  return `<div class="stat"><span>${label}</span><span>${value}</span></div>`;
}

export function renderPanel(state, selectedId) {
  const panel = document.getElementById('side-panel');
  if (!selectedId) { panel.innerHTML = '<p>国を選択してください</p>'; return; }
  const p = state.provinces[selectedId];
  const owner = state.daimyo[p.owner];
  const isMine = p.owner === state.playerId;
  let html = `<h3>${p.name}（${p.region}）</h3>`;
  html += `<div style="color:${owner.color}">${owner.name}</div>`;
  html += statRow('石高', p.baseKokudaka) + statRow('兵力', p.troops)
    + statRow('農業', p.agri) + statRow('商業', p.commerce)
    + statRow('城防御', p.castle) + statRow('民忠', p.loyalty)
    + statRow('兵糧', p.rations) + statRow('地勢', p.terrain)
    + statRow('予想金収入', goldIncome(p));

  if (isMine) {
    html += `<div class="cmd-row">
      <button data-cmd="develop" data-kind="agri" data-prov="${p.id}">農業開発</button>
      <button data-cmd="develop" data-kind="commerce" data-prov="${p.id}">商業開発</button>
      <button data-cmd="recruit" data-prov="${p.id}">徴兵</button>
      <button data-cmd="train" data-prov="${p.id}">訓練</button>
    </div>`;
    // 出陣先（隣接する非同盟の敵国）
    const targets = p.neighbors
      .map(id => state.provinces[id])
      .filter(n => n && n.owner !== state.playerId);
    if (targets.length) {
      html += '<div class="cmd-row">';
      for (const t of targets) {
        html += `<button data-cmd="attack" data-from="${p.id}" data-to="${t.id}">${t.name}へ出陣</button>`;
      }
      html += '</div>';
    }
  } else {
    html += `<div class="cmd-row">
      <button data-cmd="propose_alliance" data-to="${p.owner}">${owner.name}に同盟提案</button>
    </div>`;
  }
  panel.innerHTML = html;
}

export function renderLog(state) {
  const log = document.getElementById('log');
  const recent = state.log.slice(-40).reverse();
  log.innerHTML = recent.map(e => `<div class="entry">[${e.turn}] ${e.text}</div>`).join('');
}

export function renderRanking(state) {
  const rank = Object.values(state.daimyo)
    .filter(d => d.alive)
    .map(d => ({ name: d.name, color: d.color, n: provincesOf(state, d.id).length }))
    .sort((a, b) => b.n - a.n)
    .slice(0, 12);
  document.getElementById('ranking').innerHTML =
    '<b>勢力ランキング</b>' + rank.map(r =>
      `<div class="stat"><span><span class="swatch" style="background:${r.color}"></span>${r.name}</span><span>${r.n}国</span></div>`
    ).join('');
}

export function render(state, selectedId) {
  renderTopbar(state);
  renderMap(state, selectedId);
  renderPanel(state, selectedId);
  renderLog(state);
  renderRanking(state);
}
```

- [ ] **Step 2: コミット**

```bash
git add src/ui/render.js
git commit -m "$(printf 'feat: add UI rendering (map, panel, log, ranking)\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

## Task 12: ui/input.js（イベント配線）

**Files:**
- Create: `src/ui/input.js`

> DOM全体に対しイベント委譲で1度だけリスナを張る。具体的なゲーム処理は `handlers` を通じて main.js に委ねる（UIはロジックを持たない）。

- [ ] **Step 1: input.js を実装**

`src/ui/input.js`:
```js
// handlers: {
//   onSelectProvince(id), onCommand(cmdEl), onEndTurn(),
//   onSave(), onLoad(), onPickDaimyo(id), onModalOk()
// }
export function wireUI(handlers) {
  // 地図クリック（ノード選択）
  document.getElementById('map').addEventListener('click', (e) => {
    const node = e.target.closest('[data-prov]');
    if (node) handlers.onSelectProvince(node.getAttribute('data-prov'));
  });

  // サイドパネルのコマンドボタン（委譲）
  document.getElementById('side-panel').addEventListener('click', (e) => {
    const btn = e.target.closest('[data-cmd]');
    if (btn) handlers.onCommand(btn);
  });

  // 開始画面の大名選択
  document.getElementById('daimyo-picker').addEventListener('click', (e) => {
    const card = e.target.closest('[data-daimyo]');
    if (card) handlers.onPickDaimyo(card.getAttribute('data-daimyo'));
  });

  document.getElementById('btn-end-turn').addEventListener('click', () => handlers.onEndTurn());
  document.getElementById('btn-save').addEventListener('click', () => handlers.onSave());
  document.getElementById('btn-load').addEventListener('click', () => handlers.onLoad());
  document.getElementById('modal-ok').addEventListener('click', () => handlers.onModalOk());
}
```

- [ ] **Step 2: コミット**

```bash
git add src/ui/input.js
git commit -m "$(printf 'feat: add UI event wiring (delegated handlers)\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

## Task 13: save.js（localStorage セーブ/ロード）

**Files:**
- Create: `src/engine/save.js`
- Test: `tests/save.test.js`

- [ ] **Step 1: 失敗するテストを書く**

`tests/save.test.js`:
```js
import { describe, it, expect } from 'vitest';
import { makeTestScenario } from './helpers.js';
import { createInitialState } from '../src/engine/state.js';
import { saveGame, loadGame, hasSave, SAVE_VERSION } from '../src/engine/save.js';

function fakeStorage() {
  const m = new Map();
  return { getItem:(k)=>m.has(k)?m.get(k):null, setItem:(k,v)=>m.set(k,String(v)), removeItem:(k)=>m.delete(k) };
}

describe('save/load', () => {
  it('保存→読込でラウンドトリップする', () => {
    const st = fakeStorage();
    const s = createInitialState(makeTestScenario(), 'd1');
    s.daimyo.d1.gold = 1234;
    saveGame(s, st);
    expect(hasSave(st)).toBe(true);
    const loaded = loadGame(st);
    expect(loaded.daimyo.d1.gold).toBe(1234);
    expect(loaded.provinces.a.name).toBe('A');
  });

  it('セーブが無ければ load は null', () => {
    expect(loadGame(fakeStorage())).toBe(null);
  });

  it('バージョン不一致は null（互換崩れ対策）', () => {
    const st = fakeStorage();
    st.setItem('sengoku_save', JSON.stringify({ version: SAVE_VERSION + 99, state: {} }));
    expect(loadGame(st)).toBe(null);
  });
});
```

- [ ] **Step 2: 実行して失敗を確認**

Run: `npm test -- save`
Expected: FAIL（module not found）

- [ ] **Step 3: 実装**

`src/engine/save.js`:
```js
export const SAVE_VERSION = 1;
const KEY = 'sengoku_save';

function storageOf(s) {
  return s ?? (typeof localStorage !== 'undefined' ? localStorage : null);
}

export function saveGame(state, s) {
  const store = storageOf(s);
  if (!store) return false;
  store.setItem(KEY, JSON.stringify({ version: SAVE_VERSION, state }));
  return true;
}

export function loadGame(s) {
  const store = storageOf(s);
  if (!store) return null;
  const raw = store.getItem(KEY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw);
    if (parsed.version !== SAVE_VERSION) return null;
    return parsed.state;
  } catch {
    return null;
  }
}

export function hasSave(s) {
  const store = storageOf(s);
  return !!(store && store.getItem(KEY));
}
```

- [ ] **Step 4: 実行して成功を確認**

Run: `npm test -- save`
Expected: 3 passed

- [ ] **Step 5: コミット**

```bash
git add src/engine/save.js tests/save.test.js
git commit -m "$(printf 'feat: add localStorage save/load\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

## Task 14: main.js（全体配線・開始画面・ループ）

**Files:**
- Modify: `src/main.js`

> 開始画面で大名を選ぶ → `createInitialState` → `startSeason`（初季の収入）→ ゲーム画面表示。プレイヤーのコマンドは即時適用、`ターン終了`で `endTurn`（AI＋経済＋判定）。勝敗でモーダル表示。

- [ ] **Step 1: main.js を実装**

`src/main.js`:
```js
import { SCENARIO_1560 } from './data/daimyo.js';
import { createInitialState } from './engine/state.js';
import { startSeason, endTurn, applyAction } from './engine/turn.js';
import { saveGame, loadGame, hasSave } from './engine/save.js';
import { render } from './ui/render.js';
import { wireUI } from './ui/input.js';

export const APP_NAME = '戦国・国盗り';

const app = { game: null, selected: null };

function showModal(text) {
  document.getElementById('modal-text').textContent = text;
  document.getElementById('modal').hidden = false;
}
function hideModal() { document.getElementById('modal').hidden = true; }

function rerender() {
  if (!app.game) return;
  render(app.game, app.selected);
}

function checkEnd() {
  if (app.game.status === 'won') showModal('天下統一を成し遂げた！');
  else if (app.game.status === 'lost') showModal('我が家は滅亡した…');
}

function startGame(playerId) {
  app.game = createInitialState(SCENARIO_1560, playerId);
  app.selected = null;
  startSeason(app.game); // 初季の収入
  document.getElementById('start-screen').hidden = true;
  document.getElementById('game-screen').hidden = false;
  rerender();
}

function renderDaimyoPicker() {
  const picker = document.getElementById('daimyo-picker');
  picker.innerHTML = SCENARIO_1560.daimyo.map(d =>
    `<div class="daimyo-card" data-daimyo="${d.id}">
       <div><span class="swatch" style="background:${d.color}"></span><b>${d.name}</b></div>
       <div style="font-size:12px;opacity:.8">${d.family}</div>
       <div style="font-size:12px;opacity:.7">武${d.stats.valor}/政${d.stats.politics}/智${d.stats.intellect}</div>
     </div>`
  ).join('');
}

const handlers = {
  onPickDaimyo: (id) => startGame(id),

  onSelectProvince: (id) => { app.selected = id; rerender(); },

  onCommand: (btn) => {
    const cmd = btn.getAttribute('data-cmd');
    const pid = app.game.playerId;
    if (cmd === 'develop') {
      applyAction(app.game, pid, { type:'develop', province:btn.dataset.prov, kind:btn.dataset.kind });
    } else if (cmd === 'recruit') {
      applyAction(app.game, pid, { type:'recruit', province:btn.dataset.prov });
    } else if (cmd === 'train') {
      applyAction(app.game, pid, { type:'train', province:btn.dataset.prov });
    } else if (cmd === 'attack') {
      const to = btn.dataset.to;
      applyAction(app.game, pid, { type:'attack', from:btn.dataset.from, to,
        troops: app.game.provinces[btn.dataset.from].troops });
      // 攻略に成功していれば選択を移す
      if (app.game.provinces[to].owner === pid) app.selected = to;
    } else if (cmd === 'propose_alliance') {
      applyAction(app.game, pid, { type:'propose_alliance', to:btn.dataset.to });
    }
    rerender();
  },

  onEndTurn: () => {
    endTurn(app.game);
    rerender();
    checkEnd();
  },

  onSave: () => { if (saveGame(app.game)) flash('セーブしました'); },

  onLoad: () => {
    const loaded = loadGame();
    if (!loaded) { flash('セーブがありません'); return; }
    app.game = loaded; app.selected = null;
    document.getElementById('start-screen').hidden = true;
    document.getElementById('game-screen').hidden = false;
    rerender();
  },

  onModalOk: () => {
    hideModal();
    if (app.game && (app.game.status === 'won' || app.game.status === 'lost')) {
      // ゲーム終了 → 開始画面へ
      document.getElementById('game-screen').hidden = true;
      document.getElementById('start-screen').hidden = false;
    }
  },
};

function flash(text) {
  app.game.log.push({ turn: `${app.game.year}-${app.game.season}`, type:'info', text });
  rerender();
}

function boot() {
  renderDaimyoPicker();
  wireUI(handlers);
}

if (typeof document !== 'undefined') boot();
```

- [ ] **Step 2: 全テスト実行（回帰確認）**

Run: `npm test`
Expected: 全 pass（main.js 追加でエンジンテストが壊れていないこと）

- [ ] **Step 3: 手動起動確認**

Run: `python -m http.server 8000` → http://localhost:8000
Expected:
- 開始画面に大名カードが並ぶ
- 大名を選ぶとマップ画面に遷移し、ノード地図・自勢力ステータス・ログが表示される

- [ ] **Step 4: コミット**

```bash
git add src/main.js
git commit -m "$(printf 'feat: wire start screen, command loop, save/load\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

## Task 15: 通しプレイ検証＋仕上げ

**Files:**
- Modify: 不具合があれば該当ファイル
- Create: `docs/superpowers/plans/2026-05-30-sengoku-kuni-tori-playtest.md`（検証メモ）

- [ ] **Step 1: 全テストの最終確認**

Run: `npm test`
Expected: 全テストファイル pass（smoke/util/state/economy/combat/diplomacy/victory/ai/turn/data/save）

- [ ] **Step 2: 手動通しプレイのチェックリスト**

`python -m http.server 8000` で起動し、以下を1ゲームで確認（結果を playtest メモに記録）:
- [ ] 大名を選んで開始できる
- [ ] 国を選択するとステータスとコマンドが出る
- [ ] 農業/商業開発で開発度が上がり金が減る
- [ ] 徴兵で兵力が増え民忠が下がる
- [ ] 隣接敵国へ出陣でき、勝つと国が自色に変わる／負けると失敗ログが出る
- [ ] 同盟提案が成立/拒否される
- [ ] ターン終了でAIが行動し、勢力図（地図色・ランキング）が変化する
- [ ] 季節が春→夏→秋→冬→翌春と進み、年が更新される
- [ ] セーブ→ロードで状態が復元される
- [ ] 全国統一で勝利モーダル、自家滅亡で敗北モーダルが出る

- [ ] **Step 3: 見つかった不具合を修正**

不具合ごとに「失敗する自動テストを追加（可能なら）→修正→`npm test`」のループ。UI起因はコード修正後に再度手動確認。

- [ ] **Step 4: 検証メモを記録してコミット**

`docs/superpowers/plans/2026-05-30-sengoku-kuni-tori-playtest.md` にチェック結果・既知の制限を記載。

```bash
git add -A
git commit -m "$(printf 'test: complete playthrough verification and fixes\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

## Self-Review（計画と仕様の突き合わせ）

**1. 仕様カバレッジ**
- フルマップ60超 → Task 9（整合テストで60国以上を強制）✓
- 1560年・史実大名/国名 → Task 9 ✓
- 季節制ターン → Task 8（advanceSeason）✓
- 内政（開発/徴兵/訓練）→ Task 8 applyAction ✓
- 出陣・外交 → Task 8 applyAction（attack/propose_alliance）✓
- 合戦自動解決 → Task 4 ✓
- 全AI自律行動 → Task 7 + Task 8 runAIPhase ✓
- 全国統一で勝利/プレイヤー消滅で敗北 → Task 6 checkStatus ✓
- 滅亡＝版図0・本拠移転 → Task 6 updateEliminations ✓
- セーブ/ロード（localStorage・バージョン）→ Task 13 ✓
- 経済/合戦/外交/勝敗の計算式 → Task 3/4/5/6 で式どおり実装＋テスト ✓
- 乱数注入でテスト決定性 → 全エンジンテストで fixed/seq を使用 ✓
- UI（上部バー/地図/情報パネル/ログ/ランキング/モーダル）→ Task 10/11 ✓
- DOM非依存の純粋ロジック → engine/ai は document 不参照（render/main のみDOM）✓
- データ整合テスト（隣接対称・連結・所属網羅・本拠妥当）→ Task 9 ✓
- エッジケース（金/兵糧不足・同盟国攻撃不可・兵0出陣不可・本拠陥落）→ Task 8 検証分岐＋Task 6 ✓

**2. プレースホルダ検査**
- 計算ロジック・テストは全て実コードを記載。Task 9 のデータ本体のみ「整合テストを満たすよう網羅」とした（データ整備であり、正しさはテストで機械検証されるため許容）。シード国・形式・編纂ルールは具体提示済み。

**3. 型・名称整合**
- `createInitialState(scenario, playerId)` / `provincesOf` / `totalTroops` / `areAllied` / `daimyoStrength`（state.js）を各所で同名使用 ✓
- `applyAction` のアクション型（develop/recruit/train/attack/propose_alliance）は ai.js の生成と一致 ✓
- `resolveBattle` のパラメータ名（atkTroops/atkValor/atkTrained/defTroops/defValor/terrain/castle）は turn.js の呼び出しと一致 ✓
- `startSeason/runAIPhase/endTurn/applyAction` は turn.js で定義し main.js で使用 ✓
- `render(state, selectedId)` は main.js の `rerender` と一致 ✓
- Task 6 は `provincesOf` を素直に import（不要な別名・未使用importなし）✓
