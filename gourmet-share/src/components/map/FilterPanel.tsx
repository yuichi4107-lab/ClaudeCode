'use client';

import { GENRES, PRICE_RANGES, type Genre, type PriceRange } from '@/lib/constants';

type Props = {
  open: boolean;
  onClose: () => void;
  selectedGenres: Genre[];
  selectedPriceRanges: PriceRange[];
  onGenreToggle: (genre: Genre) => void;
  onPriceRangeToggle: (range: PriceRange) => void;
  onReset: () => void;
};

export function FilterPanel({
  open,
  onClose,
  selectedGenres,
  selectedPriceRanges,
  onGenreToggle,
  onPriceRangeToggle,
  onReset,
}: Props) {
  if (!open) return null;

  return (
    <>
      <div
        className="fixed inset-0 z-40 bg-black/30"
        onClick={onClose}
      />
      <div className="fixed bottom-0 left-0 right-0 z-50 rounded-t-2xl bg-white p-5 pb-24 shadow-xl">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-lg font-bold">絞り込み</h3>
          <button
            onClick={onReset}
            className="text-sm text-green-600"
          >
            リセット
          </button>
        </div>

        <div className="mb-4">
          <p className="mb-2 text-sm font-medium text-gray-700">ジャンル</p>
          <div className="flex flex-wrap gap-2">
            {GENRES.map((genre) => (
              <button
                key={genre}
                onClick={() => onGenreToggle(genre)}
                className={`rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${
                  selectedGenres.includes(genre)
                    ? 'bg-green-600 text-white'
                    : 'bg-gray-100 text-gray-700'
                }`}
              >
                {genre}
              </button>
            ))}
          </div>
        </div>

        <div className="mb-4">
          <p className="mb-2 text-sm font-medium text-gray-700">価格帯</p>
          <div className="flex flex-wrap gap-2">
            {PRICE_RANGES.map((range) => (
              <button
                key={range}
                onClick={() => onPriceRangeToggle(range)}
                className={`rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${
                  selectedPriceRanges.includes(range)
                    ? 'bg-green-600 text-white'
                    : 'bg-gray-100 text-gray-700'
                }`}
              >
                ¥{range}
              </button>
            ))}
          </div>
        </div>

        <button
          onClick={onClose}
          className="w-full rounded-lg bg-green-600 py-3 text-base font-medium text-white"
        >
          適用する
        </button>
      </div>
    </>
  );
}
