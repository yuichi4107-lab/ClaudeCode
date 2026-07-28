"use client";

import { useEffect, useState } from "react";

export default function SettingsPage() {
  const [host, setHost] = useState("");
  const [port, setPort] = useState("587");
  const [user, setUser] = useState("");
  const [password, setPassword] = useState("");
  const [senderName, setSenderName] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    fetch("/api/settings").then((r) => r.json()).then((d) => {
      const s = d.settings;
      setHost(s.smtp_host || "");
      setPort(s.smtp_port || "587");
      setUser(s.smtp_user || "");
      setSenderName(s.smtp_sender_name || "");
    });
  }, []);

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    const res = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "save", smtpHost: host, smtpPort: port, smtpUser: user, smtpPassword: password, senderName }),
    });
    const data = await res.json();
    setMessage(data.success ? "保存しました" : "保存に失敗しました");
  }

  return (
    <div>
      <h1 style={{ fontSize: 22, marginBottom: "1rem" }}>SMTP設定</h1>
      <form onSubmit={handleSave} style={{ maxWidth: 500 }}>
        <label style={labelStyle}>SMTPホスト</label>
        <input value={host} onChange={(e) => setHost(e.target.value)} style={inputStyle} placeholder="mail.example.com" />

        <label style={labelStyle}>ポート</label>
        <input value={port} onChange={(e) => setPort(e.target.value)} style={inputStyle} placeholder="587" />

        <label style={labelStyle}>ユーザー（メールアドレス）</label>
        <input value={user} onChange={(e) => setUser(e.target.value)} style={inputStyle} />

        <label style={labelStyle}>パスワード</label>
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} style={inputStyle}
          placeholder="変更する場合のみ入力" />

        <label style={labelStyle}>送信者名（任意）</label>
        <input value={senderName} onChange={(e) => setSenderName(e.target.value)} style={inputStyle} />

        {message && <p style={{ color: "#4ade80", fontSize: 14 }}>{message}</p>}
        <button type="submit" style={btnStyle}>保存</button>
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
  marginTop: "1.5rem", padding: "0.5rem 2rem", backgroundColor: "#2563eb",
  color: "white", border: "none", borderRadius: 4, cursor: "pointer", fontSize: 14,
};
