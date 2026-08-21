"use client";

import { useState } from "react";

export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    const res = await fetch("/api/auth", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "login", username, password }),
    });
    const data = await res.json();
    if (data.success) {
      window.location.href = "/";
    } else {
      setError(data.error);
    }
  }

  return (
    <div style={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center" }}>
      <form onSubmit={handleSubmit} style={{ width: 360, padding: "2rem", backgroundColor: "#1e293b", borderRadius: 8 }}>
        <h1 style={{ fontSize: 20, marginBottom: "1.5rem", textAlign: "center" }}>営業自動化ツール</h1>
        <input
          type="text" placeholder="ユーザー名" value={username}
          onChange={(e) => setUsername(e.target.value)}
          style={inputStyle}
        />
        <input
          type="password" placeholder="パスワード" value={password}
          onChange={(e) => setPassword(e.target.value)}
          style={inputStyle}
        />
        {error && <p style={{ color: "#f87171", fontSize: 14 }}>{error}</p>}
        <button type="submit" style={btnStyle}>ログイン</button>
        <p style={{ textAlign: "center", fontSize: 13, color: "#64748b", marginTop: "1rem" }}>
          初回の方は <a href="/setup" style={{ color: "#60a5fa" }}>こちら</a>
        </p>
      </form>
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  width: "100%", padding: "0.6rem", marginBottom: "0.75rem",
  backgroundColor: "#0f172a", border: "1px solid #334155", borderRadius: 4,
  color: "#e2e8f0", fontSize: 14, boxSizing: "border-box",
};
const btnStyle: React.CSSProperties = {
  width: "100%", padding: "0.6rem", backgroundColor: "#2563eb",
  color: "white", border: "none", borderRadius: 4, cursor: "pointer",
  fontSize: 14, fontWeight: "bold",
};
