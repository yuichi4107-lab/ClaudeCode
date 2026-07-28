import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { PROVINCES } from '../src/data/provinces.js';
import { DAIMYO, SCENARIO_1560 } from '../src/data/daimyo.js';

const byId = Object.fromEntries(PROVINCES.map(p => [p.id, p]));
const daimyoIds = new Set(DAIMYO.map(d => d.id));

describe('province data integrity', () => {
  it('60国以上ある', () => {
    assert.ok(PROVINCES.length >= 60, `got ${PROVINCES.length}`);
  });
  it('id は一意', () => {
    assert.equal(new Set(PROVINCES.map(p => p.id)).size, PROVINCES.length);
  });
  it('座標は 0..1 の範囲', () => {
    for (const p of PROVINCES) {
      assert.ok(p.x >= 0, `${p.id}.x < 0`);
      assert.ok(p.x <= 1, `${p.id}.x > 1`);
      assert.ok(p.y >= 0, `${p.id}.y < 0`);
      assert.ok(p.y <= 1, `${p.id}.y > 1`);
    }
  });
  it('隣接は実在ID・自己参照なし・双方向対称', () => {
    for (const p of PROVINCES) {
      for (const n of p.neighbors) {
        assert.ok(n !== p.id, `${p.id} self-neighbor`);
        assert.ok(byId[n], `${p.id}->${n} target not found`);
        assert.ok(byId[n].neighbors.includes(p.id), `${n} does not list ${p.id} back`);
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
    assert.equal(seen.size, PROVINCES.length, `connected: ${seen.size}/${PROVINCES.length}`);
  });
  it('所有者は実在の大名ID', () => {
    for (const p of PROVINCES) assert.ok(daimyoIds.has(p.owner), `${p.id}.owner="${p.owner}" not in DAIMYO`);
  });
  it('terrain は既定値のいずれか', () => {
    const valid = new Set(['plain', 'coast', 'mountain']);
    for (const p of PROVINCES) assert.ok(valid.has(p.terrain), `${p.id}.terrain="${p.terrain}"`);
  });
});

describe('daimyo data integrity', () => {
  it('id は一意', () => {
    assert.equal(new Set(DAIMYO.map(d => d.id)).size, DAIMYO.length);
  });
  it('能力値は 1..100', () => {
    for (const d of DAIMYO) for (const k of ['valor', 'politics', 'intellect']) {
      assert.ok(d.stats[k] >= 1, `${d.id}.stats.${k} < 1`);
      assert.ok(d.stats[k] <= 100, `${d.id}.stats.${k} > 100`);
    }
  });
  it('全大名が1国以上を所有', () => {
    const owners = new Set(PROVINCES.map(p => p.owner));
    for (const d of DAIMYO) assert.ok(owners.has(d.id), `${d.id} owns no province`);
  });
  it('本拠は自領内', () => {
    for (const d of DAIMYO) assert.equal(byId[d.capital]?.owner, d.id, `${d.id}.capital="${d.capital}"`);
  });
  it('aiPersonality は既定値のいずれか', () => {
    const valid = new Set(['aggressive', 'balanced', 'defensive']);
    for (const d of DAIMYO) assert.ok(valid.has(d.aiPersonality), `${d.id}.aiPersonality="${d.aiPersonality}"`);
  });
});

describe('scenario', () => {
  it('SCENARIO_1560 が provinces/daimyo を内包し year=1560', () => {
    assert.equal(SCENARIO_1560.year, 1560);
    assert.equal(SCENARIO_1560.provinces.length, PROVINCES.length);
    assert.equal(SCENARIO_1560.daimyo.length, DAIMYO.length);
  });
});
