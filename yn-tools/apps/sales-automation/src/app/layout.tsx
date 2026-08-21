import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "営業自動化ツール",
  description: "企業検索・CRM管理・メールキャンペーン",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ja">
      <body style={{ margin: 0, fontFamily: "sans-serif", backgroundColor: "#0f172a", color: "#e2e8f0" }}>
        {children}
      </body>
    </html>
  );
}
