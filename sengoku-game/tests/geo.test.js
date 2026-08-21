import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { PROVINCES } from '../src/data/provinces.js';
import { GEO, GEO_LABEL, MAP_VIEWBOX } from '../src/data/geo.js';

const ids = PROVINCES.map(p => p.id);

describe('geo data', () => {
  it('MAP_VIEWBOX は数値4つ', () => {
    const n = MAP_VIEWBOX.trim().split(/\s+/).map(Number);
    assert.equal(n.length, 4);
    assert.ok(n.every(Number.isFinite));
  });
  it('GEO は全66国IDを非空パスでカバー', () => {
    for (const id of ids) {
      assert.ok(typeof GEO[id] === 'string' && GEO[id].length > 0, `GEO missing ${id}`);
      assert.ok(/^[Mm]/.test(GEO[id].trim()), `GEO[${id}] not a path`);
    }
  });
  it('GEO に余分なIDが無い', () => {
    for (const id of Object.keys(GEO)) assert.ok(ids.includes(id), `extra ${id}`);
  });
  it('GEO_LABEL は全IDを viewBox 範囲内で持つ', () => {
    const [mx, my, w, h] = MAP_VIEWBOX.trim().split(/\s+/).map(Number);
    for (const id of ids) {
      const lab = GEO_LABEL[id];
      assert.ok(Array.isArray(lab) && lab.length === 2, `label missing ${id}`);
      assert.ok(lab[0] >= mx && lab[0] <= mx + w, `label x oob ${id}`);
      assert.ok(lab[1] >= my && lab[1] <= my + h, `label y oob ${id}`);
    }
  });
});
