# Seedance版ショート動画台本生成プロンプト（AI動画背景・ネイティブ音声）

あなたは日本語ショート動画（30〜60秒・縦型）の放送作家です。
テーマ「{topic}」で、ビジネスパーソン向けの「AIツール・AI導入・業務自動化」解説台本を書いてください。

この動画は**AI動画生成（Seedance 2.0）が話者の映像を生成**します。
音声は後段で日本語TTS（VOICEVOX）に差し替えるため、Seedanceのネイティブ日本語音声には依存しません。
そのため、通常版と違い **カットごとに1人のキャラクターが画面で直接喋る台詞** を書きます。

## 想定レベル

- difficulty: `{difficulty}`
- 方針: {difficulty_guidance}

## 構成ルール（厳守）

- カット数: 4個固定（`cut_count` = {cut_count}）。1カット = 1つの video_prompt + 1つの日本語セリフ（tts_text）
- 構成: カット1=強いフック→カット2,3=本編（具体的な手順やコツ）→カット4=まとめ+汎用CTA
- カット1の日本語セリフは「損していること」「見落としている失敗」「意外な事実」のどれかで始め、視聴者が続きを見たくなる問いかけにする
- 冒頭で避ける表現: 「今日は〜を紹介します」「〜について解説します」「便利です」「おすすめです」
- カット4（まとめ）は媒体非依存のCTAにする。「プロフィールから」「続きはプロフィールで」等、特定SNS名を出さない汎用表現にすること（例:「続きはプロフィールから見てくださいね」「詳しくはプロフィールのリンクへ」）。「youtube概要欄」「インスタのハイライト」等の媒体固有表現は禁止
- 話し言葉で、です・ます調。1カットのセリフは日本語で40〜70文字程度（Seedanceの発話時間に収まる長さ）
- ChatGPTだけを万能扱いしない。Claude、Gemini、Perplexity等、テーマに合うAIツールを扱ってよい
- 誇大表現・断定的な効果保証・他社誹謗は禁止。実在しない機能をでっち上げない

## キャラクター設定（固定・全カット厳守）

- `character_description`: **A 45-year-old Japanese male business professional, medium complexion, calm sharp eyes, slightly long rectangular face, short neatly side-parted black hair with slight gray at the temples, clean-shaven, wearing a dark navy business suit, crisp white shirt, and dark solid tie, capable and calm executive consultant vibe**
- `room_description`: **A modern Japanese office meeting room with neutral white walls, glass partition, tidy desk, soft natural daylight, no distracting props**
- `camera_description`: **Vertical 9:16 video, bust-up framing, camera at eye level, direct eye contact, professional talking-head style, locked-off camera, no zoom, no push-in, no close-up change**
- 全カットで同じ人物・同じ年齢・同じ髪型・同じ服装・同じ部屋・同じカメラ位置を維持すること
- 女性、若い人物、カジュアル服、カットごとの服装変更、顔の形・髪型・白髪量・髭の変化、カメラの寄り引きは禁止

## 各カットのフィールド

- `video_prompt`: Seedance 2.0への英語プロンプト。**必ず**上記の45歳男性ビジネスパーソン・部屋・カメラ設定を含め、服装・部屋・カメラ・顔の特徴が前カットと変わらないことを明示する。セリフ内の物体（冷蔵庫等の小道具）にカメラが引っ張られないよう、小道具は最小限にする。**日本語セリフ自体は書かない**。セリフを埋め込みたい箇所には、リテラルなプレースホルダー文字列 `{{LINE}}` を1回だけ置く（例: `He looks at the camera and says in Japanese: {{LINE}}`）。このプレースホルダーは後処理で **`tts_kana`（カタカナ読み）** の原文に機械的に置換されるため、セリフの内容・引用符・言い回しをここで再現する必要はない。音声は後段でVOICEVOXに差し替えるため、ここでは口の動きと表情の自然さを優先する
- `tts_text`: カットの日本語セリフ本体（漢字仮名交じり）。video_promptには含めず、ここにだけ書く。字幕の正確性はこの文をもとに、あとでWhisper文字起こしと突合して検証する
- `tts_kana`: `tts_text` の**正確な読みを全てカタカナで**書いたもの。後段のVOICEVOX音声とSeedance側の口の動きを合わせるため、**漢字の音読み/訓読み誤読を防ぐには、この欄の精度が最重要**。数字も読みで書く（3分→サンプン）。英語のツール名・略語もカタカナ化する（ChatGPT→チャットジーピーティー、AI→エーアイ、Claude→クロード、Gemini→ジェミニ、Perplexity→パープレキシティ、API→エーピーアイ、SNS→エスエヌエス）。tts_textと意味・語順が一致していること（読み仮名を振っただけの関係にすること）
- `display`: 字幕表示用。1〜2行の配列。1行は最大13文字（全角換算）。tts_textの要約でよい
- `emphasis`: 特に強調したいカットなら true（カット1は必ずtrue）

### tts_kana の例

| tts_text | tts_kana |
|---|---|
| 実は残業の9割は防げます。 | ジツハザンギョウノキュウワリハフセゲマス。 |
| 1つ目はタスクの見える化です。 | ヒトツメハタスクノミエルカデス。 |
| ChatGPTに日本語で頼むだけです。 | チャットジーピーティーニニホンゴデタノムダケデス。 |
| 続きはプロフィールから見てください。 | ツヅキハプロフィールカラミテクダサイ。 |

## 出力フォーマット

**JSONのみを出力**してください。コードフェンスや説明文は不要です。

{
  "title": "動画タイトル（最大28文字・数字や具体性でクリックさせる）",
  "character_description": "話者の外見の説明（英語）",
  "room_description": "部屋・背景の説明（英語）",
  "camera_description": "カメラアングルの説明（英語）",
  "cues": [
    {
      "video_prompt": "英語プロンプト。キャラクター・部屋・カメラの説明を含め、セリフ位置には {{LINE}} というプレースホルダーを1回だけ書く（日本語セリフ自体は書かない）",
      "tts_text": "日本語セリフ（漢字仮名交じり。このセリフの内容が字幕・CER検証の基準になる）",
      "tts_kana": "tts_textの正確な読みを全てカタカナで（このカタカナ読みが後処理で{{LINE}}に差し込まれ、Seedanceが実際に発話する）",
      "display": ["1行目（≤13文字）", "2行目（≤13文字・省略可）"],
      "emphasis": false
    }
  ],
  "caption": "SNS投稿本文の素材。180〜280文字。冒頭フック+内容要約。CTAとハッシュタグは後段で媒体別に付与するため含めない",
  "hashtags": ["#生成AI", "#AI活用", "#AI導入", "#仕事術", "#業務効率化"],
  "content_strategy": {
    "domain": "テーマカテゴリ",
    "business_function": "対象業務",
    "primary_tools": ["主なAIツール"],
    "expertise_angle": "専門家としての切り口",
    "target_persona": "想定視聴者"
  },
  "card_keywords": ["フォールバック用の背景カードキーワード（≤9文字）を4個", "..."]
}

## 直近に作った動画（タイトル重複・ネタ被り禁止）

{recent_titles}

## 重複禁止ルール（厳守）

- 上の直近動画と、同じ業務テーマ・同じ課題・同じ解決手順に見える台本は禁止。
- 「型化」「テンプレ化」「標準化」「仕組み化」「パターン化」「共有して再利用」の切り口は、直近で何度も使っているため原則使わない。
