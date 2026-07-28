import { NextRequest, NextResponse } from 'next/server';
import { createServerClient } from '@supabase/ssr';
import { createClient } from '@supabase/supabase-js';
import { cookies } from 'next/headers';

export async function DELETE(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;

  // ログインユーザーを取得
  const cookieStore = await cookies();
  const supabaseAuth = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        setAll() {},
      },
    }
  );

  const { data: { user } } = await supabaseAuth.auth.getUser();
  if (!user) {
    return NextResponse.json({ error: 'ログインが必要です' }, { status: 401 });
  }

  // service_role keyでDB操作（RLSバイパス）
  const supabaseAdmin = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.SUPABASE_SERVICE_ROLE_KEY!
  );

  // まず店舗の登録者を確認
  const { data: restaurant } = await supabaseAdmin
    .from('restaurants')
    .select('registered_by')
    .eq('id', id)
    .single();

  if (!restaurant) {
    return NextResponse.json({ error: 'お店が見つかりません' }, { status: 404 });
  }

  if (restaurant.registered_by !== user.id) {
    return NextResponse.json({ error: '自分が登録したお店のみ削除できます' }, { status: 403 });
  }

  // 削除実行
  const { error } = await supabaseAdmin
    .from('restaurants')
    .delete()
    .eq('id', id);

  if (error) {
    return NextResponse.json({ error: '削除に失敗しました' }, { status: 500 });
  }

  return NextResponse.json({ success: true });
}

export async function PATCH(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const body = await request.json();

  const cookieStore = await cookies();
  const supabaseAuth = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        setAll() {},
      },
    }
  );

  const { data: { user } } = await supabaseAuth.auth.getUser();
  if (!user) {
    return NextResponse.json({ error: 'ログインが必要です' }, { status: 401 });
  }

  const supabaseAdmin = createClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.SUPABASE_SERVICE_ROLE_KEY!
  );

  const { data: restaurant } = await supabaseAdmin
    .from('restaurants')
    .select('registered_by')
    .eq('id', id)
    .single();

  if (!restaurant) {
    return NextResponse.json({ error: 'お店が見つかりません' }, { status: 404 });
  }

  if (restaurant.registered_by !== user.id) {
    return NextResponse.json({ error: '自分が登録したお店のみ編集できます' }, { status: 403 });
  }

  // undefinedのフィールドを除外して、送られたフィールドのみ更新
  const updateData: Record<string, unknown> = { updated_at: new Date().toISOString() };
  const fields = ['name', 'address', 'genre', 'price_range', 'lunch_price_range', 'dinner_price_range', 'owner_comment', 'url', 'latitude', 'longitude'];
  for (const key of fields) {
    if (key in body) updateData[key] = body[key];
  }

  const { error } = await supabaseAdmin
    .from('restaurants')
    .update(updateData)
    .eq('id', id);

  if (error) {
    return NextResponse.json({ error: '更新に失敗しました' }, { status: 500 });
  }

  return NextResponse.json({ success: true });
}
