/**
 * イースタッフィング勤怠CSV パーサー＆集計エンジン
 */

export interface DayRecord {
  date: Date;
  category: number | null; // 1=出勤, 2=全日有給, 4=欠勤, 5=半日有給+半日出勤
  startTime: string;
  endTime: string;
  breakTime: string;
  actualMinutes: number; // 実労働時間（分）
  contractMinutes: number; // 契約内時間（分）
  legalOvertimeMinutes: number; // 法定内契約外（分）
  extraOvertimeMinutes: number; // 法定外契約外（分）
  nightMinutes: number; // 深夜勤務（分）
  holidayMinutes: number; // 休日労働（分）
  paidLeaveMinutes: number; // 年休時間（分）
}

export interface Employee {
  contractNo: string;
  staffCode: string;
  staffName: string;
  companyName: string;
  contractMinutesPerDay: number; // 契約勤務時間（分）
  days: DayRecord[];
}

export interface AggregatedResult {
  staffCode: string;
  staffName: string;
  companyName: string;
  contractHours: number;
  workDays: number;
  workHours: number;
  overtimeHours: number;
  holidayWorkHours: number;
  paidLeaveDays: number;
  paidLeaveHours: number;
  lastWeekNormalHours: number;
}

/** H:MM or HH:MM 形式を分に変換 */
function parseHMM(value: string): number {
  if (!value || value.trim() === "") return 0;
  const parts = value.trim().split(":");
  if (parts.length !== 2) return 0;
  const h = parseInt(parts[0], 10) || 0;
  const m = parseInt(parts[1], 10) || 0;
  return h * 60 + m;
}

/** 分を10進法の時間に変換（小数点以下3位で切り捨て） */
export function minutesToDecimalHours(minutes: number): number {
  return Math.floor((minutes / 60) * 1000) / 1000;
}

/** 日付から週の月曜日を取得 */
function getWeekMonday(date: Date): string {
  const d = new Date(date);
  const day = d.getDay();
  const diff = day === 0 ? 6 : day - 1; // 月曜始まり
  d.setDate(d.getDate() - diff);
  return d.toISOString().slice(0, 10);
}

/** cp932 バイナリを文字列にデコード */
export function decodeCp932(buffer: ArrayBuffer): string {
  const decoder = new TextDecoder("shift-jis");
  return decoder.decode(buffer);
}

/** CSVテキストをパースする（ダブルクォート内改行対応） */
function parseCSVLine(text: string): string[][] {
  const rows: string[][] = [];
  let current = "";
  let inQuotes = false;
  let row: string[] = [];

  for (let i = 0; i < text.length; i++) {
    const ch = text[i];

    if (inQuotes) {
      if (ch === '"') {
        if (i + 1 < text.length && text[i + 1] === '"') {
          current += '"';
          i++;
        } else {
          inQuotes = false;
        }
      } else {
        current += ch;
      }
    } else {
      if (ch === '"') {
        inQuotes = true;
      } else if (ch === ",") {
        row.push(current);
        current = "";
      } else if (ch === "\n") {
        row.push(current);
        current = "";
        if (row.length > 1 || (row.length === 1 && row[0] !== "")) {
          rows.push(row);
        }
        row = [];
      } else if (ch === "\r") {
        // skip
      } else {
        current += ch;
      }
    }
  }
  if (current || row.length > 0) {
    row.push(current);
    rows.push(row);
  }
  return rows;
}

/** イースタッフィングCSVをパースして従業員リストを返す */
export function parseEStaffingCSV(csvText: string): Employee[] {
  const rows = parseCSVLine(csvText);
  const employees: Employee[] = [];
  let currentEmployee: Employee | null = null;

  for (const cols of rows) {
    if (cols[0] === "H") {
      currentEmployee = {
        contractNo: cols[1] || "",
        staffCode: cols[4] || "",
        staffName: cols[5] || "",
        companyName: cols[7] || "",
        contractMinutesPerDay: parseHMM(cols[19] || ""),
        days: [],
      };
      employees.push(currentEmployee);
    } else if (cols[0] === "D" && currentEmployee) {
      const dateParts = (cols[1] || "").split("/");
      const date = new Date(
        parseInt(dateParts[0]),
        parseInt(dateParts[1]) - 1,
        parseInt(dateParts[2])
      );

      const catStr = (cols[2] || "").trim();
      const category = catStr ? parseInt(catStr, 10) : null;

      currentEmployee.days.push({
        date,
        category,
        startTime: cols[3] || "",
        endTime: cols[4] || "",
        breakTime: cols[5] || "",
        actualMinutes: parseHMM(cols[9] || ""),
        contractMinutes: parseHMM(cols[10] || ""),
        legalOvertimeMinutes: parseHMM(cols[11] || ""),
        extraOvertimeMinutes: parseHMM(cols[12] || ""),
        nightMinutes: parseHMM(cols[13] || ""),
        holidayMinutes: parseHMM(cols[14] || ""),
        paidLeaveMinutes: parseHMM(cols[15] || ""),
      });
    }
  }
  return employees;
}

