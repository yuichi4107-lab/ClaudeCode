import { provincesOf, daimyoStrength, areAllied } from '../engine/state.js';
import { terrainMul } from '../engine/combat.js';

export const RECRUIT_COST = 200;
export const DEVELOP_COST = 100;
export const RECRUIT_TARGET = 4000;
export const RECRUIT_MIN = 1500;
export const AGGRO = { aggressive: 0.9, balanced: 1.1, defensive: 1.4 };
export const ALLIANCE_RATIO = 1.5;

// 純粋関数: state は読むだけ、アクション配列を返す
export function decideActions(state, daimyoId, rng = Math.random) {
  const me = state.daimyo[daimyoId];
  const mine = provincesOf(state, daimyoId);
  const actions = [];
  let gold = me.gold;

  // 1) 内政：各国に最大1つ
  for (const p of mine) {
    const floor = me.aiPersonality === 'aggressive' ? RECRUIT_TARGET : RECRUIT_MIN;
    if (gold >= RECRUIT_COST && p.troops < floor) {
      actions.push({ type: 'recruit', province: p.id });
      gold -= RECRUIT_COST;
    } else if (gold >= DEVELOP_COST) {
      const kind = p.agri <= p.commerce ? 'agri' : 'commerce';
      actions.push({ type: 'develop', province: p.id, kind });
      gold -= DEVELOP_COST;
    }
  }

  // 2) 軍事：勝てそうな隣接敵国へ（defensive は出陣しない）
  if (me.aiPersonality !== 'defensive') {
    let best = null; // { from, to, defScore }
    for (const p of mine) {
      for (const nId of p.neighbors) {
        const n = state.provinces[nId];
        if (!n || n.owner === daimyoId) continue;
        if (areAllied(state, daimyoId, n.owner)) continue;
        const estAtk = p.troops * (1 + me.stats.valor / 100);
        const defValor = state.daimyo[n.owner].stats.valor;
        const estDef = n.troops * (1 + defValor / 100) * terrainMul(n.terrain) * (1 + n.castle / 100);
        if (estAtk > estDef * AGGRO[me.aiPersonality] && p.troops > 0) {
          if (!best || estDef < best.defScore) best = { from: p.id, to: n.id, defScore: estDef };
        }
      }
    }
    if (best) actions.push({ type: 'attack', from: best.from, to: best.to,
      troops: state.provinces[best.from].troops });
  }

  // 3) 外交：自分よりはるかに強い隣接勢力へ同盟提案
  const neighborsDaimyo = new Set();
  for (const p of mine) {
    for (const nId of p.neighbors) {
      const n = state.provinces[nId];
      if (n && n.owner !== daimyoId) neighborsDaimyo.add(n.owner);
    }
  }
  let target = null; let targetStr = 0;
  const myStr = daimyoStrength(state, daimyoId);
  for (const otherId of neighborsDaimyo) {
    if (areAllied(state, daimyoId, otherId)) continue;
    const s = daimyoStrength(state, otherId);
    if (s / myStr >= ALLIANCE_RATIO && s > targetStr) { target = otherId; targetStr = s; }
  }
  if (target && (me.aiPersonality === 'defensive' || rng() < 0.3)) {
    actions.push({ type: 'propose_alliance', to: target });
  }

  return actions;
}
