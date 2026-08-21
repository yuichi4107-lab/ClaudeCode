import { NextRequest, NextResponse } from "next/server";
import {
  resultsToDat,
  parseEmployeeCodeFile,
  type AggregatedResult,
} from "@/lib/kintai-parser";

export async function POST(req: NextRequest) {
  try {
    const formData = await req.formData();
    const resultsJson = formData.get("results") as string | null;
    const codeFile = formData.get("codeFile") as File | null;

    if (!resultsJson) {
      return NextResponse.json({ error: "集計データがありません" }, { status: 400 });
    }

    const results: AggregatedResult[] = JSON.parse(resultsJson);

    let employeeCodeMap = new Map<string, string>();
    if (codeFile) {
      const buffer = await codeFile.arrayBuffer();
      const decoder = new TextDecoder("shift-jis");
      const text = decoder.decode(buffer);
      employeeCodeMap = parseEmployeeCodeFile(text);
    }

    const { dat, unmatched } = resultsToDat(results, employeeCodeMap);

    return NextResponse.json({ dat, unmatched });
  } catch (e: unknown) {
    const message = e instanceof Error ? e.message : "不明なエラー";
    return NextResponse.json({ error: `変換中にエラーが発生しました: ${message}` }, { status: 500 });
  }
}
