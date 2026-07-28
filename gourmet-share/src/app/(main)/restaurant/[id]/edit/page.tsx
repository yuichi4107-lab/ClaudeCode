'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { createClient } from '@/lib/supabase/client';
import { GENRES, PRICE_RANGES, type Genre, type PriceRange } from '@/lib/constants';
import type { RestaurantWithCounts } from '@/lib/supabase/types';

export default function EditRestaurantPage() {
  const params = useParams();
  const router = useRouter();
  const id = params.id as string;

  const [loading, setLoading] = useState(true);
  const [name, setName] = useState('');
  const [address, setAddress] = useState('');
  const [genre, setGenre] = useState<Genre | ''>('');
  const [lunchPrice, setLunchPrice] = useState<PriceRange | ''>('');
  const [dinnerPrice, setDinnerPrice] = useState<PriceRange | ''>('');
  const [url, setUrl] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    async function load() {
      const supabase = createClient();

      const { data: { user } } = await supabase.auth.getUser();
      if (!user) {
        router.push('/login');
        return;
      }

      const { data } = await supabase
        .from('restaurants_with_counts')
        .select('*')
        .eq('id', id)
        .single();

      const r = data as unknown as RestaurantWithCounts;
      if (!r || r.registered_by !== user.id) {
        router.push(`/restaurant/${id}`);
        return;
      }

      setName(r.name);
      setAddress(r.address || '');
      setGenre((r.genre as Genre) || '');
      setLunchPrice((r.lunch_price_range as PriceRange) || '');
      setDinnerPrice((r.dinner_price_range as PriceRange) || '');
      setUrl(r.url || '');
      setLoading(false);
    }
    load();
  }, [id, router]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!genre) {
      setError('ジャンルを選択してください');
      return;
    }
    if (!lunchPrice && !dinnerPrice) {
      setError('昼または夜の価格帯を少なくとも1つ選択してください');
      return;
    }
    if (!address.trim()) {
      setError('住所を入力してください');
      return;
    }

    setSaving(true);
    setError('');

    try {
      // 住所からジオコーディング
      const geoRes = await fetch(
        `/api/geocode?q=${encodeURIComponent(address.trim())}`
      );
      const geoData = await geoRes.json();

      if (!geoData.length) {
        setError('住所から位置を特定できませんでした。');
        setSaving(false);
        return;
      }

      const lat = parseFloat(geoData[0].lat);
      const lng = parseFloat(geoData[0].lon);
      const priceRange = lunchPrice || dinnerPrice;

      const res = await fetch(`/api/restaurants/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: name.trim(),
          address: address.trim(),
          genre,
          price_range: priceRange,
          lunch_price_range: lunchPrice || null,
          dinner_price_range: dinnerPrice || null,
          url: url.trim() || null,
          latitude: lat,
          longitude: lng,
        }),
      });

      const result = await res.json();
      if (!res.ok) {
        setError(result.error || '更新に失敗しました');
        setSaving(false);
        return;
      }

      router.push(`/restaurant/${id}`);
      router.refresh();
    } catch {
      setError('エラーが発生しました');
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-gray-500">読み込み中...</p>
      </div>
    );
  }

  return (
    <div className="px-4 pt-4 pb-4">
      <Link href={`/restaurant/${id}`} className="mb-3 inline-block text-sm text-green-600">
        ← 戻る
      </Link>
      <h1 className="mb-4 text-xl font-bold">お店を編集</h1>

      <form onSubmit={handleSubmit} className="space-y-5">
        <div>
          <label className="block text-sm font-medium text-gray-700">
            店名 <span className="text-red-500">*</span>
          </label>
          <input
            type="text"
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="mt-1 block w-full rounded-lg border border-gray-300 px-4 py-3 text-base focus:border-green-500 focus:outline-none focus:ring-1 focus:ring-green-500"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700">
            住所 <span className="text-red-500">*</span>
          </label>
          <input
            type="text"
            required
            value={address}
            onChange={(e) => setAddress(e.target.value)}
            className="mt-1 block w-full rounded-lg border border-gray-300 px-4 py-3 text-base focus:border-green-500 focus:outline-none focus:ring-1 focus:ring-green-500"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700">
            ジャンル <span className="text-red-500">*</span>
          </label>
          <div className="mt-2 flex flex-wrap gap-2">
            {GENRES.map((g) => (
              <button
                key={g}
                type="button"
                onClick={() => setGenre(g)}
                className={`rounded-full px-3 py-1.5 text-sm font-medium transition-colors ${
                  genre === g ? 'bg-green-600 text-white' : 'bg-gray-100 text-gray-700'
                }`}
              >
                {g}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700">昼の価格帯</label>
          <div className="mt-2 flex flex-wrap gap-2">
            {PRICE_RANGES.map((p) => (
              <button
                key={`lunch-${p}`}
                type="button"
                onClick={() => setLunchPrice(lunchPrice === p ? '' : p)}
                className={`rounded-full px-3 py-1.5 text-sm font-medium transition-colors ${
                  lunchPrice === p ? 'bg-orange-500 text-white' : 'bg-gray-100 text-gray-700'
                }`}
              >
                ¥{p}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700">夜の価格帯</label>
          <div className="mt-2 flex flex-wrap gap-2">
            {PRICE_RANGES.map((p) => (
              <button
                key={`dinner-${p}`}
                type="button"
                onClick={() => setDinnerPrice(dinnerPrice === p ? '' : p)}
                className={`rounded-full px-3 py-1.5 text-sm font-medium transition-colors ${
                  dinnerPrice === p ? 'bg-indigo-600 text-white' : 'bg-gray-100 text-gray-700'
                }`}
              >
                ¥{p}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700">URL</label>
          <input
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://..."
            className="mt-1 block w-full rounded-lg border border-gray-300 px-4 py-3 text-base focus:border-green-500 focus:outline-none focus:ring-1 focus:ring-green-500"
          />
        </div>

        {error && <p className="text-sm text-red-600">{error}</p>}

        <button
          type="submit"
          disabled={saving}
          className="w-full rounded-lg bg-green-600 px-4 py-3 text-base font-medium text-white hover:bg-green-700 disabled:opacity-50"
        >
          {saving ? '更新中...' : '更新する'}
        </button>
      </form>
    </div>
  );
}
