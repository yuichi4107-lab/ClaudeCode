import { PageLayout, Card } from "@yn-tools/ui";

export default function Home() {
  return (
    <PageLayout title="営業自動化ツール">
      <Card title="ダッシュボード">
        <p>企業検索・キャンペーン管理・CRM機能を提供します。</p>
        <p>（旧 FastAPI 版からの移行中）</p>
      </Card>
      <Card title="機能一覧（移行予定）">
        <ul>
          <li>企業検索・スクレイピング</li>
          <li>キャンペーン管理</li>
          <li>CRM（顧客関係管理）</li>
          <li>設定管理</li>
        </ul>
      </Card>
    </PageLayout>
  );
}
