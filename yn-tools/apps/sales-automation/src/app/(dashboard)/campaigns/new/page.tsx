"use client";

import { useState } from "react";

export default function NewCampaignPage() {
  const [name, setName] = useState("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [message, setMessage] = useState("");

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    const res = await fetch("/api/campaigns", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "create", name, subjectTemplate: subject, bodyTemplate: body }),
    });
    const data = await res.json();
    if (data.success) {
      window.location.href = `/campaigns/${data.campaign.id}`;
    } else {
      setMessage(data.error || "作成に失敗しました");
    }
  }

  return (
    <div>
      <h1 style={{ fontSize: 22, marginBottom: "1rem" }}>新規キャンペーン作成</h1>
      <form onSubmit={handleCreate} style={{ maxWidth: 700 }}>
        <label style={labelStyle}>キャンペーン名</label>
        <input value={name} onChange={(e) => setName(e.target.value)} style={inputStyle} required />

        <label style={labelStyle}>件名テンプレート</label>
        <input value={subject} onChange={(e) => setSubject(e.target.value)} style={inputStyle}
          placeholder="$company_name 様へのご提案" required />

        <label style={labelStyle}>本文テンプレート</label>
        <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={10} style={{ ...inputStyle, resize: "vertical" }}
          placeholder="$company_name 御中&#10;&#10;お忙しいところ恐れ入ります。&#10;..." required />

        <p style={{ fontSize: 12, color: "#64748b" }}>
          変数: $company_name（企業名）, $address（住所）, $industry（業種）
        </p>

        {message && <p style={{ color: "#f87171" }}>{message}</p>}
        <button type="submit" style={btnStyle}>作成</button>
      </form>
    </div>
  );
}

const labelStyle: React.CSSProperties = { display: "block", fontSize: 13, color: "#94a3b8", marginBottom: "0.25rem", marginTop: "1rem" };
const inputStyle: React.CSSProperties = {
  width: "100%", padding: "0.5rem", backgroundColor: "#1e293b", border: "1px solid #334155",
  borderRadius: 4, color: "#e2e8f0", fontSize: 14, boxSizing: "border-box",
};
const btnStyle: React.CSSProperties = {
  marginTop: "1rem", padding: "0.5rem 2rem", backgroundColor: "#2563eb",
  color: "white", border: "none", borderRadius: 4, cursor: "pointer", fontSize: 14,
};
