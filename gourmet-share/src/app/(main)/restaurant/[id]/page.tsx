'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { createClient } from '@/lib/supabase/client';
import { ReactionPicker } from '@/components/reaction/ReactionPicker';
import { useReactions } from '@/hooks/useReactions';
import { GENRE_COLORS, type Genre } from '@/lib/constants';
import type { RestaurantWithCounts } from '@/lib/supabase/types';

export default function RestaurantDetailPage() {
  const params = useParams();
  const id = params.id as string;
  const [restaurant, setRestaurant] = useState<RestaurantWithCounts | null>(null);
  const [loading, setLoading] = useState(true);
  const { counts, myReactions, toggleReaction } = useReactions(id);

  useEffect(() => {
    async function load() {
      const supabase = createClient();
      const { data } = await supabase
        .from('restaurants_with_counts')
        .select('*')
        .eq('id', id)
        .single();

      setRestaurant(data as unknown as RestaurantWithCounts | null);
      setLoading(false);
    }
    load();
  }, [id]);

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-gray-500">読み込み中...</p>
      </div>
    );
  }

  if (!restaurant) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4">
        <p className="text-gray-500">お店が見つかりません</p>
        <Link href="/map" className="text-green-600">
          マップに戻る
        </Link>
      </div>
    );
  }

  const color = GENRE_COLORS[restaurant.genre as Genre] || '#546E7A';

  return (
    <div className="px-4 pt-4 pb-4">
      <Link
        href="/map"
        className="mb-3 inline-block text-sm text-green-600"
      >
        ← マップに戻る
      </Link>

      <h1 className="text-2xl font-bold">{restaurant.name}</h1>

      <div className="mt-2 flex items-center gap-2">
        <span
          className="inline-block rounded-full px-2.5 py-0.5 text-xs font-medium text-white"
          style={{ backgroundColor: color }}
        >
          {restaurant.genre}
        </span>
        <span className="text-sm text-gray-500">
          ¥{restaurant.price_range}
        </span>
      </div>

      {restaurant.address && (
        <p className="mt-2 text-sm text-gray-600">
          📍 {restaurant.address}
        </p>
      )}

      {restaurant.url && (
        <a
          href={restaurant.url}
          target="_blank"
          rel="noopener noreferrer"
          className="mt-1 inline-block text-sm text-blue-600 underline"
        >
          🔗 お店のページを見る
        </a>
      )}

      <p className="mt-2 text-xs text-gray-400">
        {restaurant.registered_by_name} さんが登録
      </p>

      <hr className="my-5" />

      <h2 className="mb-3 text-lg font-bold">リアクション</h2>
      <ReactionPicker
        counts={counts}
        myReactions={myReactions}
        onToggle={toggleReaction}
      />
    </div>
  );
}
