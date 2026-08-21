import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { fixed } from './helpers.js';
import { terrainMul, resolveBattle } from '../src/engine/combat.js';

describe('combat', () => {
  it('terrainMul: plain1.0 / coast1.1 / mountain1.3 / 既定1.0', () => {
    assert.equal(terrainMul('plain'), 1.0);
    assert.equal(terrainMul('coast'), 1.1);
    assert.equal(terrainMul('mountain'), 1.3);
    assert.equal(terrainMul('unknown'), 1.0);
  });

  it('攻撃側が圧倒すると captured=true、守備は壊走', () => {
    const r = resolveBattle(
      { atkTroops:5000, atkValor:80, atkTrained:false,
        defTroops:1000, defValor:50, terrain:'plain', castle:20 },
      fixed(0.5), // roll = 0.85 + 0.5*0.30 = 1.0
    );
    // attackPower=9000, defensePower=1800, ratio=5
    assert.equal(r.captured, true);
    assert.equal(r.atkLosses, 300);   // 5000*clamp(0.30/5=0.06)
    assert.equal(r.defLosses, 1000);  // routed
  });

  it('攻撃側が劣勢だと captured=false、両者損耗', () => {
    const r = resolveBattle(
      { atkTroops:1000, atkValor:50, atkTrained:false,
        defTroops:3000, defValor:70, terrain:'mountain', castle:30 },
      fixed(0.5),
    );
    // attackPower=1500, defensePower=8619, ratio≈0.174
    assert.equal(r.captured, false);
    assert.equal(r.atkLosses, 252);   // 1000*clamp(0.30*0.174+0.20)
    assert.equal(r.defLosses, 150);   // 3000*clamp(0.25*0.174→0.05)
  });

  it('守備兵0なら captured=true', () => {
    const r = resolveBattle(
      { atkTroops:1000, atkValor:50, atkTrained:false,
        defTroops:0, defValor:50, terrain:'plain', castle:0 },
      fixed(0.5),
    );
    assert.equal(r.captured, true);
  });
});
