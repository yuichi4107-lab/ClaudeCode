// ジャンル一覧
export const GENRES = [
  '和食', '中華', 'イタリアン', 'フレンチ', '韓国料理',
  'カフェ', '居酒屋', 'ラーメン', '焼肉', '寿司', 'カレー', 'その他',
] as const;

export type Genre = (typeof GENRES)[number];

// ジャンル別ピンカラー
export const GENRE_COLORS: Record<Genre, string> = {
  '和食': '#2E7D32',
  '中華': '#C62828',
  'イタリアン': '#1565C0',
  'フレンチ': '#6A1B9A',
  '韓国料理': '#EF6C00',
  'カフェ': '#795548',
  '居酒屋': '#F9A825',
  'ラーメン': '#D84315',
  '焼肉': '#AD1457',
  '寿司': '#00838F',
  'カレー': '#FF8F00',
  'その他': '#546E7A',
};

// 価格帯
export const PRICE_RANGES = [
  '~1,000',
  '1,000~3,000',
  '3,000~5,000',
  '5,000~10,000',
  '10,000~',
] as const;

export type PriceRange = (typeof PRICE_RANGES)[number];

// リアクション定義
export type ReactionDef = {
  key: string;
  emoji: string;
  label: string;
};

// 行く前のリアクション
export const BEFORE_REACTIONS: ReactionDef[] = [
  { key: 'want_to_go', emoji: '🙋', label: '行きたい！' },
  { key: 'interested', emoji: '😋', label: '気になる' },
  { key: 'want_again', emoji: '🔁', label: 'また行きたい' },
];

// 行った後の感想タグ
export const AFTER_REACTIONS: ReactionDef[] = [
  { key: 'delicious', emoji: '😊', label: 'おいしかった' },
  { key: 'large_portions', emoji: '🍽️', label: '量が多い' },
  { key: 'good_dessert', emoji: '🍰', label: 'デザートが良い' },
  { key: 'good_atmosphere', emoji: '🎉', label: '雰囲気がいい' },
  { key: 'comfortable', emoji: '🪑', label: '居心地がいい' },
  { key: 'photogenic', emoji: '📸', label: '映える' },
  { key: 'near_station', emoji: '🚶', label: '駅から近い' },
  { key: 'large_groups', emoji: '👨‍👩‍👧‍👦', label: '大人数OK' },
  { key: 'good_nomihodai', emoji: '🍺', label: '飲み放題が良い' },
  { key: 'no_wait', emoji: '🕐', label: '待たなかった' },
];

// 行った後の価格感
export const PRICE_FEEL_REACTIONS: ReactionDef[] = [
  { key: 'cheaper', emoji: '💰', label: '思ったより安かった' },
  { key: 'as_budgeted', emoji: '💰💰', label: '予算どおり' },
  { key: 'expensive_but_worth', emoji: '💰💰💰', label: 'ちょっと高かった(でも価値あり)' },
];

// 全リアクションキーの一覧
export const ALL_REACTIONS = [
  ...BEFORE_REACTIONS,
  ...AFTER_REACTIONS,
  ...PRICE_FEEL_REACTIONS,
];

export const REACTION_MAP = Object.fromEntries(
  ALL_REACTIONS.map((r) => [r.key, r])
) as Record<string, ReactionDef>;
