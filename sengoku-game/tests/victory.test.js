import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { makeTestScenario } from './helpers.js';
import { createInitialState, areAllied } from '../src/engine/state.js';
import { provinceCount, updateEliminations, checkStatus } from '../src/engine/victory.js';

describe('victory', () => {
  it('provinceCount は所有国数', () => {
    const s = createInitialState(makeTestScenario(), 'd1');
    assert.equal(provinceCount(s, 'd2'), 2);
  });

  it('版図0の大名は滅亡し、同盟も掃除される', () => {
    const s = createInitialState(makeTestScenario(), 'd1');
    s.alliances.push(['d1', 'd2']);
    s.provinces.b.owner = 'd1';
    s.provinces.c.owner = 'd1'; // d2 の版図0
    const ev = updateEliminations(s);
    assert.equal(s.daimyo.d2.alive, false);
    assert.equal(areAllied(s, 'd1', 'd2'), false);
    assert.ok(ev.some(e => e.type === 'elimination'));
  });

  it('本拠陥落でも他国が残れば本拠を移転して存続', () => {
    const s = createInitialState(makeTestScenario(), 'd1');
    s.provinces.b.owner = 'd1';        // d1 は a,b を保有・本拠a
    s.provinces.a.owner = 'd2';        // 本拠a を失う（bは残る）
    updateEliminations(s);
    assert.equal(s.daimyo.d1.alive, true);
    assert.equal(s.daimyo.d1.capital, 'b');
  });

  it('checkStatus: 全国掌握で won / プレイヤー消滅で lost', () => {
    const s = createInitialState(makeTestScenario(), 'd1');
    s.provinces.b.owner = 'd1';
    s.provinces.c.owner = 'd1';
    updateEliminations(s);
    assert.equal(checkStatus(s), 'won');

    const s2 = createInitialState(makeTestScenario(), 'd1');
    s2.provinces.a.owner = 'd2';
    updateEliminations(s2);
    assert.equal(checkStatus(s2), 'lost');
  });
});
