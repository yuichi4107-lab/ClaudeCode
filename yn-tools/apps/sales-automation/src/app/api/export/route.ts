import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const status = searchParams.get("status");
  const excludeBlacklist = searchParams.get("excludeBlacklist") !== "false";

  const where: Record<string, unknown> = {};
  if (excludeBlacklist) where.isBlacklisted = false;
  if (status) where.status = status;

  const data = await prisma.crmStatus.findMany({
    where,
    include: {
      company: { include: { contacts: true } },
    },
    orderBy: { score: "desc" },
  });

  const bom = "\uFEFF";
  const header = "企業名,住所,電話番号,WebサイトURL,メールアドレス,ステータス,スコア,メモ";
  const rows = data.map((crm) => {
    const c = crm.company;
    const email = c.contacts.find((ct) => ct.email)?.email || "";
    return [
      csvEscape(c.name),
      csvEscape(c.address || ""),
      csvEscape(c.phone || ""),
      csvEscape(c.websiteUrl || ""),
      csvEscape(email),
      csvEscape(crm.status),
      crm.score,
      csvEscape(crm.memo || ""),
    ].join(",");
  });

  const csv = bom + [header, ...rows].join("\n");

  return new NextResponse(csv, {
    headers: {
      "Content-Type": "text/csv; charset=utf-8",
      "Content-Disposition": 'attachment; filename="sales_export.csv"',
    },
  });
}

function csvEscape(value: string): string {
  if (value.includes(",") || value.includes('"') || value.includes("\n")) {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return value;
}
