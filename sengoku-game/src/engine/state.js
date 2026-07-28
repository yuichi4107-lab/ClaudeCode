const PROVINCE_STRENGTH_WEIGHT = 2000;

export function createInitialState(scenario, playerId = scenario.playerId) {
  const provinces = {};
  for (const p of scenario.provinces) {
    provinces[p.id] = { ...p, neighbors: [...p.neighbors] };
  }
  const daimyo = {};
  for (const d of scenario.daimyo) {
    daimyo[d.id] = { ...d, stats: { ...d.stats }, isPlayer: d.id === playerId };
  }
  return {
    year: scenario.year,
    season: scenario.season,
    provinces,
    daimyo,
    alliances: [],
    playerId,
    log: [],
    status: 'playing',
  };
}

export function provincesOf(state, daimyoId) {
  return Object.values(state.provinces).filter(p => p.owner === daimyoId);
}

export function totalTroops(state, daimyoId) {
  return provincesOf(state, daimyoId).reduce((sum, p) => sum + p.troops, 0);
}

export function areAllied(state, a, b) {
  return state.alliances.some(
    ([x, y]) => (x === a && y === b) || (x === b && y === a),
  );
}

export function daimyoStrength(state, daimyoId) {
  return totalTroops(state, daimyoId)
    + provincesOf(state, daimyoId).length * PROVINCE_STRENGTH_WEIGHT;
}
