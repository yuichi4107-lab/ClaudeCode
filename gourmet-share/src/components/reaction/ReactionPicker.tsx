'use client';

import {
  BEFORE_REACTIONS,
  AFTER_REACTIONS,
  PRICE_FEEL_REACTIONS,
  type ReactionDef,
} from '@/lib/constants';

type Props = {
  counts: Record<string, number>;
  myReactions: Set<string>;
  onToggle: (key: string) => void;
};

function ReactionButton({
  def,
  count,
  active,
  onToggle,
}: {
  def: ReactionDef;
  count: number;
  active: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      onClick={onToggle}
      className={`flex items-center gap-1.5 rounded-full px-3 py-2 text-sm transition-colors ${
        active
          ? 'bg-green-100 text-green-800 ring-1 ring-green-400'
          : 'bg-gray-50 text-gray-700 hover:bg-gray-100'
      }`}
    >
      <span>{def.emoji}</span>
      <span className="whitespace-nowrap">{def.label}</span>
      {count > 0 && (
        <span className="ml-1 text-xs font-medium text-gray-500">
          {count}
        </span>
      )}
    </button>
  );
}

export function ReactionPicker({ counts, myReactions, onToggle }: Props) {
  return (
    <div className="space-y-5">
      <div>
        <h4 className="mb-2 text-sm font-medium text-gray-500">
          気になる？
        </h4>
        <div className="flex flex-wrap gap-2">
          {BEFORE_REACTIONS.map((def) => (
            <ReactionButton
              key={def.key}
              def={def}
              count={counts[def.key] || 0}
              active={myReactions.has(def.key)}
              onToggle={() => onToggle(def.key)}
            />
          ))}
        </div>
      </div>

      <div>
        <h4 className="mb-2 text-sm font-medium text-gray-500">
          行った感想（当てはまるものをタップ）
        </h4>
        <div className="flex flex-wrap gap-2">
          {AFTER_REACTIONS.map((def) => (
            <ReactionButton
              key={def.key}
              def={def}
              count={counts[def.key] || 0}
              active={myReactions.has(def.key)}
              onToggle={() => onToggle(def.key)}
            />
          ))}
        </div>
      </div>

      <div>
        <h4 className="mb-2 text-sm font-medium text-gray-500">
          お会計の印象
        </h4>
        <div className="flex flex-wrap gap-2">
          {PRICE_FEEL_REACTIONS.map((def) => (
            <ReactionButton
              key={def.key}
              def={def}
              count={counts[def.key] || 0}
              active={myReactions.has(def.key)}
              onToggle={() => onToggle(def.key)}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
