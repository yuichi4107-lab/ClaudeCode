'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

const NAV_ITEMS = [
  { href: '/map', label: 'マップ', icon: '🗺️' },
  { href: '/list', label: 'リスト', icon: '📋' },
  { href: '/add', label: '登録', icon: '➕' },
  { href: '/profile', label: 'マイページ', icon: '👤' },
];

export function BottomNav() {
  const pathname = usePathname();

  return (
    <nav className="fixed bottom-0 left-0 right-0 z-50 border-t border-gray-200 bg-white pb-[env(safe-area-inset-bottom)]">
      <div className="mx-auto flex max-w-lg">
        {NAV_ITEMS.map((item) => {
          const isActive = pathname.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex flex-1 flex-col items-center py-2 text-xs ${
                isActive
                  ? 'text-green-600 font-medium'
                  : 'text-gray-500'
              }`}
            >
              <span className="text-xl">{item.icon}</span>
              <span className="mt-0.5">{item.label}</span>
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
