import { NextRequest, NextResponse } from "next/server";
import {
  decodeCp932,
  parseEStaffingCSV,
  aggregateEmployee,
  resultsToCSV,
  detectYearMonth,
} from "@/lib/kintai-parser";

export async function POST(req: NextRequest) {
  try {
    const formData = await req.formData();
    const file = formData.get("file") as File | null;

    if (!file) {
      return NextResponse.json({ error: "ファイルが選択されていません" }, { status: 400 });
    }

    const buffer = await file.arrayBuffer();
    const csvText = decodeCp932(buffer);
    const employees = parseEStaffingCSV(csvText);

    if (employees.length === 0) {
      return NextResponse.json(
        { error: "従業員データが見つかりませんでした。イースタッフィング形式のCSVか確認してください。" },
        { status: 400 }
      );
    }

    const results = employees.map(aggregateEmployee);
    const yearMonth = detectYearMonth(employees);
    const csv = resultsToCSV(results, yearMonth);

    return NextResponse.json({
      yearMonth,
      results,
      csv,
      employeeCount: results.length,
    });
  } catch (e: unknown) {
    const message = e instanceof Error ? e.message : "不明なエラー";
    return NextResponse.json({ error: `処理中にエラーが発生しました: ${message}` }, { status: 500 });
  }
}
