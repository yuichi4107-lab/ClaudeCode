#!/usr/bin/env node
/**
 * 新しいアプリを _template からコピーして作成するスクリプト
 * 使い方: npm run new-app -- <app-name> "<表示タイトル>" <ポート番号>
 * 例:    npm run new-app -- invoice-tool "請求書管理ツール" 3004
 */

import { cpSync, readFileSync, writeFileSync } from "fs";
import { join, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const rootDir = join(__dirname, "..");

const [appName, title, port] = process.argv.slice(2);

if (!appName) {
  console.error("使い方: npm run new-app -- <app-name> \"<タイトル>\" <ポート>");
  console.error("例:    npm run new-app -- invoice-tool \"請求書管理\" 3004");
  process.exit(1);
}

const displayTitle = title || appName;
const appPort = port || "3000";
const templateDir = join(rootDir, "apps", "_template");
const targetDir = join(rootDir, "apps", appName);

// コピー
cpSync(templateDir, targetDir, { recursive: true });

// package.json を更新
const pkgPath = join(targetDir, "package.json");
const pkg = JSON.parse(readFileSync(pkgPath, "utf-8"));
pkg.name = `@yn-tools/${appName}`;
pkg.scripts.dev = `next dev --port ${appPort}`;
writeFileSync(pkgPath, JSON.stringify(pkg, null, 2) + "\n");

// layout.tsx を更新
const layoutPath = join(targetDir, "src", "app", "layout.tsx");
let layout = readFileSync(layoutPath, "utf-8");
layout = layout.replace("YN Tool", displayTitle);
layout = layout.replace("YN Factory Tool", displayTitle);
writeFileSync(layoutPath, layout);

// page.tsx を更新
const pagePath = join(targetDir, "src", "app", "page.tsx");
let page = readFileSync(pagePath, "utf-8");
page = page.replace("New Tool", displayTitle);
page = page.replace(
  "このテンプレートをベースに新しいツールを作成してください。",
  `${displayTitle}のダッシュボードです。`
);
writeFileSync(pagePath, page);

console.log(`✓ アプリ "${appName}" を作成しました！`);
console.log(`  場所: apps/${appName}/`);
console.log(`  開発: cd apps/${appName} && npm run dev (ポート: ${appPort})`);
console.log(`  次のステップ: npm install → npm run dev`);
