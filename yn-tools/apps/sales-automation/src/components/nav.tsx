"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const links = [
  { href: "/", label: "ダッシュボード" },
  { href: "/companies", label: "企業リスト" },
  { href: "/companies/search", label: "企業検索" },
  { href: "/scraper", label: "一括巡回" },
  { href: "/campaigns", label: "キャンペーン" },
  { href: "/crm", label: "CRM" },
  { href: "/settings", label: "設定" },
];

export function Nav() {
  const pathname = usePathname();

  async function handleLogout() {
    await fetch("/api/auth", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "logout" }),
    });
    window.location.href = "/login";
  }

  return (
    <nav style={{
      backgroundColor: "#1e293b",
      padding: "0.75rem 1.5rem",
      display: "flex",
      alignItems: "center",
      gap: "0.5rem",
      flexWrap: "wrap",
      borderBottom: "1px solid #334155",
    }}>
      <span style={{ fontWeight: "bold", fontSize: 16, marginRight: "1rem", color: "#60a5fa" }}>
        営業自動化ツール
      </span>
      {links.map((link) => (
        <Link
          key={link.href}
          href={link.href}
          style={{
            color: pathname === link.href ? "#60a5fa" : "#94a3b8",
            textDecoration: "none",
            fontSize: 14,
            padding: "0.25rem 0.75rem",
            borderRadius: 4,
            backgroundColor: pathname === link.href ? "#1e3a5f" : "transparent",
          }}
        >
          {link.label}
        </Link>
      ))}
      <button
        onClick={handleLogout}
        style={{
          marginLeft: "auto",
          background: "none",
          border: "1px solid #475569",
          color: "#94a3b8",
          padding: "0.25rem 0.75rem",
          borderRadius: 4,
          cursor: "pointer",
          fontSize: 13,
        }}
      >
        ログアウト
      </button>
    </nav>
  );
}
