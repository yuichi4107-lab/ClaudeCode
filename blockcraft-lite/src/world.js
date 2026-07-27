export const WORLD_SIZE = 32;
export const WORLD_HALF = WORLD_SIZE / 2;
export const SAVE_KEY = 'blockcraft-lite-save-v1';

export const BLOCKS = {
  grass: { id: 'grass', name: '草', color: '#63a845', solid: true },
  dirt: { id: 'dirt', name: '土', color: '#8d633d', solid: true },
  stone: { id: 'stone', name: '石', color: '#858a91', solid: true },
  wood: { id: 'wood', name: '木', color: '#9a6a3a', solid: true },
  leaves: { id: 'leaves', name: '葉', color: '#4e8f42', solid: true },
  water: { id: 'water', name: '水', color: '#4a92d9', solid: false }
};

export const HOTBAR = ['grass', 'dirt', 'stone', 'wood', 'leaves', 'water'];

export function blockKey(x, y, z) {
  return `${x},${y},${z}`;
}

export function parseBlockKey(key) {
  return key.split(',').map(Number);
}

function hash2(x, z) {
  let n = x * 374761393 + z * 668265263;
  n = (n ^ (n >> 13)) * 1274126177;
  return ((n ^ (n >> 16)) >>> 0) / 4294967295;
}

function heightAt(x, z) {
  const wave = Math.sin(x * 0.43) * 1.5 + Math.cos(z * 0.37) * 1.2;
  const ridge = Math.sin((x + z) * 0.19) * 0.9;
  return Math.max(1, Math.min(7, Math.round(3 + wave + ridge + hash2(x, z) * 1.4)));
}

export function createWorld() {
  const blocks = {};

  for (let x = -WORLD_HALF; x < WORLD_HALF; x += 1) {
    for (let z = -WORLD_HALF; z < WORLD_HALF; z += 1) {
      const height = heightAt(x, z);
      for (let y = 0; y <= height; y += 1) {
        let type = 'stone';
        if (y === height) type = height <= 2 ? 'dirt' : 'grass';
        else if (y >= height - 2) type = 'dirt';
        blocks[blockKey(x, y, z)] = type;
      }

      if (height < 3) {
        for (let y = height + 1; y <= 3; y += 1) {
          blocks[blockKey(x, y, z)] = 'water';
        }
      }
    }
  }

  addTrees(blocks);
  return { size: WORLD_SIZE, blocks };
}

function addTrees(blocks) {
  for (let x = -WORLD_HALF + 2; x < WORLD_HALF - 2; x += 1) {
    for (let z = -WORLD_HALF + 2; z < WORLD_HALF - 2; z += 1) {
      if (hash2(x * 11, z * 17) > 0.055) continue;
      const h = findTopSolidY(blocks, x, z);
      if (h < 4 || blocks[blockKey(x, h, z)] !== 'grass') continue;

      const trunkHeight = 3 + Math.floor(hash2(x * 3, z * 5) * 3);
      for (let y = h + 1; y <= h + trunkHeight; y += 1) {
        blocks[blockKey(x, y, z)] = 'wood';
      }

      const crownY = h + trunkHeight;
      for (let dx = -2; dx <= 2; dx += 1) {
        for (let dy = -1; dy <= 2; dy += 1) {
          for (let dz = -2; dz <= 2; dz += 1) {
            const distance = Math.abs(dx) + Math.abs(dz) + Math.max(0, dy);
            if (distance > 4 || (Math.abs(dx) === 2 && Math.abs(dz) === 2)) continue;
            const key = blockKey(x + dx, crownY + dy, z + dz);
            if (!blocks[key]) blocks[key] = 'leaves';
          }
        }
      }
    }
  }
}

export function findTopSolidY(blocks, x, z) {
  let top = -1;
  for (const key of Object.keys(blocks)) {
    const [bx, by, bz] = parseBlockKey(key);
    if (bx === x && bz === z && BLOCKS[blocks[key]]?.solid && by > top) top = by;
  }
  return top;
}

export function getSpawn(world) {
  const y = findTopSolidY(world.blocks, 0, 0);
  return { x: 0, y: Math.max(8, y + 4), z: 0 };
}

export function serializeWorld(world, player) {
  return JSON.stringify({
    version: 1,
    size: world.size,
    blocks: world.blocks,
    player
  });
}

export function deserializeWorld(raw) {
  const data = JSON.parse(raw);
  if (!data || data.version !== 1 || !data.blocks || typeof data.blocks !== 'object') {
    throw new Error('Unsupported save data');
  }

  const blocks = {};
  for (const [key, type] of Object.entries(data.blocks)) {
    if (BLOCKS[type]) blocks[key] = type;
  }

  return {
    world: { size: data.size || WORLD_SIZE, blocks },
    player: data.player || null
  };
}

export function isInsideBuildBounds(x, y, z) {
  return (
    x >= -WORLD_HALF &&
    x < WORLD_HALF &&
    z >= -WORLD_HALF &&
    z < WORLD_HALF &&
    y >= 0 &&
    y <= 24
  );
}
