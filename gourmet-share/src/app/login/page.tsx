'use client';

import { useState } from 'react';
import { createClient } from '@/lib/supabase/client';

export default function LoginPage() {
  const [email, setEmail] = useState('');
  const [sent, setSent] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError('');

    const supabase = createClient();
    const { error } = await supabase.auth.signInWithOtp({
      email,
      options: {
        emailRedirectTo: `${window.location.origin}/auth/callback`,
      },
    });

    if (error) {
      setError('送信に失敗しました。メールアドレスを確認してください。');
    } else {
      setSent(true);
    }
    setLoading(false);
  };

  return (
    <div className="flex min-h-full items-center justify-center px-4">
      <div className="w-full max-w-sm space-y-8">
        <div className="text-center">
          <h1 className="text-3xl font-bold text-green-700">
            グルメシェア
          </h1>
          <p className="mt-2 text-sm text-gray-500">
            仲間とレストランをシェアしよう
          </p>
        </div>

        {sent ? (
          <div className="rounded-lg bg-green-50 p-6 text-center">
            <p className="text-lg font-medium text-green-800">
              メールを送信しました
            </p>
            <p className="mt-2 text-sm text-green-600">
              {email} に届いたリンクをタップしてログインしてください。
            </p>
          </div>
        ) : (
          <form onSubmit={handleLogin} className="space-y-4">
            <div>
              <label
                htmlFor="email"
                className="block text-sm font-medium text-gray-700"
              >
                メールアドレス
              </label>
              <input
                id="email"
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="example@email.com"
                className="mt-1 block w-full rounded-lg border border-gray-300 px-4 py-3 text-base focus:border-green-500 focus:outline-none focus:ring-1 focus:ring-green-500"
              />
            </div>

            {error && (
              <p className="text-sm text-red-600">{error}</p>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full rounded-lg bg-green-600 px-4 py-3 text-base font-medium text-white hover:bg-green-700 disabled:opacity-50"
            >
              {loading ? '送信中...' : 'マジックリンクを送信'}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
