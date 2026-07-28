import { BottomNav } from '@/components/layout/BottomNav';

export default function MainLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex h-full flex-col">
      <main className="flex-1 overflow-auto pb-16">{children}</main>
      <BottomNav />
    </div>
  );
}
