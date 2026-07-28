"use client";

import { useState, useRef } from "react";
import type { AggregatedResult } from "@/lib/kintai-parser";

interface AggregateResponse {
  yearMonth: string;
  results: AggregatedResult[];
  csv: string;
  employeeCount: number;
}

export default function Home() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<AggregateResponse | null>(null);
  const [datLoading, setDatLoading] = useState(false);
  const [datError, setDatError] = useState<string | null>(null);
  const [unmatchedNames, setUnmatchedNames] = useState<string[]>([]);
  const fileRef = useRef<HTMLInputElement>(null);
  const codeFileRef = useRef<HTMLInputElement>(null);

  async function handleUpload() {
    const file = fileRef.current?.files?.[0];
    if (!file) {
      setError("CSVファイルを選択してください。");
      return;
    }
    setLoading(true);
    setError(null);
    setData(null);

    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetch("/api/aggregate", { method: "POST", body: formData });
      const json = await res.json();
      if (!res.ok) {
        setError(json.error || "エラーが発生しました");
      } else {
        setData(json);
      }
    } catch {
      setError("通信エラーが発生しました。");
    } finally {
      setLoading(false);
    }
  }

  function downloadCSV() {
    if (!data) return;
    const blob = new Blob([data.csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `勤怠集計_${data.yearMonth}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  async function handleDatConvert() {
    if (!data) return;
    setDatLoading(true);
    setDatError(null);
    setUnmatchedNames([]);

    const formData = new FormData();
    formData.append("results", JSON.stringify(data.results));
    const codeFile = codeFileRef.current?.files?.[0];
    if (codeFile) {
      formData.append("codeFile", codeFile);
    }

    try {
      const res = await fetch("/api/convert-dat", { method: "POST", body: formData });
      const json = await res.json();
      if (!res.ok) {
        setDatError(json.error || "エラーが発生しました");
      } else {
        if (json.unmatched?.length > 0) {
          setUnmatchedNames(json.unmatched);
        }
        const blob = new Blob([json.dat], { type: "application/octet-stream" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "kintai.dat";
        a.click();
        URL.revokeObjectURL(url);
      }
    } catch {
      setDatError("通信エラーが発生しました。");
    } finally {
      setDatLoading(false);
    }
  }

  return (
    <div style={{ maxWidth: 1100, margin: "0 auto", padding: "2rem", fontFamily: "sans-serif" }}>
      <h1 style={{ borderBottom: "3px solid #2563eb", paddingBottom: "0.5rem" }}>
        勤怠管理Webアプリ
      </h1>

      {/* Step 1: CSVアップロード */}
      <section style={sectionStyle}>
        <h2>Step 1: 勤怠CSVアップロード</h2>
        <p style={{ color: "#666", fontSize: 14 }}>
          イースタッフィングからダウンロードした勤怠データCSVを選択してください。
        </p>
        <div style={{ display: "flex", gap: "1rem", alignItems: "center", marginTop: "0.5rem" }}>
          <input ref={fileRef} type="file" accept=".csv" style={fileInputStyle} />
          <button onClick={handleUpload} disabled={loading} style={buttonStyle}>
            {loading ? "集計中..." : "集計する"}
          </button>
        </div>
        {error && <p style={errorStyle}>{error}</p>}
      </section>

      {/* Step 2: 集計結果 */}
      {data && (
        <section style={sectionStyle}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <h2>Step 2: 集計結果 — {data.yearMonth}</h2>
            <button onClick={downloadCSV} style={buttonStyleGreen}>
              CSVダウンロード
            </button>
          </div>
          <p style={{ color: "#666", fontSize: 14 }}>
            {data.employeeCount}名の集計が完了しました。
          </p>
          <div style={{ overflowX: "auto" }}>
            <table style={tableStyle}>
              <thead>
                <tr>
                  <th style={thStyle}>コード</th>
                  <th style={thStyle}>スタッフ名</th>
                  <th style={thStyle}>就業先</th>
                  <th style={thStyle}>契約時間</th>
                  <th style={thStyle}>出勤日数</th>
                  <th style={thStyle}>勤務時間</th>
                  <th style={thStyle}>残業時間</th>
                  <th style={thStyle}>休日出勤</th>
                  <th style={thStyle}>有給日数</th>
                  <th style={thStyle}>有給時間</th>
                </tr>
              </thead>
              <tbody>
                {data.results.map((r, i) => (
                  <tr key={i} style={i % 2 === 0 ? {} : { backgroundColor: "#f8fafc" }}>
                    <td style={tdStyle}>{r.staffCode}</td>
                    <td style={tdStyle}>{r.staffName}</td>
                    <td style={tdStyle}>{r.companyName}</td>
                    <td style={tdStyleNum}>{r.contractHours}</td>
                    <td style={tdStyleNum}>{r.workDays}</td>
                    <td style={tdStyleNum}>{r.workHours}</td>
                    <td style={tdStyleNum}>{r.overtimeHours > 0 ? r.overtimeHours : "-"}</td>
                    <td style={tdStyleNum}>{r.holidayWorkHours > 0 ? r.holidayWorkHours : "-"}</td>
                    <td style={tdStyleNum}>{r.paidLeaveDays > 0 ? r.paidLeaveDays : "-"}</td>
                    <td style={tdStyleNum}>{r.paidLeaveHours > 0 ? r.paidLeaveHours : "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Step 3: dat変換 */}
          <div style={{ marginTop: "2rem", padding: "1.5rem", backgroundColor: "#f1f5f9", borderRadius: 8 }}>
            <h3 style={{ marginTop: 0 }}>Step 3: datファイル変換（任意）</h3>
            <p style={{ color: "#666", fontSize: 14 }}>
              給与システム用のdatファイルに変換します。社員番号対応表（社員番号.txt）があれば選択してください。
            </p>
            <div style={{ display: "flex", gap: "1rem", alignItems: "center", flexWrap: "wrap" }}>
              <label style={{ fontSize: 14 }}>
                社員番号.txt（任意）:
                <input ref={codeFileRef} type="file" accept=".txt" style={{ ...fileInputStyle, marginLeft: 8 }} />
              </label>
              <button onClick={handleDatConvert} disabled={datLoading} style={buttonStyle}>
                {datLoading ? "変換中..." : "datファイル生成"}
              </button>
            </div>
            {datError && <p style={errorStyle}>{datError}</p>}
            {unmatchedNames.length > 0 && (
              <div style={{ marginTop: "0.5rem", padding: "0.5rem", backgroundColor: "#fef3c7", borderRadius: 4 }}>
                <p style={{ margin: 0, fontSize: 14, fontWeight: "bold" }}>
                  以下の従業員は社員番号対応表に一致しませんでした（スタッフコードで代用）:
                </p>
                <ul style={{ margin: "0.25rem 0 0", paddingLeft: "1.5rem", fontSize: 14 }}>
                  {unmatchedNames.map((n, i) => (
                    <li key={i}>{n}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </section>
      )}
    </div>
  );
}

// --- Styles ---
const sectionStyle: React.CSSProperties = {
  marginTop: "1.5rem",
  padding: "1.5rem",
  border: "1px solid #e2e8f0",
  borderRadius: 8,
};

const buttonStyle: React.CSSProperties = {
  padding: "0.5rem 1.5rem",
  backgroundColor: "#2563eb",
  color: "white",
  border: "none",
  borderRadius: 6,
  cursor: "pointer",
  fontSize: 14,
  fontWeight: "bold",
};

const buttonStyleGreen: React.CSSProperties = {
  ...buttonStyle,
  backgroundColor: "#16a34a",
};

const fileInputStyle: React.CSSProperties = {
  fontSize: 14,
};

const errorStyle: React.CSSProperties = {
  color: "#dc2626",
  fontSize: 14,
  marginTop: "0.5rem",
};

const tableStyle: React.CSSProperties = {
  width: "100%",
  borderCollapse: "collapse",
  fontSize: 14,
  marginTop: "0.5rem",
};

const thStyle: React.CSSProperties = {
  backgroundColor: "#1e3a5f",
  color: "white",
  padding: "0.5rem 0.75rem",
  textAlign: "left",
  fontSize: 13,
  whiteSpace: "nowrap",
};

const tdStyle: React.CSSProperties = {
  padding: "0.5rem 0.75rem",
  borderBottom: "1px solid #e2e8f0",
};

const tdStyleNum: React.CSSProperties = {
  ...tdStyle,
  textAlign: "right",
  fontVariantNumeric: "tabular-nums",
};
