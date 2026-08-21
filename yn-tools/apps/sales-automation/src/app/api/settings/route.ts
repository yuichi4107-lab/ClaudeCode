import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";

export async function GET() {
  const keys = ["smtp_host", "smtp_port", "smtp_user", "smtp_sender_name"];
  const settings: Record<string, string> = {};
  for (const key of keys) {
    const s = await prisma.appSetting.findUnique({ where: { key } });
    settings[key] = s?.value || "";
  }
  return NextResponse.json({ settings });
}

export async function POST(req: NextRequest) {
  const body = await req.json();
  const { action } = body;

  if (action === "save") {
    const entries = [
      ["smtp_host", body.smtpHost],
      ["smtp_port", body.smtpPort],
      ["smtp_user", body.smtpUser],
      ["smtp_password", body.smtpPassword],
      ["smtp_sender_name", body.senderName],
    ];
    for (const [key, value] of entries) {
      if (value !== undefined && value !== "") {
        await prisma.appSetting.upsert({
          where: { key },
          update: { value: String(value) },
          create: { key, value: String(value) },
        });
      }
    }
    return NextResponse.json({ success: true });
  }

  if (action === "test") {
    // テストメール送信（簡易版）
    return NextResponse.json({ success: true, message: "テストメール機能は今後実装予定です" });
  }

  return NextResponse.json({ error: "不正なアクション" }, { status: 400 });
}
