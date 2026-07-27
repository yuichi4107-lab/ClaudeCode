import test from 'node:test';
import assert from 'node:assert/strict';
import {
  BLOCKS,
  blockKey,
  createWorld,
  deserializeWorld,
  findTopSolidY,
  getSpawn,
  isInsideBuildBounds,
  parseBlockKey,
  serializeWorld
} from '../src/world.js';

test('createWorld builds a playable terrain with known block types', () => {
  const world = createWorld();
  const entries = Object.entries(world.blocks);

  assert.equal(world.size, 32);
  assert.ok(entries.length > 3000);
  assert.ok(entries.every(([, type]) => BLOCKS[type]));
  assert.ok(entries.some(([, type]) => type === 'grass'));
  assert.ok(entries.some(([, type]) => type === 'stone'));
  assert.ok(entries.some(([, type]) => type === 'wood'));
});

test('block keys round-trip', () => {
  const key = blockKey(-4, 12, 7);
  assert.equal(key, '-4,12,7');
  assert.deepEqual(parseBlockKey(key), [-4, 12, 7]);
});

test('spawn is above the center column', () => {
  const world = createWorld();
  const top = findTopSolidY(world.blocks, 0, 0);
  const spawn = getSpawn(world);

  assert.ok(spawn.y > top);
  assert.equal(spawn.x, 0);
  assert.equal(spawn.z, 0);
});

test('serialization keeps block edits and selected block', () => {
  const world = createWorld();
  world.blocks[blockKey(1, 12, 1)] = 'wood';

  const raw = serializeWorld(world, {
    position: { x: 1, y: 10, z: 1 },
    selected: 'stone'
  });
  const restored = deserializeWorld(raw);

  assert.equal(restored.world.blocks[blockKey(1, 12, 1)], 'wood');
  assert.equal(restored.player.selected, 'stone');
  assert.equal(restored.player.position.y, 10);
});

test('build bounds allow compact world edits only', () => {
  assert.equal(isInsideBuildBounds(0, 4, 0), true);
  assert.equal(isInsideBuildBounds(-16, 0, -16), true);
  assert.equal(isInsideBuildBounds(16, 0, 0), false);
  assert.equal(isInsideBuildBounds(0, 25, 0), false);
  assert.equal(isInsideBuildBounds(0, -1, 0), false);
});
