import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
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
    assert.equal(hasSave(st), true);
    const loaded = loadGame(st);
    assert.equal(loaded.daimyo.d1.gold, 1234);
    assert.equal(loaded.provinces.a.name, 'A');
  });

  it('セーブが無ければ load は null', () => {
    assert.equal(loadGame(fakeStorage()), null);
  });

  it('バージョン不一致は null（互換崩れ対策）', () => {
    const st = fakeStorage();
    st.setItem('sengoku_save', JSON.stringify({ version: SAVE_VERSION + 99, state: {} }));
    assert.equal(loadGame(st), null);
  });
});
