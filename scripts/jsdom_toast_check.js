#!/usr/bin/env node
/**
 * 前端提示（toast）的實際渲染驗證 —— V2.11.4 S-01
 *
 * 為什麼需要這支：後端煙霧測試、Jinja parse、node --check 都看不見「頁面載入後
 * 提示會不會真的出現」。V2.11.3 的 toast 在兩個情境下永遠不顯示，三支檢查全綠。
 *
 * 做法：把 Python 端渲染好的 HTML 載進 jsdom，再把 Alpine 放在 body 最後執行，
 * 等同正式環境 `defer` 的順序（先跑完頁面內所有 inline script，再初始化 Alpine）。
 * 然後檢查 toast 元件的文字。
 *
 * 用法（由 scripts/check_frontend_toast.py 呼叫，也可手動）：
 *   node scripts/jsdom_toast_check.js <html檔> <期望文字> [<網址>]
 *
 * 需要 node_modules/jsdom 與 node_modules/alpinejs（見 check_frontend_toast.py）。
 */
const fs = require('fs');
const path = require('path');

const [,, htmlPath, expected, urlArg] = process.argv;
if (!htmlPath || !expected) {
  console.error('用法：node jsdom_toast_check.js <html檔> <期望文字> [<網址>]');
  process.exit(2);
}

let JSDOM;
try {
  ({ JSDOM } = require('jsdom'));
} catch (e) {
  console.log('SKIP 沒有 jsdom');
  process.exit(3);
}

let alpinePath;
try {
  alpinePath = require.resolve('alpinejs/dist/cdn.js');
} catch (e) {
  console.log('SKIP 沒有 alpinejs');
  process.exit(3);
}

let html = fs.readFileSync(htmlPath, 'utf8');
// 拿掉外部 CDN 的 script（jsdom 不連網），Alpine 改由本機注入
html = html.replace(/<script[^>]+src=["'][^"']*(?:alpinejs|htmx|tailwindcss)[^"']*["'][^>]*>\s*<\/script>/gi, '');

// 拿掉依賴 tailwind 全域物件的 inline 設定（CDN 沒載，會 ReferenceError，純雜訊）
html = html.replace(/<script>\s*tailwind\.config[\s\S]*?<\/script>/i, '');

const alpineSrc = fs.readFileSync(alpinePath, 'utf8');
// 把 Alpine 放在 body 最後，模擬 defer：頁面 inline script 先跑完才初始化
html = html.replace(/<\/body>/i, `<script>${alpineSrc}</script></body>`);

const dom = new JSDOM(html, {
  url: urlArg || 'http://localhost/page',
  runScripts: 'dangerously',
  pretendToBeVisual: true,
});

const { window } = dom;

// 給 Alpine 一點時間初始化（它用 queueMicrotask / MutationObserver）
setTimeout(() => {
  const el = window.document.querySelector('[x-data*="msg"]');
  const text = el ? (el.textContent || '').trim() : '';
  const shown = el && !/display:\s*none/.test(el.getAttribute('style') || '');
  const ok = text.includes(expected) && shown;
  console.log(JSON.stringify({ ok, text, shown, expected }));
  process.exit(ok ? 0 : 1);
}, 200);
