import { clamp } from './util.js';

export function terrainMul(terrain) {
  switch (terrain) {
    case 'coast': return 1.1;
    case 'mountain': return 1.3;
    default: return 1.0; // plain / 未知
  }
}

// 純粋関数。rng は () => [0,1)
export function resolveBattle(p, rng = Math.random) {
  const atkRoll = 0.85 + rng() * 0.30;
  const defRoll = 0.85 + rng() * 0.30;
  const attackPower = p.atkTroops * (1 + p.atkValor / 100)
    * (p.atkTrained ? 1.1 : 1.0) * atkRoll;
  const defensePower = p.defTroops * (1 + p.defValor / 100)
    * terrainMul(p.terrain) * (1 + p.castle / 100) * defRoll;
  const ratio = defensePower === 0 ? Infinity : attackPower / defensePower;
  const captured = ratio >= 1;

  let atkLosses;
  let defLosses;
  if (captured) {
    atkLosses = Math.round(p.atkTroops * clamp(0.30 / ratio, 0.05, 0.60));
    defLosses = p.defTroops; // 壊走
  } else {
    atkLosses = Math.round(p.atkTroops * clamp(0.30 * ratio + 0.20, 0.10, 0.70));
    defLosses = Math.round(p.defTroops * clamp(0.25 * ratio, 0.05, 0.50));
  }
  return { attackPower, defensePower, ratio, atkLosses, defLosses, captured };
}
