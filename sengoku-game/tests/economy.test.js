import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { makeTestScenario } from './helpers.js';
import { createInitialState } from '../src/engine/state.js';
import { goldIncome, rationIncome, upkeep, applyEconomy } from '../src/engine/economy.js';

describe('economy', () => {
  const A = () => createInitialState(makeTestScenario(), 'd1').provinces.a;

  it('goldIncome = round(石高*商業/100*(0.5+民忠/200)*8)', () => {
    assert.equal(goldIncome(A()), 136); // 50*0.4*0.85*8
  });
  it('rationIncome は季節係数を反映（春1.0 / 秋2.0）', () => {
    assert.equal(rationIncome(A(), 0), 600);   // 50*0.4*1.0*30
    assert.equal(rationIncome(A(), 2), 1200);  // 秋
  });
  it('upkeep = round(兵力*0.5)', () => {
    assert.equal(upkeep(A()), 1500);
  });

  it('applyEconomy: 通常は金加算・兵糧収支・民忠+2', () => {
    const s = createInitialState(makeTestScenario(), 'd1');
    applyEconomy(s);
    assert.equal(s.daimyo.d1.gold, 2000 + 136);
    assert.equal(s.provinces.a.rations, 5000 + 600 - 1500); // 4100
    assert.equal(s.provinces.a.loyalty, 72);
  });

  it('applyEconomy: 兵糧不足で餓死＋民忠-5', () => {
    const s = createInitialState(makeTestScenario(), 'd1');
    s.provinces.a.rations = 0;            // 収入600 < 維持1500 → 不足900
    applyEconomy(s);
    assert.equal(s.provinces.a.rations, 0);
    assert.equal(s.provinces.a.troops, 3000 - 1800); // lost = 900/0.5
    assert.equal(s.provinces.a.loyalty, 65);
  });
});
