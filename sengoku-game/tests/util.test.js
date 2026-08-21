import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { clamp } from '../src/engine/util.js';

describe('clamp', () => {
  it('範囲内はそのまま', () => assert.equal(clamp(5, 0, 10), 5));
  it('下限でクランプ', () => assert.equal(clamp(-3, 0, 10), 0));
  it('上限でクランプ', () => assert.equal(clamp(99, 0, 10), 10));
});
