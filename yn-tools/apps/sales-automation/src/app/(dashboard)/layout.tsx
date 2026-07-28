import { Nav } from "@/components/nav";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <Nav />
      <main style={{ padding: "1.5rem", maxWidth: 1200, margin: "0 auto" }}>
        {children}
      </main>
    </>
  );
}
