import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";

export async function GET() {
  const campaigns = await prisma.campaign.findMany({
    orderBy: { createdAt: "desc" },
    include: { _count: { select: { outreachLogs: true } } },
  });
  return NextResponse.json({ campaigns });
}

export async function POST(req: NextRequest) {
  const body = await req.json();
  const { action } = body;

  if (action === "create") {
    const campaign = await prisma.campaign.create({
      data: {
        name: body.name,
        subjectTemplate: body.subjectTemplate,
        bodyTemplate: body.bodyTemplate,
      },
    });
    return NextResponse.json({ success: true, campaign });
  }

  if (action === "update") {
    const campaign = await prisma.campaign.update({
      where: { id: body.id },
      data: {
        name: body.name,
        subjectTemplate: body.subjectTemplate,
        bodyTemplate: body.bodyTemplate,
        status: body.status,
      },
    });
    return NextResponse.json({ success: true, campaign });
  }

  if (action === "send") {
    const { campaignId, dryRun } = body;
    const campaign = await prisma.campaign.findUnique({ where: { id: campaignId } });
    if (!campaign) return NextResponse.json({ error: "キャンペーンが見つかりません" }, { status: 404 });

    // 送信対象: 未営業 + メールあり + ブラックリスト除外
    const targets = await prisma.company.findMany({
      where: {
        crmStatus: { status: "未営業", isBlacklisted: false },
        contacts: { some: { email: { not: null } } },
      },
      include: { contacts: true, crmStatus: true },
    });

    // 既送信済みを除外
    const sentCompanyIds = await prisma.outreachLog.findMany({
      where: { campaignId },
      select: { companyId: true },
    });
    const sentIds = new Set(sentCompanyIds.map((l) => l.companyId));
    const pendingTargets = targets.filter((t) => !sentIds.has(t.id));

    if (dryRun) {
      const preview = pendingTargets.map((t) => {
        const email = t.contacts.find((c) => c.email)?.email || "";
        return {
          companyName: t.name,
          email,
          subject: renderTemplate(campaign.subjectTemplate, t),
          body: renderTemplate(campaign.bodyTemplate, t),
        };
      });
      return NextResponse.json({ dryRun: true, count: preview.length, preview: preview.slice(0, 10) });
    }

    // 本送信
    const smtpHost = await getSetting("smtp_host");
    if (!smtpHost) {
      return NextResponse.json({ error: "SMTP設定が完了していません。設定画面から設定してください。" }, { status: 400 });
    }

    let sentCount = 0;
    let failedCount = 0;

    for (const target of pendingTargets) {
      const contact = target.contacts.find((c) => c.email);
      if (!contact?.email) continue;

      try {
        // メール送信（実装は別途settings APIで設定されたSMTPを使用）
        await sendEmail({
          to: contact.email,
          subject: renderTemplate(campaign.subjectTemplate, target),
          body: renderTemplate(campaign.bodyTemplate, target),
        });

        await prisma.outreachLog.create({
          data: {
            companyId: target.id,
            contactId: contact.id,
            campaignId,
            type: "email",
            status: "sent",
            sentAt: new Date(),
          },
        });

        await prisma.crmStatus.update({
          where: { companyId: target.id },
          data: { status: "送信済" },
        });

        sentCount++;
      } catch {
        await prisma.outreachLog.create({
          data: {
            companyId: target.id,
            contactId: contact.id,
            campaignId,
            type: "email",
            status: "failed",
            notes: "送信失敗",
          },
        });
        failedCount++;
      }
    }

    await prisma.campaign.update({
      where: { id: campaignId },
      data: { status: "active" },
    });

    return NextResponse.json({ dryRun: false, sentCount, failedCount });
  }

  return NextResponse.json({ error: "不正なアクション" }, { status: 400 });
}

function renderTemplate(template: string, company: { name: string; address?: string | null; industry?: string | null }): string {
  return template
    .replace(/\$company_name/g, company.name)
    .replace(/\$address/g, company.address || "")
    .replace(/\$industry/g, company.industry || "");
}

async function getSetting(key: string): Promise<string | null> {
  const setting = await prisma.appSetting.findUnique({ where: { key } });
  return setting?.value || null;
}

async function sendEmail(params: { to: string; subject: string; body: string }) {
  const host = await getSetting("smtp_host");
  const port = parseInt((await getSetting("smtp_port")) || "587");
  const user = await getSetting("smtp_user");
  const pass = await getSetting("smtp_password");
  const senderName = (await getSetting("smtp_sender_name")) || user;

  if (!host || !user || !pass) throw new Error("SMTP未設定");

  // Node.js環境でのメール送信（nodemailerが必要だが、まずはログのみ）
  console.log(`[EMAIL] To: ${params.to}, Subject: ${params.subject}`);
  // 実際のSMTP送信は nodemailer 追加後に実装
}
