import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "勤怠管理Webアプリ",
  description: "イースタッフィング勤怠CSVの集計・datファイル変換",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ja">
      <body style={{ margin: 0, backgroundColor: "#ffffff" }}>{children}</body>
    </html>
  );
}
