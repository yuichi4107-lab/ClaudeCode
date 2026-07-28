'use client';

import { useCallback, useState } from 'react';
import { MapContainer } from '@/components/map/MapContainer';
import { SearchBar } from '@/components/map/SearchBar';
import { FilterPanel } from '@/components/map/FilterPanel';
import { useRestaurants } from '@/hooks/useRestaurants';
import type { Genre, PriceRange } from '@/lib/constants';

export default function MapPage() {
  const { restaurants, filters, setFilters } = useRestaurants();
  const [filterOpen, setFilterOpen] = useState(false);

  // 地図を操作するためのref的なアプローチは不要
  // SearchBarからの検索結果はグローバルステートで管理せず、
  // MapInner内のuseMapで直接操作する必要がある
  // → ここではシンプルにフィルタと一覧表示を管理

  const handleSearch = useCallback((_lat: number, _lng: number, _name: string) => {
    // TODO: 地図の中心を移動する。MapInnerのrefを使うか、
    // stateで中心座標を管理して渡す
  }, []);

  const handleBoundsChange = useCallback(
    (bounds: { north: number; south: number; east: number; west: number }) => {
      setFilters((prev) => ({ ...prev, bounds }));
    },
    [setFilters]
  );

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

  const handleFilterReset = () => {
    setFilters((prev) => ({ ...prev, genres: [], priceRanges: [] }));
  };

  return (
    <div className="relative h-full">
      <SearchBar
        onSearch={handleSearch}
        onFilterToggle={() => setFilterOpen((v) => !v)}
      />
      <MapContainer
        restaurants={restaurants}
        onBoundsChange={handleBoundsChange}
      />
      <FilterPanel
        open={filterOpen}
        onClose={() => setFilterOpen(false)}
        selectedGenres={filters.genres}
        selectedPriceRanges={filters.priceRanges}
        onGenreToggle={handleGenreToggle}
        onPriceRangeToggle={handlePriceRangeToggle}
        onReset={handleFilterReset}
      />
    </div>
  );
}
