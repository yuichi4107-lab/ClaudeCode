'use client';

import dynamic from 'next/dynamic';
import type { RestaurantWithCounts } from '@/lib/supabase/types';

const MapInner = dynamic(() => import('./MapInner'), {
  ssr: false,
  loading: () => (
    <div className="flex h-full items-center justify-center bg-gray-100">
      <p className="text-gray-500">地図を読み込み中...</p>
    </div>
  ),
});

type Props = {
  restaurants: RestaurantWithCounts[];
  onBoundsChange?: (bounds: {
    north: number;
    south: number;
    east: number;
    west: number;
  }) => void;
};

export function MapContainer({ restaurants, onBoundsChange }: Props) {
  return <MapInner restaurants={restaurants} onBoundsChange={onBoundsChange} />;
}
