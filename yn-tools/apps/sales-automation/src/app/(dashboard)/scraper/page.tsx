"use client";

import { useState } from "react";

export default function ScraperPage() {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<{ crawled: number; failed: number; total: number } | null>(null);

  async function handleBulkCrawl() {
    setLoading(true);
    setResult(null);
    const res = await fetch("/api/scraper", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "bulk_crawl" }),
    });
    const data = await res.json();
    setResult(data);
    setLoading(false);
  }

  return (
    <div>
      <h1 style={{ fontSize: 22, marginBottom: "1rem" }}>一括HP巡回</h1>
      <div style={{ backgroundColor: "#1e293b", borderRadius: 8, padding: "1.5rem" }}>
        <p style={{ color: "#94a3b8", fontSize: 14, marginTop: 0 }}>
          未巡回の企業HPを巡回し、メールアドレス・お問い合わせフォーム・SNSリンクを自動抽出します。
          スコアも自動計算されます。
        </p>
        <button onClick={handleBulkCrawl} disabled={loading} style={btnStyle}>
          {loading ? "巡回中..." : "一括巡回を開始"}
        </button>
        {result && (
          <div style={{ marginTop: "1rem", padding: "1rem", backgroundColor: "#0f172a", borderRadius: 6 }}>
            <p style={{ margin: 0 }}>対象: {result.total}件</p>
            <p style={{ margin: 0, color: "#4ade80" }}>成功: {result.crawled}件</p>
            {result.failed > 0 && <p style={{ margin: 0, color: "#f87171" }}>失敗: {result.failed}件</p>}
          </div>
        )}
      </div>
    </div>
  );
}

const btnStyle: React.CSSProperties = {
  padding: "0.5rem 2rem", backgroundColor: "#2563eb", color: "white",
  border: "none", borderRadius: 4, cursor: "pointer", fontSize: 14, fontWeight: "bold",
};
