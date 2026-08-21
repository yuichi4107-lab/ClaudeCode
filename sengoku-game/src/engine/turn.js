import { provincesOf, areAllied } from './state.js';
import { applyEconomy } from './economy.js';
import { resolveBattle } from './combat.js';
import { evaluateAllianceProposal, formAlliance, maybeBreakAlliances } from './diplomacy.js';
import { updateEliminations, checkStatus } from './victory.js';
import { decideActions } from '../ai/ai.js';

export const DEVELOP_COST = 100;
export const RECRUIT_COST = 200;
export const RECRUIT_LOYALTY_COST = 8;
export const NEW_CONQUEST_LOYALTY = 50;

function log(state, type, text) {
  state.log.push({ turn: `${state.year}-${state.season}`, type, text });
}

// 1アクションを適用（検証込み）。state を更新する。
export function applyAction(state, daimyoId, action, rng = Math.random) {
  const d = state.daimyo[daimyoId];
  if (!d || !d.alive) return;

  if (action.type === 'develop') {
    const p = state.provinces[action.province];
    if (!p || p.owner !== daimyoId || d.gold < DEVELOP_COST) return;
    const gain = Math.round(5 + d.stats.politics / 20);
    if (action.kind === 'agri') p.agri = Math.min(100, p.agri + gain);
    else p.commerce = Math.min(100, p.commerce + gain);
    d.gold -= DEVELOP_COST;
    return;
  }

  if (action.type === 'recruit') {
    const p = state.provinces[action.province];
    if (!p || p.owner !== daimyoId || d.gold < RECRUIT_COST) return;
    const gain = Math.round(800 + d.stats.politics * 4);
    p.troops += gain;
    p.loyalty = Math.max(0, p.loyalty - RECRUIT_LOYALTY_COST);
    d.gold -= RECRUIT_COST;
    return;
  }

  if (action.type === 'train') {
    const p = state.provinces[action.province];
    if (!p || p.owner !== daimyoId) return;
    p.trained = true;
    return;
  }

  if (action.type === 'attack') {
    const from = state.provinces[action.from];
    const to = state.provinces[action.to];
    if (!from || !to) return;
    if (from.owner !== daimyoId) return;
    if (to.owner === daimyoId) return;
    if (!from.neighbors.includes(to.id)) return;
    if (areAllied(state, daimyoId, to.owner)) return;
    if (from.troops <= 0) return;

    const atkTroops = from.troops;
    from.troops = 0; // 出撃
    const result = resolveBattle({
      atkTroops,
      atkValor: d.stats.valor,
      atkTrained: from.trained === true,
      defTroops: to.troops,
      defValor: state.daimyo[to.owner].stats.valor,
      terrain: to.terrain,
      castle: to.castle,
    }, rng);
    from.trained = false;

    const survivors = Math.max(0, atkTroops - result.atkLosses);
    if (result.captured) {
      const loserId = to.owner;
      const loserName = state.daimyo[loserId].name;
      to.owner = daimyoId;
      to.troops = survivors;
      to.loyalty = NEW_CONQUEST_LOYALTY;
      to.trained = false;
      log(state, 'battle', `${d.name}が${to.name}を攻略（対${loserName}）`);
    } else {
      to.troops = Math.max(0, to.troops - result.defLosses);
      from.troops = survivors; // 撤退して帰還
      log(state, 'battle', `${d.name}の${to.name}攻めは失敗`);
    }
    return;
  }

  if (action.type === 'propose_alliance') {
    const toId = action.to;
    if (!state.daimyo[toId] || !state.daimyo[toId].alive) return;
    if (areAllied(state, daimyoId, toId)) return;
    if (evaluateAllianceProposal(state, daimyoId, toId, rng)) {
      formAlliance(state, daimyoId, toId);
      log(state, 'diplomacy', `${d.name}と${state.daimyo[toId].name}が同盟`);
    } else {
      log(state, 'diplomacy', `${state.daimyo[toId].name}は同盟を拒否`);
    }
  }
}

// 季節開始：経済適用
export function startSeason(state) {
  const ev = applyEconomy(state);
  for (const e of ev) state.log.push(e);
  return ev;
}

// 全AI大名の行動
export function runAIPhase(state, rng = Math.random) {
  for (const id of Object.keys(state.daimyo)) {
    const d = state.daimyo[id];
    if (!d.alive || d.isPlayer) continue;
    for (const action of decideActions(state, id, rng)) {
      applyAction(state, id, action, rng);
    }
  }
}

// 季節を1つ進める
function advanceSeason(state) {
  state.season = (state.season + 1) % 4;
  if (state.season === 0) state.year += 1;
}

// 「ターン終了」: AI→滅亡処理→勝敗判定→（継続なら）次季節開始
export function endTurn(state, rng = Math.random) {
  for (const e of maybeBreakAlliances(state, rng)) state.log.push(e);
  runAIPhase(state, rng);
  for (const e of updateEliminations(state)) state.log.push(e);
  checkStatus(state);
  if (state.status === 'playing') {
    advanceSeason(state);
    startSeason(state);
    for (const e of updateEliminations(state)) state.log.push(e);
    checkStatus(state);
  }
  return state.status;
}
