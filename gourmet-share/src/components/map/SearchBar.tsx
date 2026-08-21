'use client';

import { useState, useCallback } from 'react';

type Props = {
  onSearch: (lat: number, lng: number, name: string) => void;
  onFilterToggle: () => void;
};

export function SearchBar({ onSearch, onFilterToggle }: Props) {
  const [query, setQuery] = useState('');
  const [searching, setSearching] = useState(false);

  const handleSearch = useCallback(async () => {
    if (!query.trim()) return;
    setSearching(true);

    try {
      const res = await fetch(
        `/api/geocode?q=${encodeURIComponent(query.trim())}`
      );
      const data = await res.json();
      if (data.length > 0) {
        onSearch(parseFloat(data[0].lat), parseFloat(data[0].lon), data[0].display_name);
      }
    } catch {
      // 検索失敗は無視
    } finally {
      setSearching(false);
    }
  }, [query, onSearch]);

  return (
    <div className="absolute top-3 left-3 right-3 z-[1000] flex gap-2">
      <div className="relative flex-1">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
          placeholder="駅名・地名で検索..."
          className="w-full rounded-lg bg-white px-4 py-2.5 text-sm shadow-lg focus:outline-none focus:ring-2 focus:ring-green-500"
        />
        {searching && (
          <span className="absolute right-3 top-2.5 text-gray-400 text-sm">
            検索中...
          </span>
        )}
      </div>
      <button
        onClick={onFilterToggle}
        className="flex h-10 w-10 items-center justify-center rounded-lg bg-white shadow-lg"
        aria-label="フィルター"
      >
        🔍
      </button>
    </div>
  );
}
