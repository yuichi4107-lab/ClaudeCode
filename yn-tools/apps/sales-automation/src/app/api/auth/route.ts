import { NextRequest, NextResponse } from "next/server";
import { authenticate, createUser, getUserCount, SESSION_COOKIE } from "@/lib/auth";

export async function POST(req: NextRequest) {
  const body = await req.json();
  const { action, username, password } = body;

  if (action === "setup") {
    const count = await getUserCount();
    if (count > 0) {
      return NextResponse.json({ error: "既にユーザーが登録されています" }, { status: 400 });
    }
    if (!username || !password) {
      return NextResponse.json({ error: "ユーザー名とパスワードを入力してください" }, { status: 400 });
    }
    const user = await createUser(username, password);
    const res = NextResponse.json({ success: true, userId: user.id });
    res.cookies.set(SESSION_COOKIE, String(user.id), {
      httpOnly: true,
      maxAge: 60 * 60 * 24 * 7,
      path: "/",
    });
    return res;
  }

  if (action === "login") {
    const user = await authenticate(username, password);
    if (!user) {
      return NextResponse.json({ error: "ユーザー名またはパスワードが正しくありません" }, { status: 401 });
    }
    const res = NextResponse.json({ success: true });
    res.cookies.set(SESSION_COOKIE, String(user.id), {
      httpOnly: true,
      maxAge: 60 * 60 * 24 * 7,
      path: "/",
    });
    return res;
  }

  if (action === "logout") {
    const res = NextResponse.json({ success: true });
    res.cookies.delete(SESSION_COOKIE);
    return res;
  }

  return NextResponse.json({ error: "不正なアクション" }, { status: 400 });
}
