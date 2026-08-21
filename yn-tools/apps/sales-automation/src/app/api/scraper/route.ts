import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";

export async function POST(req: NextRequest) {
  const body = await req.json();
  const { action } = body;

  if (action === "crawl_single") {
    const { companyId } = body;
    const company = await prisma.company.findUnique({ where: { id: companyId } });
    if (!company?.websiteUrl) {
      return NextResponse.json({ error: "WebサイトURLが登録されていません" }, { status: 400 });
    }
    const result = await crawlWebsite(company.websiteUrl);
    // 連絡先を保存
    if (result.emails.length > 0 || result.contactFormUrl || result.instagram || result.twitter || result.facebook) {
      await prisma.contact.create({
        data: {
          companyId,
          email: result.emails[0]?.address || null,
          emailType: result.emails[0]?.type || null,
          contactFormUrl: result.contactFormUrl || null,
          snsInstagram: result.instagram || null,
          snsTwitter: result.twitter || null,
          snsFacebook: result.facebook || null,
          extractedAt: new Date(),
        },
      });
    }
    // スコア計算
    const score = calculateScore(company, result);
    await prisma.crmStatus.update({
      where: { companyId },
      data: { score },
    });
    if (result.description) {
      await prisma.company.update({
        where: { id: companyId },
        data: { description: result.description },
      });
    }
    return NextResponse.json({ success: true, result, score });
  }

  if (action === "bulk_crawl") {
    const companies = await prisma.company.findMany({
      where: {
        websiteUrl: { not: null },
        contacts: { none: {} },
        crmStatus: { isBlacklisted: false },
      },
      take: 50,
    });

    let crawled = 0;
    let failed = 0;
    for (const company of companies) {
      if (!company.websiteUrl) continue;
      try {
        const result = await crawlWebsite(company.websiteUrl);
        if (result.emails.length > 0 || result.contactFormUrl) {
          await prisma.contact.create({
            data: {
              companyId: company.id,
              email: result.emails[0]?.address || null,
              emailType: result.emails[0]?.type || null,
              contactFormUrl: result.contactFormUrl || null,
              snsInstagram: result.instagram || null,
              snsTwitter: result.twitter || null,
              snsFacebook: result.facebook || null,
              extractedAt: new Date(),
            },
          });
        }
        const score = calculateScore(company, result);
        await prisma.crmStatus.update({
          where: { companyId: company.id },
          data: { score },
        });
        crawled++;
      } catch {
        failed++;
      }
    }

    return NextResponse.json({ crawled, failed, total: companies.length });
  }

  return NextResponse.json({ error: "不正なアクション" }, { status: 400 });
}

interface CrawlResult {
  emails: Array<{ address: string; type: string }>;
  contactFormUrl: string | null;
  instagram: string | null;
  twitter: string | null;
  facebook: string | null;
  description: string | null;
}

async function crawlWebsite(url: string): Promise<CrawlResult> {
  const result: CrawlResult = {
    emails: [], contactFormUrl: null,
    instagram: null, twitter: null, facebook: null, description: null,
  };

  try {
    const res = await fetch(url, {
      headers: { "User-Agent": "Mozilla/5.0" },
      signal: AbortSignal.timeout(10000),
    });
    const html = await res.text();

    // メールアドレス抽出
    const emailRegex = /[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/g;
    const emails = [...new Set(html.match(emailRegex) || [])];
    for (const email of emails) {
      const lower = email.toLowerCase();
      let type = "other";
      if (lower.startsWith("info")) type = "info";
      else if (lower.includes("contact")) type = "contact";
      else if (lower.includes("support")) type = "support";
      result.emails.push({ address: email, type });
    }
    result.emails.sort((a, b) => {
      const order = { info: 0, contact: 1, support: 2, other: 3 };
      return (order[a.type as keyof typeof order] || 3) - (order[b.type as keyof typeof order] || 3);
    });

    // お問い合わせフォーム検出
    const formMatch = html.match(/href=["']([^"']*(?:contact|inquiry|otoiawase|toiawase)[^"']*)["']/i);
    if (formMatch) {
      result.contactFormUrl = new URL(formMatch[1], url).href;
    }

    // SNS抽出
    const igMatch = html.match(/https?:\/\/(?:www\.)?instagram\.com\/[a-zA-Z0-9_.]+/);
    if (igMatch) result.instagram = igMatch[0];
    const twMatch = html.match(/https?:\/\/(?:www\.)?(?:twitter|x)\.com\/[a-zA-Z0-9_]+/);
    if (twMatch) result.twitter = twMatch[0];
    const fbMatch = html.match(/https?:\/\/(?:www\.)?facebook\.com\/[a-zA-Z0-9.]+/);
    if (fbMatch) result.facebook = fbMatch[0];

    // description
    const descMatch = html.match(/<meta[^>]+name=["']description["'][^>]+content=["']([^"']+)["']/i);
    if (descMatch) result.description = descMatch[1];
  } catch {
    // crawl failed
  }

  return result;
}

function calculateScore(
  company: { websiteUrl: string | null; reviewCount: number },
  result: CrawlResult
): number {
  let score = 0;
  if (result.emails.length > 0) score += 30;
  if (company.websiteUrl) score += 20;
  if (company.reviewCount >= 10) score += 20;
  if (result.contactFormUrl) score += 15;
  let snsCount = 0;
  if (result.instagram) snsCount++;
  if (result.twitter) snsCount++;
  if (result.facebook) snsCount++;
  score += Math.min(snsCount * 5, 15);
  return score;
}
