"use client";

import { useEffect, useState } from "react";

interface Stats {
  totalCompanies: number;
  byStatus: Record<string, number>;
  topCompanies: Array<{ name: string; score: number; status: string }>;
}

export default function Dashboard() {
  const [stats, setStats] = useState<Stats | null>(null);

  useEffect(() => {
    fetchStats();
  }, []);

  async function fetchStats() {
    const res = await fetch("/api/crm");
    const data = await res.json();
    const list = data.crmList || [];

    const byStatus: Record<string, number> = {};
    for (const item of list) {
      byStatus[item.status] = (byStatus[item.status] || 0) + 1;
    }

    const top = [...list]
      .sort((a: { score: number }, b: { score: number }) => b.score - a.score)
      .slice(0, 10)
      .map((item: { company: { name: string }; score: number; status: string }) => ({
        name: item.company.name,
        score: item.score,
        status: item.status,
      }));

    setStats({ totalCompanies: list.length, byStatus, topCompanies: top });
  }

  const statuses = ["未営業", "送信済", "返信あり", "商談", "契約"];
  const statusColors: Record<string, string> = {
    "未営業": "#64748b", "送信済": "#3b82f6", "返信あり": "#f59e0b",
    "商談": "#8b5cf6", "契約": "#16a34a",
  };

  return (
    <div>
      <h1 style={{ fontSize: 22, marginBottom: "1.5rem" }}>ダッシュボード</h1>

      {/* パイプライン */}
      <div style={{ display: "flex", gap: "0.75rem", marginBottom: "2rem", flexWrap: "wrap" }}>
        {statuses.map((s) => (
          <div key={s} style={{
            flex: 1, minWidth: 130, padding: "1rem", borderRadius: 8,
            backgroundColor: "#1e293b", border: `2px solid ${statusColors[s]}`,
          }}>
            <div style={{ fontSize: 28, fontWeight: "bold" }}>{stats?.byStatus[s] || 0}</div>
            <div style={{ fontSize: 13, color: statusColors[s] }}>{s}</div>
          </div>
        ))}
      </div>

      {/* スコアTOP10 */}
      <div style={{ backgroundColor: "#1e293b", borderRadius: 8, padding: "1.5rem" }}>
        <h2 style={{ fontSize: 16, marginTop: 0 }}>スコアTOP10</h2>
        {stats?.topCompanies.length === 0 && (
          <p style={{ color: "#64748b" }}>企業データがありません。企業検索から始めましょう。</p>
        )}
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
          <tbody>
            {stats?.topCompanies.map((c, i) => (
              <tr key={i} style={{ borderBottom: "1px solid #334155" }}>
                <td style={{ padding: "0.5rem", width: 30, color: "#64748b" }}>{i + 1}</td>
                <td style={{ padding: "0.5rem" }}>{c.name}</td>
                <td style={{ padding: "0.5rem", textAlign: "right", fontWeight: "bold" }}>{c.score}pt</td>
                <td style={{ padding: "0.5rem", textAlign: "right" }}>
                  <span style={{ fontSize: 12, padding: "2px 8px", borderRadius: 4, backgroundColor: statusColors[c.status] || "#334155" }}>
                    {c.status}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
