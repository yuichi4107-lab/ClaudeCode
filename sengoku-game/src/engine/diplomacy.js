import { areAllied, daimyoStrength } from './state.js';
import { clamp } from './util.js';

const PERSONALITY_BONUS = { aggressive: -0.2, balanced: 0.0, defensive: 0.2 };

// 受け手 toId が fromId の同盟提案を受諾するか（純粋判定）
export function evaluateAllianceProposal(state, fromId, toId, rng = Math.random) {
  const ratio = daimyoStrength(state, fromId) / daimyoStrength(state, toId);
  let chance;
  if (ratio >= 1.2) chance = 0.7;       // 提案者が強い → 庇護を得たい
  else if (ratio <= 0.8) chance = 0.2;  // 提案者が弱い → 旨味少ない
  else chance = 0.4;
  chance = clamp(chance + (PERSONALITY_BONUS[state.daimyo[toId].aiPersonality] ?? 0), 0, 1);
  return rng() < chance;
}

export function formAlliance(state, a, b) {
  if (!areAllied(state, a, b)) state.alliances.push([a, b]);
}

export function breakAlliance(state, a, b) {
  state.alliances = state.alliances.filter(
    ([x, y]) => !((x === a && y === b) || (x === b && y === a)),
  );
}

export const ALLIANCE_BREAK_CHANCE = 0.08;

// 同盟を確率/国力逆転で破棄。破棄イベント配列を返す（state を更新）
export function maybeBreakAlliances(state, rng = Math.random) {
  const events = [];
  for (const [a, b] of [...state.alliances]) {
    const sa = daimyoStrength(state, a);
    const sb = daimyoStrength(state, b);
    const ratio = Math.max(sa, sb) / Math.max(1, Math.min(sa, sb));
    const chance = ratio >= 2 ? 0.5 : ALLIANCE_BREAK_CHANCE; // 国力が大きく傾けば裏切りやすい
    if (rng() < chance) {
      breakAlliance(state, a, b);
      events.push({ turn: `${state.year}-${state.season}`, type: 'diplomacy',
        text: `${state.daimyo[a].name}と${state.daimyo[b].name}の同盟が破棄された` });
    }
  }
  return events;
}
