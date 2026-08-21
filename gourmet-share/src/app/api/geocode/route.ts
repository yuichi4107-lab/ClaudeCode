import { NextRequest, NextResponse } from 'next/server';

const NOMINATIM_URL = 'https://nominatim.openstreetmap.org';

// シンプルなレート制限（最後のリクエスト時刻を保持）
let lastRequestTime = 0;

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const q = searchParams.get('q');
  const lat = searchParams.get('lat');
  const lng = searchParams.get('lng');

  // Nominatimの利用規約: 1秒に1リクエストまで
  const now = Date.now();
  const wait = 1000 - (now - lastRequestTime);
  if (wait > 0) {
    await new Promise((resolve) => setTimeout(resolve, wait));
  }
  lastRequestTime = Date.now();

  try {
    let url: string;
    if (q) {
      // 順方向ジオコーディング（住所/地名 → 座標）
      url = `${NOMINATIM_URL}/search?format=json&q=${encodeURIComponent(q)}&limit=5&countrycodes=jp`;
    } else if (lat && lng) {
      // 逆方向ジオコーディング（座標 → 住所）
      url = `${NOMINATIM_URL}/reverse?format=json&lat=${lat}&lon=${lng}`;
    } else {
      return NextResponse.json(
        { error: 'q または lat,lng パラメータが必要です' },
        { status: 400 }
      );
    }

    const res = await fetch(url, {
      headers: {
        'User-Agent': 'GourmetShare/1.0',
      },
    });

    const data = await res.json();

    // 逆ジオコーディングの場合は配列に包む
    if (lat && lng) {
      return NextResponse.json(data ? [data] : []);
    }

    return NextResponse.json(data);
  } catch {
    return NextResponse.json(
      { error: 'ジオコーディングに失敗しました' },
      { status: 500 }
    );
  }
}
