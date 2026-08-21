'use client';

import { useState, useEffect, useCallback } from 'react';

export type MyTown = {
  name: string;
  lat: number;
  lng: number;
};

const STORAGE_KEY = 'gourmet-share-my-town';

export function useMyTown() {
  const [myTown, setMyTownState] = useState<MyTown | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      try {
        setMyTownState(JSON.parse(stored));
      } catch {
        // ignore
      }
    }
    setLoaded(true);
  }, []);

  const setMyTown = useCallback((town: MyTown | null) => {
    setMyTownState(town);
    if (town) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(town));
    } else {
      localStorage.removeItem(STORAGE_KEY);
    }
  }, []);

  return { myTown, setMyTown, loaded };
}
