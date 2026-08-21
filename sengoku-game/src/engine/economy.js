export const GOLD_FACTOR = 8;
export const RATIONS_FACTOR = 30;
export const SEASON_RATION = [1.0, 1.0, 2.0, 0.5]; // 春/夏/秋/冬
export const UPKEEP_PER_TROOP = 0.5;
export const LOYALTY_REGEN = 2;
export const STARVE_LOYALTY_PENALTY = 5;

export function goldIncome(p) {
  return Math.round(p.baseKokudaka * (p.commerce / 100) * (0.5 + p.loyalty / 200) * GOLD_FACTOR);
}

export function rationIncome(p, season) {
  return Math.round(p.baseKokudaka * (p.agri / 100) * SEASON_RATION[season] * RATIONS_FACTOR);
}

export function upkeep(p) {
  return Math.round(p.troops * UPKEEP_PER_TROOP);
}

// state を更新し、発生イベントの配列を返す
export function applyEconomy(state) {
  const events = [];
  for (const p of Object.values(state.provinces)) {
    state.daimyo[p.owner].gold += goldIncome(p);
    p.rations += rationIncome(p, state.season);
    const up = upkeep(p);
    if (p.rations >= up) {
      p.rations -= up;
      p.loyalty = Math.min(100, p.loyalty + LOYALTY_REGEN);
    } else {
      const deficit = up - p.rations;
      p.rations = 0;
      const lost = Math.round(deficit / UPKEEP_PER_TROOP);
      p.troops = Math.max(0, p.troops - lost);
      p.loyalty = Math.max(0, p.loyalty - STARVE_LOYALTY_PENALTY);
      events.push({ turn: `${state.year}-${state.season}`, type: 'starvation',
        text: `${p.name}で兵糧不足。兵${lost}を失った` });
    }
  }
  return events;
}
