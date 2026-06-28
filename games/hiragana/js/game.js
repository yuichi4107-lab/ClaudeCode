// ひらがな学習ゲーム ロジック
// 絵を見て、その名前の「さいしょの ひらがな」を選ぶクイズ形式。
// 音声はブラウザ内蔵の Web Speech API（speechSynthesis）を使用。

(function () {
  'use strict';

  // ----- 画面要素 -----
  const startScreen = document.getElementById('start-screen');
  const gameScreen = document.getElementById('game-screen');
  const pictureBtn = document.getElementById('picture');
  const pictureContent = document.getElementById('picture-content');
  const choicesEl = document.getElementById('choices');
  const feedbackEl = document.getElementById('feedback');
  const scoreNumEl = document.getElementById('score-num');
  const homeBtn = document.getElementById('home-btn');

  // ----- 状態 -----
  let pool = [];          // 出題プール（選んだカテゴリのお題）
  let current = null;     // いまのお題
  let score = 0;
  let locked = false;     // 連打防止（正解後の遷移中など）
  let speechReady = false; // 最初のタップで音声を有効化

  const CHOICE_COUNT = 3; // 選択肢の数

  // ----- 音声（Web Speech API）-----
  function speak(text, onEnd) {
    if (!speechReady || !('speechSynthesis' in window)) {
      if (onEnd) setTimeout(onEnd, 0); // 音声非対応でも進行できるようフォールバック
      return;
    }
    try {
      window.speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(text);
      u.lang = 'ja-JP';
      u.rate = 0.9;   // 子ども向けに少しゆっくり
      u.pitch = 1.1;
      if (onEnd) {
        let done = false;
        const fire = () => { if (!done) { done = true; onEnd(); } };
        u.onend = fire;
        u.onerror = fire;
      }
      window.speechSynthesis.speak(u);
    } catch (e) {
      // 音声が使えない端末でも無視して続行
      if (onEnd) onEnd();
    }
  }

  // ----- ユーティリティ -----
  function shuffle(arr) {
    const a = arr.slice();
    for (let i = a.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [a[i], a[j]] = [a[j], a[i]];
    }
    return a;
  }

  function pickRandom(arr) {
    return arr[Math.floor(Math.random() * arr.length)];
  }

  // 全お題の頭文字（ダミー選択肢の候補）
  const ALL_ANSWERS = Array.from(new Set(ITEMS.map((it) => it.answer)));

  // ----- お題の表示 -----
  function renderPicture(item) {
    pictureContent.innerHTML = '';
    if (item.image) {
      const img = document.createElement('img');
      img.src = item.image;
      img.alt = item.word;
      img.className = 'picture-img';
      pictureContent.appendChild(img);
    } else {
      const span = document.createElement('span');
      span.className = 'picture-emoji';
      span.textContent = item.emoji;
      pictureContent.appendChild(span);
    }
  }

  // ----- 選択肢の生成 -----
  function buildChoices(item) {
    const choices = [item.answer];
    // 正解以外の頭文字からダミーを集める
    const others = shuffle(ALL_ANSWERS.filter((c) => c !== item.answer));
    for (const c of others) {
      if (choices.length >= CHOICE_COUNT) break;
      choices.push(c);
    }
    return shuffle(choices);
  }

  // ----- 出題 -----
  function nextQuestion() {
    locked = false;
    hideFeedback();
    current = pickRandom(pool);
    renderPicture(current);

    choicesEl.innerHTML = '';
    const choices = buildChoices(current);
    for (const ch of choices) {
      const btn = document.createElement('button');
      btn.className = 'choice-btn';
      btn.textContent = ch;
      btn.addEventListener('click', () => onChoice(btn, ch));
      choicesEl.appendChild(btn);
    }

    // 少し待ってから単語を読み上げ（画面切り替えの直後を避ける）
    setTimeout(() => speak(current.word), 350);
  }

  // ----- 解答処理 -----
  function onChoice(btn, value) {
    if (locked) return;

    if (value === current.answer) {
      locked = true;
      btn.classList.add('correct');
      score += 1;
      scoreNumEl.textContent = String(score);
      showFeedback('せいかい！ 🎉', 'ok');
      // 「せいかい！」を読み上げ、それが終わってから少し間を置いて次の問題へ
      speak('せいかい！', () => setTimeout(nextQuestion, 900));
    } else {
      // 不正解：やさしく「もういちど」。正解ボタンは残して再挑戦可。
      btn.classList.add('wrong');
      btn.disabled = true;
      showFeedback('もういちど 😊', 'ng');
      speak('もういちど');
    }
  }

  // ----- フィードバック表示 -----
  function showFeedback(text, type) {
    feedbackEl.textContent = text;
    feedbackEl.className = 'feedback ' + type;
    // アニメをやり直すための再トリガ
    void feedbackEl.offsetWidth;
    feedbackEl.classList.add('show');
  }

  function hideFeedback() {
    feedbackEl.className = 'feedback hidden';
  }

  // ----- 画面遷移 -----
  function startGame(category) {
    pool = category === 'all' ? ITEMS.slice() : ITEMS.filter((it) => it.category === category);
    if (pool.length === 0) pool = ITEMS.slice();
    score = 0;
    scoreNumEl.textContent = '0';
    startScreen.classList.add('hidden');
    gameScreen.classList.remove('hidden');
    nextQuestion();
  }

  function goHome() {
    if ('speechSynthesis' in window) window.speechSynthesis.cancel();
    gameScreen.classList.add('hidden');
    startScreen.classList.remove('hidden');
  }

  // ----- イベント登録 -----
  document.querySelectorAll('.cat-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      speechReady = true; // 最初のユーザー操作で音声を有効化（autoplay制約対策）
      startGame(btn.dataset.category);
    });
  });

  homeBtn.addEventListener('click', goHome);

  // 絵をタップすると単語を読み上げ直す（聞き直し）
  pictureBtn.addEventListener('click', () => {
    if (current) speak(current.word);
  });

})();
