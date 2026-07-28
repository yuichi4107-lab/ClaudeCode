import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/prisma";

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const status = searchParams.get("status");
  const blacklist = searchParams.get("blacklist") === "true";
  const sortBy = searchParams.get("sort") || "score";

  const where: Record<string, unknown> = {};
  if (blacklist) {
    where.isBlacklisted = true;
  } else {
    where.isBlacklisted = false;
    if (status) where.status = status;
  }

  const orderBy = sortBy === "score" ? { score: "desc" as const } : { company: { name: "asc" as const } };

  const crmList = await prisma.crmStatus.findMany({
    where,
    include: { company: { include: { contacts: true } } },
    orderBy: sortBy === "score" ? { score: "desc" } : { updatedAt: "desc" },
  });

  return NextResponse.json({ crmList });
}

export async function POST(req: NextRequest) {
  const body = await req.json();
  const { action, companyId } = body;

  if (action === "updateStatus") {
    const updated = await prisma.crmStatus.update({
      where: { companyId },
      data: { status: body.status },
    });
    return NextResponse.json({ success: true, updated });
  }

  if (action === "updateMemo") {
    const updated = await prisma.crmStatus.update({
      where: { companyId },
      data: { memo: body.memo },
    });
    return NextResponse.json({ success: true, updated });
  }

  if (action === "toggleBlacklist") {
    const current = await prisma.crmStatus.findUnique({ where: { companyId } });
    if (!current) return NextResponse.json({ error: "Not found" }, { status: 404 });
    const updated = await prisma.crmStatus.update({
      where: { companyId },
      data: { isBlacklisted: !current.isBlacklisted },
    });
    return NextResponse.json({ success: true, updated });
  }

  return NextResponse.json({ error: "不正なアクション" }, { status: 400 });
}
