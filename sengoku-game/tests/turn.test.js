import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { makeTestScenario, fixed } from './helpers.js';
import { createInitialState } from '../src/engine/state.js';
import { applyAction, startSeason, runAIPhase, endTurn } from '../src/engine/turn.js';

describe('turn.applyAction', () => {
  it('develop: 開発度+gain・金-100', () => {
    const s = createInitialState(makeTestScenario(), 'd1');
    applyAction(s, 'd1', { type:'develop', province:'a', kind:'commerce' }, fixed(0.5));
    assert.equal(s.provinces.a.commerce, 40 + 9); // round(5+70/20)=9
    assert.equal(s.daimyo.d1.gold, 2000 - 100);
  });

  it('recruit: 兵力+gain・民忠-8・金-200', () => {
    const s = createInitialState(makeTestScenario(), 'd1');
    applyAction(s, 'd1', { type:'recruit', province:'a' }, fixed(0.5));
    assert.equal(s.provinces.a.troops, 3000 + 1080); // round(800+70*4)
    assert.equal(s.provinces.a.loyalty, 70 - 8);
    assert.equal(s.daimyo.d1.gold, 2000 - 200);
  });

  it('attack 成功: 所有者が変わり守備兵が入れ替わる', () => {
    const s = createInitialState(makeTestScenario(), 'd1');
    s.provinces.a.troops = 8000; // 圧勝条件
    s.provinces.b.troops = 500;
    s.provinces.b.castle = 5;
    applyAction(s, 'd1', { type:'attack', from:'a', to:'b', troops:8000 }, fixed(0.5));
    assert.equal(s.provinces.b.owner, 'd1');
    assert.equal(s.provinces.a.troops, 0); // 出撃して空に
    assert.ok(s.provinces.b.troops > 0); // 残存兵が駐留
  });

  it('attack 不正(非隣接)は無視される', () => {
    const s = createInitialState(makeTestScenario(), 'd1');
    const before = JSON.stringify(s.provinces);
    applyAction(s, 'd1', { type:'attack', from:'a', to:'c', troops:3000 }, fixed(0.5)); // a-c は非隣接
    assert.equal(JSON.stringify(s.provinces), before);
  });

  it('金不足の develop は無視される', () => {
    const s = createInitialState(makeTestScenario(), 'd1');
    s.daimyo.d1.gold = 50;
    applyAction(s, 'd1', { type:'develop', province:'a', kind:'agri' }, fixed(0.5));
    assert.equal(s.provinces.a.agri, 40);
    assert.equal(s.daimyo.d1.gold, 50);
  });
});

describe('turn flow', () => {
  it('startSeason は経済を適用し金が増える', () => {
    const s = createInitialState(makeTestScenario(), 'd1');
    startSeason(s);
    assert.equal(s.daimyo.d1.gold, 2000 + 136);
  });

  it('endTurn: AI行動後に季節が進み status は playing', () => {
    const s = createInitialState(makeTestScenario(), 'd1');
    endTurn(s, fixed(0.5));
    assert.equal(s.season, 1);
    assert.ok(['playing','won','lost'].includes(s.status));
  });

  it('endTurn: 冬→春で年が進む', () => {
    const s = createInitialState(makeTestScenario(), 'd1');
    s.season = 3;
    endTurn(s, fixed(0.5));
    assert.equal(s.season, 0);
    assert.equal(s.year, 1561);
  });
});
