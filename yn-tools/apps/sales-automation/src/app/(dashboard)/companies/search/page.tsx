"use client";

import { useState } from "react";

interface SearchResult {
  name: string;
  address: string;
  phone: string;
}

export default function CompanySearchPage() {
  const [keyword, setKeyword] = useState("");
  const [region, setRegion] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");

  async function handleSearch() {
    if (!keyword) return;
    setLoading(true);
    setMessage("");
    const res = await fetch("/api/companies", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "search_scraping", keyword, region }),
    });
    const data = await res.json();
    setResults(data.results || []);
    setLoading(false);
  }

  async function handleAdd() {
    const res = await fetch("/api/companies", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        action: "add",
        companies: results.map((r) => ({ name: r.name, address: r.address, phone: r.phone, region })),
      }),
    });
    const data = await res.json();
    setMessage(`${data.created}件を追加しました。`);
  }

  return (
    <div>
      <h1 style={{ fontSize: 22, marginBottom: "1rem" }}>企業検索</h1>
      <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1rem", flexWrap: "wrap" }}>
        <input placeholder="キーワード（例: Web制作）" value={keyword}
          onChange={(e) => setKeyword(e.target.value)} style={{ ...inputStyle, flex: 2 }} />
        <input placeholder="地域（例: 東京都）" value={region}
          onChange={(e) => setRegion(e.target.value)} style={{ ...inputStyle, flex: 1 }} />
        <button onClick={handleSearch} disabled={loading} style={btnStyle}>
          {loading ? "検索中..." : "検索"}
        </button>
      </div>

      {results.length > 0 && (
        <>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.5rem" }}>
            <span style={{ fontSize: 14, color: "#94a3b8" }}>{results.length}件の結果</span>
            <button onClick={handleAdd} style={{ ...btnStyle, backgroundColor: "#16a34a" }}>
              すべて一覧に追加
            </button>
          </div>
          {message && <p style={{ color: "#4ade80", fontSize: 14 }}>{message}</p>}
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
            <thead><tr style={{ borderBottom: "2px solid #334155" }}>
              <th style={thStyle}>企業名</th><th style={thStyle}>住所</th><th style={thStyle}>電話番号</th>
            </tr></thead>
            <tbody>
              {results.map((r, i) => (
                <tr key={i} style={{ borderBottom: "1px solid #1e293b" }}>
                  <td style={tdStyle}>{r.name}</td>
                  <td style={tdStyle}>{r.address}</td>
                  <td style={tdStyle}>{r.phone}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  padding: "0.5rem", backgroundColor: "#1e293b", border: "1px solid #334155",
  borderRadius: 4, color: "#e2e8f0", fontSize: 14,
};
const btnStyle: React.CSSProperties = {
  padding: "0.5rem 1rem", backgroundColor: "#2563eb", color: "white",
  border: "none", borderRadius: 4, cursor: "pointer", fontSize: 14,
};
const thStyle: React.CSSProperties = { textAlign: "left", padding: "0.5rem", color: "#94a3b8" };
const tdStyle: React.CSSProperties = { padding: "0.5rem" };
