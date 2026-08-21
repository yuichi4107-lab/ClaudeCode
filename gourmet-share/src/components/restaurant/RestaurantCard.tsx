import Link from 'next/link';
import { GENRE_COLORS, type Genre } from '@/lib/constants';
import type { RestaurantWithCounts } from '@/lib/supabase/types';

type Props = {
  restaurant: RestaurantWithCounts;
};

export function RestaurantCard({ restaurant: r }: Props) {
  const color = GENRE_COLORS[r.genre as Genre] || '#546E7A';

  return (
    <Link
      href={`/restaurant/${r.id}`}
      className="block rounded-lg border border-gray-200 bg-white p-4 shadow-sm transition-shadow hover:shadow-md"
    >
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <h3 className="font-bold text-base">{r.name}</h3>
          <div className="mt-1 flex items-center gap-2">
            <span
              className="inline-block rounded-full px-2 py-0.5 text-xs font-medium text-white"
              style={{ backgroundColor: color }}
            >
              {r.genre}
            </span>
            <span className="text-xs text-gray-500">¥{r.price_range}</span>
          </div>
          {r.address && (
            <p className="mt-1 text-xs text-gray-400 truncate">{r.address}</p>
          )}
        </div>
        <div className="ml-3 text-right">
          <p className="text-sm font-bold text-green-600">
            🙋 {r.total_reactions}
          </p>
          <p className="text-xs text-gray-400">{r.registered_by_name}</p>
        </div>
      </div>
    </Link>
  );
}
