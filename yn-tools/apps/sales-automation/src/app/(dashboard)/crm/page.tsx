"use client";

import { useEffect, useState } from "react";

interface CrmItem {
  id: number;
  companyId: number;
  status: string;
  score: number;
  memo: string | null;
  isBlacklisted: boolean;
  company: { id: number; name: string; websiteUrl: string | null; contacts: Array<{ email: string | null }> };
}

const STATUSES = ["全て", "未営業", "送信済", "返信あり", "商談", "契約", "ブラックリスト"];

export default function CrmPage() {
  const [items, setItems] = useState<CrmItem[]>([]);
  const [tab, setTab] = useState("全て");

  useEffect(() => { fetchCrm(); }, [tab]);

  async function fetchCrm() {
    const params = new URLSearchParams();
    if (tab === "ブラックリスト") params.set("blacklist", "true");
    else if (tab !== "全て") params.set("status", tab);
    const res = await fetch(`/api/crm?${params}`);
    const data = await res.json();
    setItems(data.crmList || []);
  }

  async function updateStatus(companyId: number, status: string) {
    await fetch("/api/crm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "updateStatus", companyId, status }),
    });
    fetchCrm();
  }

  async function toggleBlacklist(companyId: number) {
    await fetch("/api/crm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "toggleBlacklist", companyId }),
    });
    fetchCrm();
  }

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
        <h1 style={{ fontSize: 22, margin: 0 }}>CRM管理</h1>
        <a href="/api/export" style={{ ...btnStyle, textDecoration: "none", display: "inline-block" }}>CSV出力</a>
      </div>

      <div style={{ display: "flex", gap: "0.25rem", marginBottom: "1rem", flexWrap: "wrap" }}>
        {STATUSES.map((s) => (
          <button key={s} onClick={() => setTab(s)}
            style={{ padding: "0.3rem 0.75rem", fontSize: 13, borderRadius: 4, border: "none", cursor: "pointer",
              backgroundColor: tab === s ? "#2563eb" : "#1e293b", color: tab === s ? "white" : "#94a3b8" }}>
            {s}
          </button>
        ))}
      </div>

      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
        <thead><tr style={{ borderBottom: "2px solid #334155" }}>
          <th style={thStyle}>企業名</th><th style={thStyle}>メール</th>
          <th style={thStyle}>スコア</th><th style={thStyle}>ステータス</th><th style={thStyle}>操作</th>
        </tr></thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.id} style={{ borderBottom: "1px solid #1e293b" }}>
              <td style={tdStyle}>{item.company.name}</td>
              <td style={tdStyle}>{item.company.contacts?.find((c) => c.email)?.email || "-"}</td>
              <td style={{ ...tdStyle, textAlign: "right" }}>{item.score}pt</td>
              <td style={tdStyle}>
                <select value={item.status}
                  onChange={(e) => updateStatus(item.companyId, e.target.value)}
                  style={{ backgroundColor: "#0f172a", color: "#e2e8f0", border: "1px solid #334155", borderRadius: 4, padding: "2px 4px", fontSize: 13 }}>
                  {["未営業", "送信済", "返信あり", "商談", "契約"].map((s) => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              </td>
              <td style={tdStyle}>
                <button onClick={() => toggleBlacklist(item.companyId)}
                  style={{ fontSize: 12, padding: "2px 8px", border: "1px solid #475569", borderRadius: 4, backgroundColor: "transparent", color: "#94a3b8", cursor: "pointer" }}>
                  {item.isBlacklisted ? "解除" : "BL追加"}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {items.length === 0 && <p style={{ color: "#64748b", textAlign: "center", padding: "2rem" }}>データがありません</p>}
    </div>
  );
}

const btnStyle: React.CSSProperties = {
  padding: "0.4rem 1rem", backgroundColor: "#16a34a", color: "white",
  border: "none", borderRadius: 4, cursor: "pointer", fontSize: 13,
};
const thStyle: React.CSSProperties = { textAlign: "left", padding: "0.5rem", color: "#94a3b8" };
const tdStyle: React.CSSProperties = { padding: "0.5rem" };
