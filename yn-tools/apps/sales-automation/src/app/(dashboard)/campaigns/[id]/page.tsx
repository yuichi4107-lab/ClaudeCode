"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";

interface Preview { companyName: string; email: string; subject: string; body: string; }

export default function CampaignDetailPage() {
  const params = useParams();
  const id = Number(params.id);
  const [campaign, setCampaign] = useState<{ name: string; subjectTemplate: string; bodyTemplate: string; status: string } | null>(null);
  const [preview, setPreview] = useState<Preview[]>([]);
  const [sendResult, setSendResult] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetch("/api/campaigns").then((r) => r.json()).then((d) => {
      const c = d.campaigns.find((c: { id: number }) => c.id === id);
      if (c) setCampaign(c);
    });
  }, [id]);

  async function handleDryRun() {
    setLoading(true);
    const res = await fetch("/api/campaigns", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "send", campaignId: id, dryRun: true }),
    });
    const data = await res.json();
    setPreview(data.preview || []);
    setSendResult(`Dry-run完了: ${data.count}件が送信対象`);
    setLoading(false);
  }

  async function handleSend() {
    if (!confirm("本当にメールを送信しますか？")) return;
    setLoading(true);
    const res = await fetch("/api/campaigns", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "send", campaignId: id, dryRun: false }),
    });
    const data = await res.json();
    if (data.error) {
      setSendResult(`エラー: ${data.error}`);
    } else {
      setSendResult(`送信完了: ${data.sentCount}件成功, ${data.failedCount}件失敗`);
    }
    setLoading(false);
  }

  if (!campaign) return <p>読み込み中...</p>;

  return (
    <div>
      <h1 style={{ fontSize: 22, marginBottom: "0.5rem" }}>{campaign.name}</h1>
      <div style={{ backgroundColor: "#1e293b", borderRadius: 8, padding: "1.5rem", marginBottom: "1rem" }}>
        <p style={{ color: "#94a3b8", fontSize: 13, margin: 0 }}>件名:</p>
        <p style={{ margin: "0.25rem 0 1rem" }}>{campaign.subjectTemplate}</p>
        <p style={{ color: "#94a3b8", fontSize: 13, margin: 0 }}>本文:</p>
        <pre style={{ whiteSpace: "pre-wrap", margin: "0.25rem 0", fontSize: 14 }}>{campaign.bodyTemplate}</pre>
      </div>

      <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1rem" }}>
        <button onClick={handleDryRun} disabled={loading} style={btnStyle}>
          {loading ? "処理中..." : "Dry-run（プレビュー）"}
        </button>
        <button onClick={handleSend} disabled={loading} style={{ ...btnStyle, backgroundColor: "#dc2626" }}>
          本送信
        </button>
      </div>

      {sendResult && <p style={{ color: "#4ade80", fontSize: 14 }}>{sendResult}</p>}

      {preview.length > 0 && (
        <div>
          <h3 style={{ fontSize: 16 }}>送信プレビュー（先頭10件）</h3>
          {preview.map((p, i) => (
            <div key={i} style={{ backgroundColor: "#1e293b", padding: "1rem", borderRadius: 6, marginBottom: "0.5rem" }}>
              <div style={{ fontSize: 13, color: "#94a3b8" }}>To: {p.email} ({p.companyName})</div>
              <div style={{ fontWeight: "bold", marginTop: "0.25rem" }}>{p.subject}</div>
              <pre style={{ fontSize: 13, whiteSpace: "pre-wrap", color: "#cbd5e1", marginTop: "0.5rem" }}>{p.body}</pre>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const btnStyle: React.CSSProperties = {
  padding: "0.5rem 1.5rem", backgroundColor: "#2563eb", color: "white",
  border: "none", borderRadius: 4, cursor: "pointer", fontSize: 14,
};