/** 従業員データを集計する */
export function aggregateEmployee(emp: Employee): AggregatedResult {
  // 出勤日数
  let workDays = 0;
  for (const d of emp.days) {
    if (d.category === 1 || d.category === 5) workDays++;
  }

  // 実労働時間合計
  let totalActualMinutes = 0;
  for (const d of emp.days) {
    totalActualMinutes += d.actualMinutes;
  }

  // 日次残業（1日8h超過分）
  let dailyOvertimeMinutes = 0;
  for (const d of emp.days) {
    if (d.actualMinutes > 480) {
      dailyOvertimeMinutes += d.actualMinutes - 480;
    }
  }

  // 週40h超過残業
  const weeklyTotals = new Map<string, number>();
  for (const d of emp.days) {
    if (d.category === 1 || d.category === 5) {
      const mondayKey = getWeekMonday(d.date);
      weeklyTotals.set(
        mondayKey,
        (weeklyTotals.get(mondayKey) || 0) + d.actualMinutes
      );
    }
  }

  let weeklyOvertimeMinutes = 0;
  let lastWeekNormalMinutes = 0;

  // 月の最終日を特定
  const allDates = emp.days.map((d) => d.date).sort((a, b) => a.getTime() - b.getTime());
  const lastDate = allDates.length > 0 ? allDates[allDates.length - 1] : null;
  const lastMonday = lastDate ? getWeekMonday(lastDate) : null;

  // 最終週が不完全かチェック
  let lastWeekIncomplete = false;
  if (lastDate) {
    const lastDay = lastDate.getDay();
    if (lastDay !== 0) {
      // 日曜でなければ不完全
      lastWeekIncomplete = true;
    }
  }

  for (const [mondayKey, total] of weeklyTotals) {
    if (total > 2400) {
      weeklyOvertimeMinutes += total - 2400;
    }
    if (mondayKey === lastMonday && lastWeekIncomplete) {
      lastWeekNormalMinutes = Math.min(total, 2400);
    }
  }

  const totalOvertimeMinutes = dailyOvertimeMinutes + weeklyOvertimeMinutes;

  // 勤務時間 = 実労働時間 - 週40h超過分
  const workMinutes = totalActualMinutes - weeklyOvertimeMinutes;

  // 休日出勤時間
  let holidayMinutes = 0;
  for (const d of emp.days) {
    holidayMinutes += d.holidayMinutes;
  }

  // 有給取得日数・時間
  let paidLeaveDays = 0;
  let paidLeaveMinutes = 0;
  for (const d of emp.days) {
    if (d.category === 2) {
      paidLeaveDays += 1;
      paidLeaveMinutes += d.paidLeaveMinutes;
    } else if (d.category === 5) {
      paidLeaveDays += 0.5;
      paidLeaveMinutes += emp.contractMinutesPerDay - d.actualMinutes;
    }
  }

  return {
    staffCode: emp.staffCode,
    staffName: emp.staffName,
    companyName: emp.companyName,
    contractHours: minutesToDecimalHours(emp.contractMinutesPerDay),
    workDays,
    workHours: minutesToDecimalHours(workMinutes),
    overtimeHours: minutesToDecimalHours(totalOvertimeMinutes),
    holidayWorkHours: minutesToDecimalHours(holidayMinutes),
    paidLeaveDays,
    paidLeaveHours: minutesToDecimalHours(paidLeaveMinutes),
    lastWeekNormalHours: minutesToDecimalHours(lastWeekNormalMinutes),
  };
}

