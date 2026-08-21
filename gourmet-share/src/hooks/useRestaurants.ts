'use client';

import { useCallback, useEffect, useState } from 'react';
import { createClient } from '@/lib/supabase/client';
import type { RestaurantWithCounts } from '@/lib/supabase/types';
import type { Genre, PriceRange } from '@/lib/constants';

type Bounds = {
  north: number;
  south: number;
  east: number;
  west: number;
};

type Filters = {
  genres: Genre[];
  priceRanges: PriceRange[];
  bounds?: Bounds;
};

export function useRestaurants() {
  const [restaurants, setRestaurants] = useState<RestaurantWithCounts[]>([]);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState<Filters>({
    genres: [],
    priceRanges: [],
  });

  const fetchRestaurants = useCallback(async () => {
    setLoading(true);
    const supabase = createClient();

    let query = supabase
      .from('restaurants_with_counts')
      .select('*')
      .order('total_reactions', { ascending: false });

    if (filters.genres.length > 0) {
      query = query.in('genre', filters.genres);
    }
    if (filters.priceRanges.length > 0) {
      query = query.in('price_range', filters.priceRanges);
    }
    if (filters.bounds) {
      const { north, south, east, west } = filters.bounds;
      query = query
        .gte('latitude', south)
        .lte('latitude', north)
        .gte('longitude', west)
        .lte('longitude', east);
    }

    const { data } = await query;
    setRestaurants((data as RestaurantWithCounts[]) || []);
    setLoading(false);
  }, [filters]);

  useEffect(() => {
    fetchRestaurants();
  }, [fetchRestaurants]);

  return {
    restaurants,
    loading,
    filters,
    setFilters,
    refetch: fetchRestaurants,
  };
}
