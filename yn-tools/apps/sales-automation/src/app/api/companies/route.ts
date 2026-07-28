import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const page = parseInt(searchParams.get("page") || "1");
  const search = searchParams.get("search") || "";
  const perPage = 20;

  const where = search
    ? { OR: [{ name: { contains: search } }, { region: { contains: search } }] }
    : {};

  const [companies, total] = await Promise.all([
    prisma.company.findMany({
      where,
      include: { crmStatus: true, contacts: true },
      orderBy: { updatedAt: "desc" },
      skip: (page - 1) * perPage,
      take: perPage,
    }),
    prisma.company.count({ where }),
  ]);

  return NextResponse.json({ companies, total, page, perPage, totalPages: Math.ceil(total / perPage) });
}

export async function POST(req: NextRequest) {
  const body = await req.json();
  const { action } = body;

  if (action === "search_scraping") {
    const { keyword, region } = body;
    // iタウンページスクレイピング
    const query = encodeURIComponent(`${keyword} ${region}`);
    try {
      const res = await fetch(`https://itp.ne.jp/result/?keyword=${query}`, {
        headers: { "User-Agent": "Mozilla/5.0" },
      });
      const html = await res.text();
      const results = parseItownPage(html);
      return NextResponse.json({ results });
    } catch {
      return NextResponse.json({ results: [], error: "検索に失敗しました" });
    }
  }

  if (action === "add") {
    const { companies } = body;
    const created = [];
    for (const c of companies) {
      const existing = await prisma.company.findFirst({ where: { name: c.name, address: c.address } });
      if (existing) continue;
      const company = await prisma.company.create({
        data: {
          name: c.name,
          address: c.address || null,
          phone: c.phone || null,
          websiteUrl: c.websiteUrl || null,
          industry: c.industry || null,
          region: c.region || null,
          crmStatus: { create: { status: "未営業", score: 0 } },
        },
      });
      created.push(company);
    }
    return NextResponse.json({ created: created.length });
  }

  return NextResponse.json({ error: "不正なアクション" }, { status: 400 });
}

function parseItownPage(html: string): Array<{ name: string; address: string; phone: string }> {
  const results: Array<{ name: string; address: string; phone: string }> = [];
  // シンプルな正規表現パース
  const nameRegex = /<a[^>]*class="[^"]*normalResultsLine[^"]*"[^>]*>([^<]+)<\/a>/g;
  const entries = html.split(/class="normalResultsBox"/);
  for (const entry of entries.slice(1, 21)) {
    const nameMatch = entry.match(/<a[^>]*>([^<]{2,})<\/a>/);
    const addrMatch = entry.match(/<p[^>]*class="[^"]*resultBodyAddress[^"]*"[^>]*>([^<]+)<\/p>/);
    const phoneMatch = entry.match(/<a[^>]*href="tel:([^"]+)"/);
    if (nameMatch) {
      results.push({
        name: nameMatch[1].trim(),
        address: addrMatch ? addrMatch[1].trim() : "",
        phone: phoneMatch ? phoneMatch[1] : "",
      });
    }
  }
  return results;
}
