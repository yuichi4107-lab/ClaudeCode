"""日本語テキストの正規化・読み突合・CER計算ユーティリティ。

字幕正確性検証の中核: 台本（意図した読み）と Whisper 逆文字起こし結果を
表記ゆれに頑健な形で突き合わせるための正規化を提供する。
"""
from __future__ import annotations

import re
import unicodedata

# 英語表記 → カタカナ読みの対訳表。
# VOICEVOXユーザー辞書への登録と、CER計算前のエイリアス畳み込みの両方で使う。
TERM_READINGS: dict[str, str] = {
    # ジィー等の小書き母音つづりは VOICEVOX の発音が明瞭になり、Whisper の
    # 聞き取り精度が上がる実測結果に基づく（音韻比較では ジー と同一視される）
    "ChatGPT": "チャットジィーピィーティィー",
    "GPT": "ジィーピィーティィー",
    "OpenAI": "オープンエーアイ",
    "Claude": "クロード",
    "Gemini": "ジェミニ",
    "Perplexity": "パープレキシティ",
    "NotebookLM": "ノートブックエルエム",
    "Copilot": "コパイロット",
    "AI": "エーアÂ�",
    "DX": "ディーエックス",
    "PDF": "ピーディーエフ",
    "SNS": "エスエヌエス",
    "URL": "ユーアールエル",
    "Excel": "エクセル",
    "Word": "ワード",
    "PowerPoint": "パワーポイント",
    "Google Drive": "グーグルドライブ",
    "Google Docs": "グーグルドキュメント",
    "Google Sheets": "グーグルスプレッドシート",
    "Google Slides": "グーグルスライド",
    "Google": "グーグル",
    "Gmail": "ジーメール",
    "LINE": "ライン",
    "Slack": "スラック",
    "Zoom": "ズーム",
    "Canva": "キャンバ",
    "Gamma": "ガンマ",
    "Figma": "フィグマ",
    "Zapier": "ザピアー",
    "Make": "メイク",
    "n8n": "エヌエイトエヌ",
    "YouTube": "ユーチューブ",
    "Instagram": "インスタグラム",
    "TikTok": "ティックトック",
    "Teams": "チーユズ",
    "Notion": "ノーション",
    "iPhone": "アイフォン",
    "Android": "アンドロイド",
    "Mac": "マック",
    "Windows": "ウィンドウズ",
    "Wi-Fi": "ワイファイ",
    "Web": "ウェブ",
    "IT": "アイティー",
    "OK": "オーケー",
    "NG": "エヌジー",
    "API": "エーピーアイ",
    "LLM": "エルエルエム",
}

# TTS入力直前に適用する「発音明瞭化」置換。台本がカナ直書きでも明瞭発音にする。
# （音韻正規化では両者は同一視されるため、検証への影響はない）
KANA_CLARITY: dict[str, str] = {
    "チャットジーピーティー": "チャットジィーピィーティィー",
    "ジーピーティー": "ジィーピィーティィー",
}


def enhance_tts_clarity(s: str) -> str:
    for plain in sorted(KANA_CLARITY, key=len, reverse=True):
        s = s.replace(plain, KANA_CLARITY[plain])
    return s


_KATA_TO_HIRA = {code: code - 0x60 for code in range(0x30A1, 0x30F7)}  # ァ..ヶ → ぁ..ゖ

_KANJI_DIGITS = {
    "〇": "0", "零": "0", "一": "1", "二": "2", "三": "3", "四": "4",
    "五": "5", "六": "6", "七": "7", "八": "8", "九": "9", "十": "10",
}

_PUNCT_RE = re.compile(r"[\s、。，．,.!！?？「」『』（）()\[\]【】・…〜~ー—\-:：;；'\"’”☆★♪]+")


def kata_to_hira(s: str) -> str:
    return s.translate(_KATA_TO_HIRA)


