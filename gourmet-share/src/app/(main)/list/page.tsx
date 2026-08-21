'use client';

import { useState } from 'react';
import { RestaurantCard } from '@/components/restaurant/RestaurantCard';
import { FilterPanel } from '@/components/map/FilterPanel';
import { useRestaurants } from '@/hooks/useRestaurants';
import type { Genre, PriceRange } from '@/lib/constants';

export default function ListPage() {
  const { restaurants, loading, filters, setFilters } = useRestaurants();
  const [filterOpen, setFilterOpen] = useState(false);
  const [sortBy, setSortBy] = useState<'reactions' | 'newest'>('reactions');

  const sorted = [...restaurants].sort((a, b) => {
    if (sortBy === 'newest') {
      return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
    }
    return b.total_reactions - a.total_reactions;
  });

  const handleGenreToggle = (genre: Genre) => {
    setFilters((prev) => ({
      ...prev,
      genres: prev.genres.includes(genre)
        ? prev.genres.filter((g) => g !== genre)
        : [...prev.genres, genre],
    }));
  };

  const handlePriceRangeToggle = (range: PriceRange) => {
    setFilters((prev) => ({
      ...prev,
      priceRanges: prev.priceRanges.includes(range)
        ? prev.priceRanges.filter((p) => p !== range)
        : [...prev.priceRanges, range],
    }));
  };

  return (
    <div className="px-4 pt-4">
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-xl font-bold">お店一覧</h1>
        <div className="flex gap-2">
          <button
            onClick={() => setFilterOpen(true)}
            className="rounded-lg bg-gray-100 px-3 py-1.5 text-xs font-medium"
          >
            🔍 絞り込み
          </button>
        </div>
      </div>

      <div className="mb-3 flex gap-2">
        <button
          onClick={() => setSortBy('reactions')}
          className={`rounded-full px-3 py-1 text-xs font-medium ${
            sortBy === 'reactions'
              ? 'bg-green-600 text-white'
              : 'bg-gray-100 text-gray-700'
          }`}
        >
          リアクション順
        </button>
        <button
          onClick={() => setSortBy('newest')}
          className={`rounded-full px-3 py-1 text-xs font-medium ${
            sortBy === 'newest'
              ? 'bg-green-600 text-white'
              : 'bg-gray-100 text-gray-700'
          }`}
        >
          新着順
        </button>
      </div>

      {loading ? (
        <p className="text-center text-gray-500 py-8">読み込み中...</p>
      ) : sorted.length === 0 ? (
        <p className="text-center text-gray-500 py-8">
          お店がまだ登録されていません
        </p>
      ) : (
        <div className="space-y-3 pb-4">
          {sorted.map((r) => (
            <RestaurantCard key={r.id} restaurant={r} />
          ))}
        </div>
      )}

      <FilterPanel
        open={filterOpen}
        onClose={() => setFilterOpen(false)}
        selectedGenres={filters.genres}
        selectedPriceRanges={filters.priceRanges}
        onGenreToggle={handleGenreToggle}
        onPriceRangeToggle={handlePriceRangeToggle}
        onReset={() =>
          setFilters((prev) => ({ ...prev, genres: [], priceRanges: [] }))
        }
      />
    </div>
  );
}
