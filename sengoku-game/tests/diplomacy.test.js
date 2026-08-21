import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { makeTestScenario, fixed } from './helpers.js';
import { createInitialState, areAllied } from '../src/engine/state.js';
import { evaluateAllianceProposal, formAlliance, breakAlliance, maybeBreakAlliances } from '../src/engine/diplomacy.js';

describe('diplomacy', () => {
  it('弱者から強者(aggressive)への提案は拒否されやすい', () => {
    // d1(strength5000) → d2(strength7500): ratio0.667→base0.2, d2 aggressive -0.2 → 0
    const s = createInitialState(makeTestScenario(), 'd1');
    assert.equal(evaluateAllianceProposal(s, 'd1', 'd2', fixed(0.0)), false);
  });

  it('強者から弱者(balanced)への提案は受諾されやすい', () => {
    // d2(7500) → d1(5000): ratio1.5→base0.7, d1 balanced 0 → 0.7
    const s = createInitialState(makeTestScenario(), 'd1');
    assert.equal(evaluateAllianceProposal(s, 'd2', 'd1', fixed(0.5)), true);  // 0.5<0.7
    assert.equal(evaluateAllianceProposal(s, 'd2', 'd1', fixed(0.9)), false); // 0.9>0.7
  });

  it('formAlliance / breakAlliance が双方向に効く', () => {
    const s = createInitialState(makeTestScenario(), 'd1');
    formAlliance(s, 'd1', 'd2');
    assert.equal(areAllied(s, 'd2', 'd1'), true);
    formAlliance(s, 'd1', 'd2'); // 二重追加されない
    assert.equal(s.alliances.length, 1);
    breakAlliance(s, 'd2', 'd1');
    assert.equal(areAllied(s, 'd1', 'd2'), false);
  });

  describe('maybeBreakAlliances', () => {
    it('rng=0.0 のとき同盟を破棄してイベントを返す', () => {
      const s = createInitialState(makeTestScenario(), 'd1');
      s.alliances.push(['d1', 'd2']);
      const events = maybeBreakAlliances(s, fixed(0.0));
      assert.equal(events.length, 1);
      assert.equal(areAllied(s, 'd1', 'd2'), false);
    });

    it('rng=0.99 のとき同盟は維持される', () => {
      const s = createInitialState(makeTestScenario(), 'd1');
      s.alliances.push(['d1', 'd2']);
      const events = maybeBreakAlliances(s, fixed(0.99));
      assert.equal(events.length, 0);
      assert.equal(areAllied(s, 'd1', 'd2'), true);
    });
  });
});
