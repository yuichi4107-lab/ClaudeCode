'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { createClient } from '@/lib/supabase/client';
import { GENRES, PRICE_RANGES, type Genre, type PriceRange } from '@/lib/constants';

export function RestaurantForm() {
  const router = useRouter();
  const [name, setName] = useState('');
  const [address, setAddress] = useState('');
  const [genre, setGenre] = useState<Genre | ''>('');
  const [priceRange, setPriceRange] = useState<PriceRange | ''>('');
  const [url, setUrl] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!genre || !priceRange) {
      setError('ジャンルと価格帯を選択してください');
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
        setError('住所から位置を特定できませんでした。より詳しい住所を入力してください。');
        setSaving(false);
        return;
      }

      const lat = parseFloat(geoData[0].lat);
      const lng = parseFloat(geoData[0].lon);

      const supabase = createClient();
      const {
        data: { user },
      } = await supabase.auth.getUser();

      if (!user) {
        setError('ログインが必要です');
        setSaving(false);
        return;
      }

      const { error: insertError } = await supabase
        .from('restaurants')
        .insert({
          name: name.trim(),
          address: address.trim(),
          genre: genre as string,
          price_range: priceRange as string,
          url: url.trim() || null,
          latitude: lat,
          longitude: lng,
          registered_by: user.id,
        });

      if (insertError) {
        setError('登録に失敗しました');
        setSaving(false);
        return;
      }

      router.push('/map');
      router.refresh();
    } catch {
      setError('エラーが発生しました');
      setSaving(false);
    }
  };

  return (
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
          placeholder="例: 焼肉太郎"
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
          placeholder="例: 東京都新宿区西新宿1-1-1"
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
                genre === g
                  ? 'bg-green-600 text-white'
                  : 'bg-gray-100 text-gray-700'
              }`}
            >
              {g}
            </button>
          ))}
        </div>
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700">
          価格帯 <span className="text-red-500">*</span>
        </label>
        <div className="mt-2 flex flex-wrap gap-2">
          {PRICE_RANGES.map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => setPriceRange(p)}
              className={`rounded-full px-3 py-1.5 text-sm font-medium transition-colors ${
                priceRange === p
                  ? 'bg-green-600 text-white'
                  : 'bg-gray-100 text-gray-700'
              }`}
            >
              ¥{p}
            </button>
          ))}
        </div>
      </div>

      <div>
        <label className="block text-sm font-medium text-gray-700">
          URL（食べログ、Googleマップなど）
        </label>
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
        {saving ? '登録中...' : '登録する'}
      </button>
    </form>
  );
}
