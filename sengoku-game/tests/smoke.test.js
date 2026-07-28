import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { APP_NAME } from '../src/main.js';

describe('smoke', () => {
  it('main.js を import できる', () => {
    assert.equal(APP_NAME, '戦国・国盗り');
  });
});
