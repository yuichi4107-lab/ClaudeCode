import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { makeTestScenario, fixed } from './helpers.js';
import { createInitialState } from '../src/engine/state.js';
import { decideActions, RECRUIT_MIN } from '../src/ai/ai.js';

describe('ai.decideActions', () => {
  it('aggressive大名は資金があれば徴兵し、勝てない敵には出陣しない', () => {
    const s = createInitialState(makeTestScenario(), 'd1'); // d2=aggressive, b,c所有
    const acts = decideActions(s, 'd2', fixed(0.5));
    assert.equal(acts.filter(a => a.type === 'recruit').length, 2); // b,c
    assert.equal(acts.some(a => a.type === 'attack'), false);        // d2はd1に勝てない
  });

  it('勝てる弱い隣国には出陣する', () => {
    const s = createInitialState(makeTestScenario(), 'd1');
    s.daimyo.d1.aiPersonality = 'aggressive';
    s.provinces.a.troops = 8000;   // 圧倒的
    s.provinces.b.troops = 500;    // 弱い隣国(d2)
    s.provinces.b.castle = 5;
    const acts = decideActions(s, 'd1', fixed(0.5));
    assert.ok(acts.some(a => a.type === 'attack' && a.from === 'a' && a.to === 'b'));
  });

  it('返すアクションは必ず自分の所有国を参照する', () => {
    const s = createInitialState(makeTestScenario(), 'd1');
    const acts = decideActions(s, 'd2', fixed(0.5));
    const owned = new Set(['b', 'c']);
    for (const a of acts) {
      if (a.province) assert.ok(owned.has(a.province));
      if (a.from) assert.ok(owned.has(a.from));
    }
  });

  it('balanced大名: 兵力がRECRUIT_MIN未満の国は徴兵する', () => {
    // d1 は balanced、province a を所有
    const s = createInitialState(makeTestScenario(), 'd1');
    s.provinces.a.troops = 1000; // RECRUIT_MIN(1500)未満
    const acts = decideActions(s, 'd1', fixed(0.5));
    assert.ok(acts.some(a => a.type === 'recruit' && a.province === 'a'));
  });

  it('balanced大名: 兵力がRECRUIT_MIN以上の国は開発する（徴兵しない）', () => {
    const s = createInitialState(makeTestScenario(), 'd1');
    s.provinces.a.troops = 3000; // RECRUIT_MIN(1500)以上
    const acts = decideActions(s, 'd1', fixed(0.5));
    assert.ok(acts.some(a => a.type === 'develop' && a.province === 'a'));
    assert.equal(acts.some(a => a.type === 'recruit' && a.province === 'a'), false);
  });
});
