/**
 * AI活用 先行案内フォーム 自動作成スクリプト
 * 使い方:
 *   1. https://script.google.com にアクセス → 「新しいプロジェクト」
 *   2. 既定の myFunction() のコードを全削除し、本ファイルの内容をすべて貼り付け
 *   3. 上部メニューで関数 "createPreRegistrationForm" が選択されていることを確認
 *   4. 「実行」ボタン → 初回は権限承認を求められるので「許可」
 *   5. 「実行ログ」に出力された以下の2つのURLが最終成果物:
 *        - Published URL（回答者に配る公開URL）
 *        - Edit URL（自分が編集するためのURL）
 */
function createPreRegistrationForm() {
  var form = FormApp.create('AI活用の設計力 講座・コミュニティ 先行案内リスト');

  // 説明文
  form.setDescription(
    'AI活用の「設計力」を学べる講座・コミュニティを準備しています。\n\n' +
    'note のシリーズ『AIを使いこなす』を読んでくださった方で、今後の先行案内を受け取りたい方は、下記フォームからメールアドレスをご登録ください。\n\n' +
    '■ 案内が届くタイミング\n' +
    '・講座の開講日程が決まったとき\n' +
    '・コミュニティの開設準備が整ったとき\n' +
    '・上記に関する追加情報がまとまったとき\n\n' +
    '■ このフォームについて\n' +
    '・登録は無料です\n' +
    '・いつでも解除できます（届くメールの末尾に解除リンクを記載）\n' +
    '・登録情報は本案内以外の目的では使用しません'
  );

  // 設定（各設定を個別にtry-catchで囲む — Workspace依存の設定が個人アカウントで失敗しても他の設定は適用）
  try { form.setCollectEmail(false); } catch (e) { Logger.log('[WARN] setCollectEmail: ' + e); }
  // setRequireLogin は Workspace アカウント専用のため、個人Gmailでは呼ばない（既定値=false）
  try { form.setLimitOneResponsePerUser(false); } catch (e) { Logger.log('[WARN] setLimitOneResponsePerUser: ' + e); }
  try { form.setAllowResponseEdits(false); } catch (e) { Logger.log('[WARN] setAllowResponseEdits: ' + e); }
  try { form.setShowLinkToRespondAgain(false); } catch (e) { Logger.log('[WARN] setShowLinkToRespondAgain: ' + e); }

  // 送信後メッセージ
  form.setConfirmationMessage(
    'ご登録ありがとうございます。\n\n' +
    '講座・コミュニティの準備が整い次第、ご登録いただいたアドレスに先行案内をお送りします。\n\n' +
    '■ 登録の解除について\n' +
    '今後の案内が不要になった場合は、お送りするメールの末尾にある解除リンクからいつでも解除できます。\n\n' +
    '■ しばらくの間\n' +
    '準備状況の進捗を note やSNSでも発信していきます。よろしければ併せてフォローしてみてください。'
  );

  // Q1: メールアドレス（必須、メール形式検証つき）
  var q1 = form.addTextItem()
    .setTitle('メールアドレス')
    .setHelpText('案内メールをお送りする先のアドレスをご記入ください')
    .setRequired(true);
  var emailValidation = FormApp.createTextValidation()
    .setHelpText('有効なメールアドレスをご入力ください')
    .requireTextMatchesPattern('^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$')
    .build();
  q1.setValidation(emailValidation);

  // Q2: 立場（任意・単一選択）
  form.addMultipleChoiceItem()
    .setTitle('あなたに近い立場はどちらですか？')
    .setHelpText('案内内容を立場に合わせて最適化するための任意項目です')
    .setChoiceValues([
      '個人事業主・副業・フリーランス（Bタイプ）',
      '経営者・マネージャー（小規模組織）（Cタイプ）',
      '上記にあてはまらない／まだ決めていない',
      'その他'
    ])
    .setRequired(false);

  // Q3: 興味テーマ（任意・複数可）
  form.addCheckboxItem()
    .setTitle('特に興味のあるテーマはどれですか？（複数選択可）')
    .setHelpText('今後の講座・コミュニティの設計に反映させていただきます')
    .setChoiceValues([
      'タスク設計の3問フレーム',
      '境界線設計（AIに任せる／自分が握るの切り分け）',
      'AI部署の組織設計',
      '品質評価の基準づくり',
      '具体的な事例・ケーススタディ',
      '参加者同士の交流・相談'
    ])
    .setRequired(false);

  // Q4: 自由記述（任意）
  form.addParagraphTextItem()
    .setTitle('ご質問・ご要望など（任意）')
    .setHelpText('現時点でのAI活用に関するお悩みや、講座・コミュニティに期待することがあればお書きください。すべて拝読します。')
    .setRequired(false);

  // URLをログに出力
  var publishedUrl = form.getPublishedUrl();
  var editUrl = form.getEditUrl();
  var shortUrl = null;
  try {
    shortUrl = form.shortenFormUrl(publishedUrl);
  } catch (e) {
    Logger.log('[WARN] shortenFormUrl failed (承認スコープ不足の可能性): ' + e);
  }

  Logger.log('===============================================');
  Logger.log('Form created successfully.');
  Logger.log('-----------------------------------------------');
  Logger.log('Published URL (回答者に配る):');
  Logger.log(publishedUrl);
  if (shortUrl) {
    Logger.log('-----------------------------------------------');
    Logger.log('Short URL (短縮版):');
    Logger.log(shortUrl);
  }
  Logger.log('-----------------------------------------------');
  Logger.log('Edit URL (自分用):');
  Logger.log(editUrl);
  Logger.log('===============================================');

  return { publishedUrl: publishedUrl, shortUrl: shortUrl, editUrl: editUrl };
}
