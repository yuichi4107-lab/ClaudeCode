'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { createClient } from '@/lib/supabase/client';
import type { Profile } from '@/lib/supabase/types';

export default function ProfilePage() {
  const router = useRouter();
  const [profile, setProfile] = useState<Profile | null>(null);
  const [stats, setStats] = useState({ restaurants: 0, reactions: 0 });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      const supabase = createClient();
      const {
        data: { user },
      } = await supabase.auth.getUser();

      if (!user) return;

      const { data: profileData } = await supabase
        .from('profiles')
        .select('*')
        .eq('id', user.id)
        .single();

      setProfile(profileData);

      const { count: restaurantCount } = await supabase
        .from('restaurants')
        .select('*', { count: 'exact', head: true })
        .eq('registered_by', user.id);

      const { count: reactionCount } = await supabase
        .from('reactions')
        .select('*', { count: 'exact', head: true })
        .eq('user_id', user.id);

      setStats({
        restaurants: restaurantCount || 0,
        reactions: reactionCount || 0,
      });
      setLoading(false);
    }
    load();
  }, []);

  const handleLogout = async () => {
    const supabase = createClient();
    await supabase.auth.signOut();
    router.push('/login');
  };

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-gray-500">読み込み中...</p>
      </div>
    );
  }

  return (
    <div className="px-4 pt-4">
      <h1 className="mb-6 text-xl font-bold">マイページ</h1>

      {profile && (
        <div className="rounded-lg border border-gray-200 bg-white p-5">
          <p className="text-lg font-bold">{profile.display_name}</p>
          <p className="mt-1 text-xs text-gray-400">
            {new Date(profile.created_at).toLocaleDateString('ja-JP')} 登録
          </p>

          <div className="mt-4 flex gap-6">
            <div className="text-center">
              <p className="text-2xl font-bold text-green-600">
                {stats.restaurants}
              </p>
              <p className="text-xs text-gray-500">登録したお店</p>
            </div>
            <div className="text-center">
              <p className="text-2xl font-bold text-green-600">
                {stats.reactions}
              </p>
              <p className="text-xs text-gray-500">リアクション</p>
            </div>
          </div>
        </div>
      )}

      <button
        onClick={handleLogout}
        className="mt-6 w-full rounded-lg border border-gray-300 py-3 text-base font-medium text-gray-700"
      >
        ログアウト
      </button>
    </div>
  );
}
