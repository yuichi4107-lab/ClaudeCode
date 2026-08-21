import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { makeTestScenario } from './helpers.js';
import {
  createInitialState, provincesOf, totalTroops, areAllied, daimyoStrength,
} from '../src/engine/state.js';

describe('state', () => {
  it('createInitialState はマップ化・ディープクローン・playerId設定する', () => {
    const sc = makeTestScenario();
    const s = createInitialState(sc, 'd1');
    assert.equal(s.provinces.a.name, 'A');
    assert.equal(s.daimyo.d1.isPlayer, true);
    assert.equal(s.daimyo.d2.isPlayer, false);
    assert.equal(s.playerId, 'd1');
    assert.equal(s.status, 'playing');
    // ディープクローン：元データを変更しても state は不変
    sc.provinces[0].troops = 1;
    assert.equal(s.provinces.a.troops, 3000);
  });

  it('provincesOf は所有国の配列を返す', () => {
    const s = createInitialState(makeTestScenario(), 'd1');
    assert.deepEqual(provincesOf(s, 'd2').map(p => p.id).sort(), ['b', 'c']);
  });

  it('totalTroops は所有国の兵力合計', () => {
    const s = createInitialState(makeTestScenario(), 'd1');
    assert.equal(totalTroops(s, 'd2'), 3500);
  });

  it('areAllied は同盟ペアを双方向で判定', () => {
    const s = createInitialState(makeTestScenario(), 'd1');
    assert.equal(areAllied(s, 'd1', 'd2'), false);
    s.alliances.push(['d1', 'd2']);
    assert.equal(areAllied(s, 'd1', 'd2'), true);
    assert.equal(areAllied(s, 'd2', 'd1'), true);
  });

  it('daimyoStrength = 総兵力 + 国数*2000', () => {
    const s = createInitialState(makeTestScenario(), 'd1');
    assert.equal(daimyoStrength(s, 'd1'), 3000 + 1 * 2000);
    assert.equal(daimyoStrength(s, 'd2'), 3500 + 2 * 2000);
  });
});
