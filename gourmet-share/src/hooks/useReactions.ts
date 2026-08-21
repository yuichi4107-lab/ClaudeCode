'use client';

import { useCallback, useEffect, useState } from 'react';
import { createClient } from '@/lib/supabase/client';

type ReactionCounts = Record<string, number>;

export function useReactions(restaurantId: string) {
  const [counts, setCounts] = useState<ReactionCounts>({});
  const [myReactions, setMyReactions] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);

  const fetchReactions = useCallback(async () => {
    const supabase = createClient();
    const {
      data: { user },
    } = await supabase.auth.getUser();

    // 全リアクション取得
    const { data: allReactions } = await supabase
      .from('reactions')
      .select('reaction_type, user_id')
      .eq('restaurant_id', restaurantId);

    if (allReactions) {
      const newCounts: ReactionCounts = {};
      const userReactions = new Set<string>();

      allReactions.forEach((r) => {
        newCounts[r.reaction_type] = (newCounts[r.reaction_type] || 0) + 1;
        if (user && r.user_id === user.id) {
          userReactions.add(r.reaction_type);
        }
      });

      setCounts(newCounts);
      setMyReactions(userReactions);
    }
    setLoading(false);
  }, [restaurantId]);

  useEffect(() => {
    fetchReactions();
  }, [fetchReactions]);

  const toggleReaction = useCallback(
    async (reactionType: string) => {
      const supabase = createClient();
      const {
        data: { user },
      } = await supabase.auth.getUser();
      if (!user) return;

      const has = myReactions.has(reactionType);

      if (has) {
        // 楽観的更新: 削除
        setMyReactions((prev) => {
          const next = new Set(prev);
          next.delete(reactionType);
          return next;
        });
        setCounts((prev) => ({
          ...prev,
          [reactionType]: Math.max(0, (prev[reactionType] || 0) - 1),
        }));

        await supabase
          .from('reactions')
          .delete()
          .eq('restaurant_id', restaurantId)
          .eq('user_id', user.id)
          .eq('reaction_type', reactionType);
      } else {
        // 楽観的更新: 追加
        setMyReactions((prev) => new Set(prev).add(reactionType));
        setCounts((prev) => ({
          ...prev,
          [reactionType]: (prev[reactionType] || 0) + 1,
        }));

        await supabase.from('reactions').insert({
          restaurant_id: restaurantId,
          user_id: user.id,
          reaction_type: reactionType,
        });
      }
    },
    [restaurantId, myReactions]
  );

  return { counts, myReactions, loading, toggleReaction };
}
