#!/usr/bin/env node
/**
 * 工作台直接改價（V2.29.0，外部審稿 V2.28.0 P1-B）
 *
 * 煙霧測試看得到後端存成新版本、其他內容照抄；看不到 Alpine 的輸入框、變色、搜尋與真正會送出的 changes_json。
 *   ?edit=price 進頁就是改價模式、原本的菜單卡藏起來；沒改時「存成第 N 版」停用
 *   改 M 價 → 變色、「改了 1 項」、送出的 JSON 只有那一項（含原本的 L 價）
 *   打字母 → 顯示錯誤、按鈕停用；時價沒有輸入框
 *   搜尋只留符合的品項；取消（確認）→ 離開改價模式、值還原
 *
 * 用法：node scripts/jsdom_price_check.js <html檔>
 */
const fs = require("fs");
const [,, htmlPath] = process.argv;
let JSDOM, VirtualConsole, alpineSrc;
try {
  ({ JSDOM, VirtualConsole } = require("jsdom"));
  alpineSrc = fs.readFileSync(require.resolve("alpinejs/dist/cdn.min.js"), "utf-8");
} catch (e) { console.log("SKIP 缺套件：" + e.message.split("\n")[0]); process.exit(3); }

const page = fs.readFileSync(htmlPath, "utf-8")
  .replace(/<script[^>]+src=["'][^"']*(?:alpinejs|htmx|tailwindcss)[^"']*["'][^>]*>\s*<\/script>/gi, "")
  .replace(/<link[^>]+>/g, "").replace(/<script>\s*tailwind\.config[\s\S]*?<\/script>/i, "");
const headScripts = (page.slice(0, page.indexOf("<body")).match(/<script>[\s\S]*?<\/script>/g) || []).join("\n");
const rawBody = page.slice(page.indexOf("<body")).replace(/^<body[^>]*>/, "").replace(/<\/body>\s*<\/html>\s*$/i, "");
const html = `<html><head>${headScripts}</head><body>${rawBody}<script>${alpineSrc}</script></body></html>`;
const vc = new VirtualConsole();
const jsErrors = [];
vc.on("jsdomError", (e) => jsErrors.push(String((e && e.message) || e).split("\n")[0].slice(0, 160)));
const dom = new JSDOM(html, { runScripts: "dangerously", url: "http://localhost/admin/stores/1?tab=menu&edit=price", pretendToBeVisual: true, virtualConsole: vc });
const w = dom.window;
w.confirm = () => true;
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
const fail = (msg) => { console.log(JSON.stringify({ ok: false, msg })); process.exit(1); };
const visible = (el) => { for (let e = el; e; e = e.parentElement) { if (e.style && e.style.display === "none") return false; } return !!el; };
const text = (el) => (el ? el.textContent.replace(/\s+/g, " ").trim() : "");

(async () => {
  await sleep(150);
  if (jsErrors.length) fail("頁面初始化有未攔截的 JS 錯誤：" + jsErrors.join(" | "));
  const d = w.document;
  const ed = d.getElementById("price-editor");
  if (!visible(ed)) fail("?edit=price 進頁應是改價模式");
  const save = d.getElementById("price-save");
  if (!save.disabled) fail("沒改時「存成新版」應停用");
  const row = (name) => [...ed.querySelectorAll("[data-item]")].find(r => visible(r) && text(r).startsWith(name));
  const rt = row("紅茶");
  if (!rt) fail("找不到紅茶");
  const [m, l] = rt.querySelectorAll("input");
  if (!m || !l || m.value !== "30" || l.value !== "35") fail("紅茶應有 M 30／L 35 兩個輸入框");
  if (row("季節茶").querySelector("input")) fail("時價品項不該有輸入框");
  m.value = "32"; m.dispatchEvent(new w.Event("input", { bubbles: true })); await sleep(60);
  if (save.disabled) fail("改了價格應可存");
  if (!m.className.includes("bg-amber-50")) fail("改過的輸入框要變色");
  if (!text(d.getElementById("price-form")).includes("改了 1 項")) fail("應寫「改了 1 項」");
  const payload = JSON.parse(d.querySelector("#price-form input[name=changes_json]").value);
  if (payload.length !== 1 || payload[0].price !== "32" || payload[0].price_l !== "35") fail("送出的資料不對：" + JSON.stringify(payload));
  m.value = "3a"; m.dispatchEvent(new w.Event("input", { bubbles: true })); await sleep(60);
  if (!save.disabled || !text(d.getElementById("price-form")).includes("數字")) fail("填非數字應停用並提示");
  m.value = "32"; m.dispatchEvent(new w.Event("input", { bubbles: true })); await sleep(40);
  const q = ed.querySelector("input[type=search]");
  q.value = "綠"; q.dispatchEvent(new w.Event("input", { bubbles: true })); await sleep(60);
  const shown = [...ed.querySelectorAll("[data-item]")].filter(visible).map(text);
  if (shown.length !== 1 || !shown[0].startsWith("綠茶")) fail("搜尋「綠」應只剩綠茶（" + shown.join("/") + "）");
  q.value = ""; q.dispatchEvent(new w.Event("input", { bubbles: true })); await sleep(60);
  if (!row("紅茶").querySelector("input").className.includes("bg-amber-50")) fail("清掉搜尋後改過的值要還在");
  [...d.querySelectorAll("#price-form button")].find(b => text(b) === "取消").click(); await sleep(80);
  if (visible(ed)) fail("取消後應離開改價模式");
  if (row("紅茶") && row("紅茶").querySelector("input").value !== "30") fail("取消後值要還原");
  d.getElementById("wb-price-edit").click(); await sleep(80);
  if (!visible(ed)) fail("按「改價格」應進改價模式");
  if (jsErrors.length) fail("操作過程有 JS 錯誤：" + jsErrors.join(" | "));
  console.log(JSON.stringify({ ok: true }));
  process.exit(0);
})();