# 長音の表記ゆれ折り畳み（ひらがな域で適用）:
# こう/こー/こお → こ、せい/せー → せ、しい→し、くう→く、かあ→か
_HIRA_ROWS = {
    "あ": "あかさたなはまやらわがざだばぱぁゃ",
    "い": "いきしちにひみりぎじぢびぴぃ",
    "う": "うくすつぬふむゆるぐずづぶぷぅゅゔ",
    "え": "えけせてねへめれげぜでべぺぇ",
    "お": "おこそとのほもよろごぞどぼぽぉょ",
}
_LONG_VOWEL_PATTERNS = [
    (re.compile(f"([{rows}])[{vowel}]"), r"\1")
    for vowel, rows in _HIRA_ROWS.items()
] + [
    (re.compile(f"([{_HIRA_ROWS['え']}])い"), r"\1"),  # えい→えー系
    (re.compile(f"([{_HIRA_ROWS['お']}])う"), r"\1"),  # おう→おー系
]


_SMALL_VOWELS = str.maketrans("ぁぃぅぇぉ", "あいうえお")


def fold_long_vowels(hira: str) -> str:
    """ひらがな文字列の長音表記ゆれを潰す（こう/こー/こお→こ、じぃー→じ）。

    小書き母音（ぁぃぅぇぉ）は通常母音に寄せる（ゃゅょは音韻が変わるため対象外）。
    """
    hira = hira.translate(_SMALL_VOWELS)
    for pat, rep in _LONG_VOWEL_PATTERNS:
        hira = pat.sub(rep, hira)
    return hira.replace("ー", "")


def fold_aliases(s: str) -> str:
    """英語表記の既知用語をカタカナ読みへ畳み込む（長い語から先に置換）。"""
    for term in sorted(TERM_READINGS, key=len, reverse=True):
        s = re.sub(re.escape(term), TERM_READINGS[term], s, flags=re.IGNORECASE)
    return s


def normalize_for_cer(s: str) -> str:
    """CER計算用の正規化: NFKC → エイリアス畳込 → 句読点除去 → カナ折り畳み 。

    長音「ー」は発音ゆれ（おー/おう 等）の誤検出源なので除去する。
    漢数字は純用数字へ寄せる（三分/3分 のゆれ対策）。
    """
    s = unicodedata.normalize("NFKC", s)
    s = fold_aliases(s)
    s = _PUNCT_RE.sub("", s)
    s = "".join(_KANJI_DIGITS.get(ch, ch) for ch in s)
    s = kata_to_hira(s)
    s = fold_long_vowels(s)
    return s.lower()


_DIGITS_KANA = ["ぜろ", "いち", "に", "さん", "よん", "ご", "ろく", "なな", "はち", "きゅう"]


def _int_to_kana(n: int) -> str:
    """整数→ひらがな読み（〜99999‍）。紐敳の 両韵濁璹及毉 やヵヵ〃クケよアよらち轳どのコ"""
    if n == 0:
        return "ぜろ"
    if n >= 100000:
        return str(n)  # 大きすぎる数はそのまま（両辺同処理なので一致する）
    out = []
    for val, name in ((10000, "まん"), (1000, "せん"), (100, "ひゃく"), (10, "じゅう")):
        d, n = divmod(n, val)
        if d == 0:
            continue
        if d > 1 or val == 10000:
            out.append(_DIGITS_KANA[d])
        out.append(name)
    if n:
        out.append(_DIGITS_KANA[n])
    return "".join(out)


_NUM_RE = re.compile(r"\d+")


def _numbers_to_kana(s: str) -> str:
    return _NUM_RE.sub(lambda m: _int_to_kana(int(m.group(0))), s)


def _fold_voicing(s: str) -> str:
    """濁点・半濁点・促音を除去（ば/ぱ/は→は、いっつう→いつう）。

    Whisper聞き取りと読み生成の音韻ゆれ吸収用。TTSの読み自体の正しさは
    合成層（reading_kana突合＋かな直読みフォールバック）で構造的に保証
    されているため、検証層は「大きく違う音声」を捕まえる網として機能する。
    """
    nfd = unicodedata.normalize("NFD", s)
    return "".join(ch for ch in nfd if ch not in ("゙", "゚", "っ", "ッ"))


