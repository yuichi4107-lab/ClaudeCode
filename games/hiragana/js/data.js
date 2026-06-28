// ひらがな学習ゲームの出題データ
//
// 各お題は1つのオブジェクトで表します。
//   word     : 表示・読み上げる単語（ひらがな）
//   answer   : 正解となる「さいしょの ひらがな」
//   emoji    : いますぐ使う絵（絵文字）
//   image    : あとで差し替える画像パス（null のうちは emoji を表示する）
//   category : 'vehicle'（はたらくくるま） / 'animal'（どうぶつ）
//   say      : （任意）読み上げ専用テキスト。指定すると word の代わりにこれを読み上げる。
//              カタカナ表記にするとアクセントが自然になりやすい（例: 'パトカー'）。
//
// ▼ 絵を本物の画像に差し替えたいとき
//   1) games/hiragana/assets/images/ に画像ファイル（png/svg など）を置く
//   2) そのお題の image に "assets/images/ファイル名" を設定する
//   例: { word: 'いぬ', answer: 'い', emoji: '🐶', image: 'assets/images/inu.png', category: 'animal' }
//   image が設定されていれば emoji より優先して画像が表示されます。

const ITEMS = [
  // --- はたらく くるま ---
  { word: 'しょうぼうしゃ', answer: 'し', emoji: '🚒', image: null, category: 'vehicle' },
  { word: 'とれーらー',     answer: 'と', emoji: '🚛', image: null, category: 'vehicle' },
  { word: 'しょべるかー',   answer: 'し', emoji: '🏗️', image: null, category: 'vehicle' },
  { word: 'だんぷかー',     answer: 'だ', emoji: '🚜', image: null, category: 'vehicle' },
  { word: 'くるま',         answer: 'く', emoji: '🚗', image: null, category: 'vehicle' },
  { word: 'でんしゃ',       answer: 'で', emoji: '🚃', image: null, category: 'vehicle' },
  { word: 'ばす',           answer: 'ば', emoji: '🚌', image: null, category: 'vehicle' },
  { word: 'ひこうき',       answer: 'ひ', emoji: '✈️', image: null, category: 'vehicle' },
  { word: 'ふね',           answer: 'ふ', emoji: '🚢', image: null, category: 'vehicle' },
  { word: 'たくしー',       answer: 'た', emoji: '🚕', image: null, category: 'vehicle' },
  { word: 'ぱとかー',       answer: 'ぱ', emoji: '🚓', image: null, category: 'vehicle', say: 'パトカー' },
  { word: 'ろけっと',       answer: 'ろ', emoji: '🚀', image: null, category: 'vehicle' },

  // --- どうぶつ ---
  { word: 'いぬ',           answer: 'い', emoji: '🐶', image: null, category: 'animal' },
  { word: 'ねこ',           answer: 'ね', emoji: '🐱', image: null, category: 'animal' },
  { word: 'きりん',         answer: 'き', emoji: '🦒', image: null, category: 'animal' },
  { word: 'らいおん',       answer: 'ら', emoji: '🦁', image: null, category: 'animal' },
  { word: 'うさぎ',         answer: 'う', emoji: '🐰', image: null, category: 'animal' },
  { word: 'ぞう',           answer: 'ぞ', emoji: '🐘', image: null, category: 'animal' },
  { word: 'さる',           answer: 'さ', emoji: '🐵', image: null, category: 'animal' },
  { word: 'ぱんだ',         answer: 'ぱ', emoji: '🐼', image: null, category: 'animal' },
  { word: 'うま',           answer: 'う', emoji: '🐴', image: null, category: 'animal' },
  { word: 'ぶた',           answer: 'ぶ', emoji: '🐷', image: null, category: 'animal' },
  { word: 'かめ',           answer: 'か', emoji: '🐢', image: null, category: 'animal' },
  { word: 'とり',           answer: 'と', emoji: '🐦', image: null, category: 'animal', say: 'トリ' },
  { word: 'くま',           answer: 'く', emoji: '🐻', image: null, category: 'animal' },
  { word: 'ぺんぎん',       answer: 'ぺ', emoji: '🐧', image: null, category: 'animal' },
];
