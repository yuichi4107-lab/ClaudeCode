"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

interface Company {
  id: number;
  name: string;
  address: string | null;
  phone: string | null;
  websiteUrl: string | null;
  region: string | null;
  crmStatus: { status: string; score: number } | null;
  contacts: Array<{ email: string | null }>;
}

export default function CompaniesPage() {
  const [companies, setCompanies] = useState<Company[]>([]);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [search, setSearch] = useState("");

  useEffect(() => { fetchCompanies(); }, [page]);

  async function fetchCompanies() {
    const params = new URLSearchParams({ page: String(page) });
    if (search) params.set("search", search);
    const res = await fetch(`/api/companies?${params}`);
    const data = await res.json();
    setCompanies(data.companies);
    setTotalPages(data.totalPages);
  }

  return (
    <div>
      <h1 style={{ fontSize: 22, marginBottom: "1rem" }}>企業リスト</h1>
      <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1rem" }}>
        <input
          placeholder="企業名・地域で検索" value={search}
          onChange={(e) => setSearch(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && fetchCompanies()}
          style={inputStyle}
        />
        <button onClick={fetchCompanies} style={btnStyle}>検索</button>
      </div>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
        <thead>
          <tr style={{ borderBottom: "2px solid #334155" }}>
            <th style={thStyle}>企業名</th>
            <th style={thStyle}>地域</th>
            <th style={thStyle}>メール</th>
            <th style={thStyle}>ステータス</th>
            <th style={thStyle}>スコア</th>
          </tr>
        </thead>
        <tbody>
          {companies.map((c) => (
            <tr key={c.id} style={{ borderBottom: "1px solid #1e293b" }}>
              <td style={tdStyle}>
                <Link href={`/companies/${c.id}`} style={{ color: "#60a5fa", textDecoration: "none" }}>
                  {c.name}
                </Link>
              </td>
              <td style={tdStyle}>{c.region || "-"}</td>
              <td style={tdStyle}>{c.contacts?.find((ct) => ct.email)?.email || "-"}</td>
              <td style={tdStyle}>{c.crmStatus?.status || "-"}</td>
              <td style={{ ...tdStyle, textAlign: "right" }}>{c.crmStatus?.score || 0}pt</td>
            </tr>
          ))}
        </tbody>
      </table>
      {companies.length === 0 && <p style={{ color: "#64748b", textAlign: "center", padding: "2rem" }}>企業データがありません</p>}
      <div style={{ display: "flex", justifyContent: "center", gap: "0.5rem", marginTop: "1rem" }}>
        <button onClick={() => setPage(Math.max(1, page - 1))} disabled={page <= 1} style={btnSmall}>前へ</button>
        <span style={{ fontSize: 14, lineHeight: "32px" }}>{page} / {totalPages}</span>
        <button onClick={() => setPage(Math.min(totalPages, page + 1))} disabled={page >= totalPages} style={btnSmall}>次へ</button>
      </div>
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  flex: 1, padding: "0.5rem", backgroundColor: "#1e293b", border: "1px solid #334155",
  borderRadius: 4, color: "#e2e8f0", fontSize: 14,
};
const btnStyle: React.CSSProperties = {
  padding: "0.5rem 1rem", backgroundColor: "#2563eb", color: "white",
  border: "none", borderRadius: 4, cursor: "pointer", fontSize: 14,
};
const btnSmall: React.CSSProperties = { ...btnStyle, padding: "0.25rem 0.75rem", fontSize: 13 };
const thStyle: React.CSSProperties = { textAlign: "left", padding: "0.5rem", color: "#94a3b8" };
const tdStyle: React.CSSProperties = { padding: "0.5rem" };