/** 集計結果をCSV文字列に変換 */
export function resultsToCSV(results: AggregatedResult[], yearMonth: string): string {
  const bom = "\uFEFF";
  const header = [
    "スタッフコード",
    "スタッフ名",
    "就業先企業名",
    "契約勤務時間",
    "出勤日数",
    "勤務時間",
    "残業時間",
    "休日出勤時間",
    "有給取得日数",
    "有給取得時間",
    "最終週通常時間",
  ].join(",");

  const rows = results.map((r) =>
    [
      r.staffCode,
      r.staffName,
      r.companyName,
      r.contractHours,
      r.workDays,
      r.workHours,
      r.overtimeHours,
      r.holidayWorkHours,
      r.paidLeaveDays,
      r.paidLeaveHours,
      r.lastWeekNormalHours,
    ].join(",")
  );

  return bom + [header, ...rows].join("\n");
}

/** 集計データからdat文字列を生成 */
export function resultsToDat(
  results: AggregatedResult[],
  employeeCodeMap: Map<string, string>
): { dat: string; unmatched: string[] } {
  const OLD_TO_NEW: Record<string, string> = {
    "髙": "高", "惠": "恵", "邉": "辺", "邊": "辺",
    "齋": "斎", "齊": "斎", "澤": "沢", "櫻": "桜",
    "國": "国", "廣": "広", "橫": "横",
  };

  const MANUAL_NAME_MAP: Record<string, string> = {
    "児玉 桂子": "渡邊 桂子",
  };

  function normalize(name: string): string {
    let result = name;
    for (const [old, newChar] of Object.entries(OLD_TO_NEW)) {
      result = result.replaceAll(old, newChar);
    }
    return result;
  }

  // 正規化済みマップも作成
  const normalizedMap = new Map<string, string>();
  for (const [name, code] of employeeCodeMap) {
    normalizedMap.set(normalize(name), code);
  }

  const lines: string[] = [];
  const unmatched: string[] = [];

  for (const r of results) {
    // 社員コード特定
    let code: string | undefined;
    const mappedName = MANUAL_NAME_MAP[r.staffName];

    if (mappedName) {
      code = employeeCodeMap.get(mappedName) || normalizedMap.get(normalize(mappedName));
    }
    if (!code) {
      code = employeeCodeMap.get(r.staffName);
    }
    if (!code) {
      code = normalizedMap.get(normalize(r.staffName));
    }
    if (!code) {
      code = r.staffCode.padStart(6, "0");
      unmatched.push(r.staffName);
    }

    // 90フィールド
    const fields: string[] = new Array(90).fill("");
    const fmt = (v: number) => (v === 0 ? "" : v.toFixed(2));

    fields[0] = code;
    fields[1] = fmt(r.workDays + r.paidLeaveDays); // 要勤日数
    fields[3] = fmt(r.workDays); // 出勤日数
    fields[4] = fmt(r.workHours + r.paidLeaveHours); // 出勤時間
    fields[9] = fmt(r.paidLeaveDays); // 有休
    fields[11] = fmt(r.overtimeHours); // 平日普通残業
    fields[15] = fmt(r.holidayWorkHours); // 法定普通（休日出勤）

    lines.push(fields.join(","));
  }

  const dat = lines.join("\r\n") + "\r\n\x1A";
  return { dat, unmatched };
}

/** 社員番号対応表（タブ区切り、cp932）をパース */
export function parseEmployeeCodeFile(text: string): Map<string, string> {
  const map = new Map<string, string>();
  const lines = text.split(/\r?\n/);
  // 1行目はヘッダー、スキップ
  for (let i = 1; i < lines.length; i++) {
    const parts = lines[i].split("\t");
    if (parts.length >= 2) {
      const code = parts[0].trim();
      const name = parts[1].trim();
      if (code && name) {
        map.set(name, code);
      }
    }
  }
  return map;
}

/** CSVデータから年月を自動判定 */
export function detectYearMonth(employees: Employee[]): string {
  for (const emp of employees) {
    for (const d of emp.days) {
      if (d.date) {
        const y = d.date.getFullYear();
        const m = d.date.getMonth() + 1;
        return `${y}年${m}月`;
      }
    }
  }
  return "不明";
}
