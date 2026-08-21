"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

interface Campaign {
  id: number;
  name: string;
  status: string;
  createdAt: string;
  _count: { outreachLogs: number };
}

export default function CampaignsPage() {
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);

  useEffect(() => {
    fetch("/api/campaigns").then((r) => r.json()).then((d) => setCampaigns(d.campaigns || []));
  }, []);

  const statusLabel: Record<string, string> = {
    draft: "下書き", active: "送信中", paused: "停止", completed: "完了",
  };

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
        <h1 style={{ fontSize: 22, margin: 0 }}>キャンペーン</h1>
        <Link href="/campaigns/new" style={{ ...btnStyle, textDecoration: "none" }}>新規作成</Link>
      </div>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
        <thead><tr style={{ borderBottom: "2px solid #334155" }}>
          <th style={thStyle}>キャンペーン名</th><th style={thStyle}>ステータス</th>
          <th style={thStyle}>送信数</th><th style={thStyle}>作成日</th>
        </tr></thead>
        <tbody>
          {campaigns.map((c) => (
            <tr key={c.id} style={{ borderBottom: "1px solid #1e293b" }}>
              <td style={tdStyle}>
                <Link href={`/campaigns/${c.id}`} style={{ color: "#60a5fa", textDecoration: "none" }}>{c.name}</Link>
              </td>
              <td style={tdStyle}>{statusLabel[c.status] || c.status}</td>
              <td style={{ ...tdStyle, textAlign: "right" }}>{c._count.outreachLogs}</td>
              <td style={tdStyle}>{new Date(c.createdAt).toLocaleDateString("ja-JP")}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {campaigns.length === 0 && <p style={{ color: "#64748b", textAlign: "center", padding: "2rem" }}>キャンペーンがありません</p>}
    </div>
  );
}

const btnStyle: React.CSSProperties = {
  padding: "0.4rem 1rem", backgroundColor: "#2563eb", color: "white",
  border: "none", borderRadius: 4, cursor: "pointer", fontSize: 14,
};
const thStyle: React.CSSProperties = { textAlign: "left", padding: "0.5rem", color: "#94a3b8" };
const tdStyle: React.CSSProperties = { padding: "0.5rem" };
