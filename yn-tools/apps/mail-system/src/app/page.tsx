import { PageLayout, Card } from "@yn-tools/ui";

export default function Home() {
  return (
    <PageLayout title="メール配信システム">
      <Card title="ダッシュボード">
        <p>テンプレートベースのメール送信・連絡先管理システムです。</p>
        <p>（旧 Flask 版からの移行中）</p>
      </Card>
      <Card title="機能一覧（移行予定）">
        <ul>
          <li>連絡先管理</li>
          <li>メールテンプレート作成</li>
          <li>メール送信・プレビュー</li>
          <li>配信履歴</li>
        </ul>
      </Card>
    </PageLayout>
  );
}
