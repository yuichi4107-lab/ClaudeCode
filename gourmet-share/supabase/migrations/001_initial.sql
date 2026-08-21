-- PostGIS拡張を有効化
CREATE EXTENSION IF NOT EXISTS postgis;

-- ============================================
-- profiles テーブル
-- ============================================
CREATE TABLE public.profiles (
  id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  display_name TEXT NOT NULL,
  avatar_url TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;

CREATE POLICY "profiles_select_authenticated"
  ON public.profiles FOR SELECT
  USING (auth.role() = 'authenticated');

CREATE POLICY "profiles_insert_own"
  ON public.profiles FOR INSERT
  WITH CHECK (auth.uid() = id);

CREATE POLICY "profiles_update_own"
  ON public.profiles FOR UPDATE
  USING (auth.uid() = id);

-- 新規ユーザー登録時にプロフィールを自動作成するトリガー
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
  INSERT INTO public.profiles (id, display_name)
  VALUES (
    NEW.id,
    COALESCE(NEW.raw_user_meta_data ->> 'display_name', split_part(NEW.email, '@', 1))
  );
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- ============================================
-- restaurants テーブル
-- ============================================
CREATE TABLE public.restaurants (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  address TEXT,
  genre TEXT NOT NULL,
  price_range TEXT NOT NULL,
  url TEXT,
  latitude DOUBLE PRECISION NOT NULL,
  longitude DOUBLE PRECISION NOT NULL,
  location GEOGRAPHY(POINT, 4326) GENERATED ALWAYS AS (
    ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography
  ) STORED,
  registered_by UUID NOT NULL REFERENCES public.profiles(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_restaurants_location ON public.restaurants USING GIST (location);
CREATE INDEX idx_restaurants_genre ON public.restaurants (genre);
CREATE INDEX idx_restaurants_price_range ON public.restaurants (price_range);

ALTER TABLE public.restaurants ENABLE ROW LEVEL SECURITY;

CREATE POLICY "restaurants_select_authenticated"
  ON public.restaurants FOR SELECT
  USING (auth.role() = 'authenticated');

CREATE POLICY "restaurants_insert_authenticated"
  ON public.restaurants FOR INSERT
  WITH CHECK (auth.role() = 'authenticated');

CREATE POLICY "restaurants_update_creator"
  ON public.restaurants FOR UPDATE
  USING (auth.uid() = registered_by);

-- ============================================
-- reactions テーブル
-- ============================================
CREATE TABLE public.reactions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  restaurant_id UUID NOT NULL REFERENCES public.restaurants(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  reaction_type TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (restaurant_id, user_id, reaction_type)
);

CREATE INDEX idx_reactions_restaurant ON public.reactions (restaurant_id);
CREATE INDEX idx_reactions_user ON public.reactions (user_id);

ALTER TABLE public.reactions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "reactions_select_authenticated"
  ON public.reactions FOR SELECT
  USING (auth.role() = 'authenticated');

CREATE POLICY "reactions_insert_own"
  ON public.reactions FOR INSERT
  WITH CHECK (auth.uid() = user_id);

CREATE POLICY "reactions_delete_own"
  ON public.reactions FOR DELETE
  USING (auth.uid() = user_id);

-- ============================================
-- レストラン+リアクション集計ビュー
-- ============================================
CREATE VIEW public.restaurants_with_counts AS
SELECT
  r.*,
  p.display_name AS registered_by_name,
  COALESCE(rc.total_reactions, 0)::int AS total_reactions,
  COALESCE(rc.unique_reactors, 0)::int AS unique_reactors
FROM public.restaurants r
LEFT JOIN public.profiles p ON r.registered_by = p.id
LEFT JOIN (
  SELECT
    restaurant_id,
    COUNT(*) AS total_reactions,
    COUNT(DISTINCT user_id) AS unique_reactors
  FROM public.reactions
  GROUP BY restaurant_id
) rc ON r.id = rc.restaurant_id;

-- ============================================
-- リアクション種別別カウント取得関数
-- ============================================
CREATE OR REPLACE FUNCTION public.get_reaction_counts(p_restaurant_id UUID)
RETURNS TABLE (reaction_type TEXT, count BIGINT) AS $$
  SELECT reaction_type, COUNT(*) as count
  FROM public.reactions
  WHERE restaurant_id = p_restaurant_id
  GROUP BY reaction_type
  ORDER BY count DESC;
$$ LANGUAGE sql STABLE;
