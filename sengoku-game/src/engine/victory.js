import { provincesOf } from './state.js';

export function provinceCount(state, daimyoId) {
  return provincesOf(state, daimyoId).length;
}

function removeAllAlliancesOf(state, daimyoId) {
  state.alliances = state.alliances.filter(([x, y]) => x !== daimyoId && y !== daimyoId);
}

// 滅亡処理＋本拠移転。発生イベント配列を返す
export function updateEliminations(state) {
  const events = [];
  for (const d of Object.values(state.daimyo)) {
    if (!d.alive) continue;
    const owned = provincesOf(state, d.id);
    if (owned.length === 0) {
      d.alive = false;
      removeAllAlliancesOf(state, d.id);
      events.push({ turn: `${state.year}-${state.season}`, type: 'elimination',
        text: `${d.name}が滅亡した` });
    } else if (state.provinces[d.capital]?.owner !== d.id) {
      // 本拠を失ったが他国は残る → 残存国の先頭へ移転
      d.capital = owned[0].id;
      events.push({ turn: `${state.year}-${state.season}`, type: 'capital_move',
        text: `${d.name}が本拠を${owned[0].name}へ移した` });
    }
  }
  return events;
}

// 勝敗を判定して state.status を更新し、文字列を返す
export function checkStatus(state) {
  const total = Object.keys(state.provinces).length;
  const player = state.daimyo[state.playerId];
  if (!player.alive) state.status = 'lost';
  else if (provinceCount(state, state.playerId) === total) state.status = 'won';
  else state.status = 'playing';
  return state.status;
}
