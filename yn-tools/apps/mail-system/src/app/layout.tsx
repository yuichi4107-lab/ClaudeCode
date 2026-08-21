import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "メール配信システム",
  description: "テンプレートベースのメール送信・連絡先管理",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ja">
      <body>{children}</body>
    </html>
  );
}
