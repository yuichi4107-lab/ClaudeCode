'use client';

import { useEffect, useState } from 'react';
import {
  MapContainer,
  TileLayer,
  Marker,
  Popup,
  useMapEvents,
  useMap,
} from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { GENRE_COLORS, type Genre } from '@/lib/constants';
import { DEFAULT_CENTER, DEFAULT_ZOOM } from '@/lib/map-utils';
import type { RestaurantWithCounts } from '@/lib/supabase/types';
import Link from 'next/link';

// Leaflet デフォルトアイコン修正
// eslint-disable-next-line @typescript-eslint/no-explicit-any
delete (L.Icon.Default.prototype as any)._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
  iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
  shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
});

function createColoredIcon(genre: string) {
  const color = GENRE_COLORS[genre as Genre] || '#546E7A';
  return L.divIcon({
    html: `
      <svg xmlns="http://www.w3.org/2000/svg" width="28" height="40" viewBox="0 0 28 40">
        <path d="M14 0C6.27 0 0 6.27 0 14c0 10.5 14 26 14 26s14-15.5 14-26C28 6.27 21.73 0 14 0z"
              fill="${color}" stroke="#fff" stroke-width="1.5"/>
        <circle cx="14" cy="14" r="6" fill="#fff"/>
      </svg>
    `,
    className: '',
    iconSize: [28, 40],
    iconAnchor: [14, 40],
    popupAnchor: [0, -40],
  });
}

type Props = {
  restaurants: RestaurantWithCounts[];
  onBoundsChange?: (bounds: {
    north: number;
    south: number;
    east: number;
    west: number;
  }) => void;
};

function BoundsWatcher({
  onBoundsChange,
}: {
  onBoundsChange?: Props['onBoundsChange'];
}) {
  useMapEvents({
    moveend(e) {
      if (!onBoundsChange) return;
      const bounds = e.target.getBounds();
      onBoundsChange({
        north: bounds.getNorth(),
        south: bounds.getSouth(),
        east: bounds.getEast(),
        west: bounds.getWest(),
      });
    },
  });
  return null;
}

function LocationButton() {
  const map = useMap();
  const [locating, setLocating] = useState(false);

  const handleClick = () => {
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        map.setView([pos.coords.latitude, pos.coords.longitude], 15);
        setLocating(false);
      },
      () => {
        setLocating(false);
      }
    );
  };

  return (
    <button
      onClick={handleClick}
      disabled={locating}
      className="absolute bottom-20 right-3 z-[1000] flex h-10 w-10 items-center justify-center rounded-full bg-white shadow-lg"
      aria-label="現在地"
    >
      {locating ? '...' : '📍'}
    </button>
  );
}

export default function MapInner({ restaurants, onBoundsChange }: Props) {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) return null;

  return (
    <MapContainer
      center={DEFAULT_CENTER}
      zoom={DEFAULT_ZOOM}
      className="h-full w-full"
      zoomControl={false}
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      <BoundsWatcher onBoundsChange={onBoundsChange} />
      <LocationButton />

      {restaurants.map((r) => (
        <Marker
          key={r.id}
          position={[r.latitude, r.longitude]}
          icon={createColoredIcon(r.genre)}
        >
          <Popup>
            <div className="min-w-[160px]">
              <p className="font-bold text-sm">{r.name}</p>
              <p className="text-xs text-gray-500">
                {r.genre} / {r.price_range}
              </p>
              <p className="text-xs text-gray-400 mt-1">
                🙋 {r.total_reactions}件のリアクション
              </p>
              <Link
                href={`/restaurant/${r.id}`}
                className="mt-2 inline-block text-xs text-green-600 font-medium"
              >
                詳細を見る →
              </Link>
            </div>
          </Popup>
        </Marker>
      ))}
    </MapContainer>
  );
}