_kks = None


def phonetic_hira(s: str) -> str:
    """表記に依存しない音韻比較用の正規化。

    NFKC → 既知用語の読み畳込 → pykakasi で漢字→ひらがな → 句読点除去
    → カナ折り畳み → 長音ゆれ折り畳み。
    台本とWhisper結果の**両辺に同じ変換**をかけることで、同音異字・数字の
    読み・送り仮名のゆれによる誤検出を排除する。
    """
    global _kks
    s = unicodedata.normalize("NFKC", s)
    s = fold_aliases(s)
    try:
        if _kks is None:
            import pykakasi

            _kks = pykakasi.kakasi()
        s = "".join(seg["hira"] for seg in _kks.convert(s))
    except ImportError:
        pass  # pykakasi が無い環境では表記ベース比較にフォールバック
    s = _PUNCT_RE.sub("", s)
    s = "".join(_KANJI_DIGITS.get(ch, ch) for ch in s)
    s = _numbers_to_kana(s)
    s = kata_to_hira(s)
    s = fold_long_vowels(s)
    s = _fold_voicing(s)
    return s.lower()


def phonetic_cer(ref: str, hyp: str) -> float:
    """音韻正規化後の Character Error Rate。"""
    a, b = phonetic_hira(ref), phonetic_hira(hyp)
    if not a:
        return 0.0 if not b else 1.0
    return levenshtein(a, b) / len(a)


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def cer(ref: str, hyp: str) -> float:
    """正規化済み文字列同士の Character Error Rate。ref が空なら 0/1 を返す。"""
    ref_n = normalize_for_cer(ref)
    hyp_n = normalize_for_cer(hyp)
    if not ref_n:
        return 0.0 if not hyp_n else 1.0
    return levenshtein(ref_n, hyp_n) / len(ref_n)


def contained_cer(needle_norm: str, haystack_norm: str) -> float:
    """正規化済み needle に最も近い窓を haystack から探し、そのCERを返す。

    「字幕に表示した内容が実際に話されているか」の包含チェックに使う。
    """
    L = len(needle_norm)
    if not L:
        return 0.0
    if not haystack_norm:
        return 1.0
    best = 1.0
    for wl in {L, max(1, int(L * 0.8)), int(L * 1.2) + 1}:
        step = max(1, L // 4)
        for s in range(0, max(1, len(haystack_norm) - wl + 1), step):
            d = levenshtein(needle_norm, haystack_norm[s : s + wl]) / L
            if d < best:
                best = d
        if best < 0.05:
            break
    return best


def lcs_len(a: str, b: str) -> int:
    """最長共通部分列（順序保持・ギャップ許容）の長さ。"""
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    for ca in a:
        cur = [0]
        for j, cb in enumerate(b, 1):
            cur.append(prev[j - 1] + 1 if ca == cb else max(prev[j], cur[j - 1]))
        prev = cur
    return prev[-1]


def lcs_coverage(needle_norm: str, haystack_norm: str) -> float:
    """needle の文字がどれだけ順序通り haystack に現れるか（0〜1）。

    「字幕に表示した内容が実際に話されているか」の判定。表示側が
    助詞や副詞を省略していても、話されていない語を表示した場合のみ下がる。
    """
    if not needle_norm:
        return 1.0
    return lcs_len(needle_norm, haystack_norm) / len(needle_norm)


def normalize_kana_for_match(s: str) -> str:
    """VOICEVOX audio_query の kana（アクセント記号付き）と読み仮名を比較するための正規化。"""
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"['/_、。?？\s]+", "", s)
    s = s.replace("ヴ", "ブ")
    return fold_long_vowels(kata_to_hira(s))


def kana_cer(ref_kana: str, hyp_kana: str) -> float:
    a = normalize_kana_for_match(ref_kana)
    b = normalize_kana_for_match(hyp_kana)
    if not a:
        return 0.0 if not b else 1.0
    return levenshtein(a, b) / len(a)
