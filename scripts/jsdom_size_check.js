#!/usr/bin/env node
/**
 * 點餐彈窗的杯型規格（V2.31.0，Sela 選畫面稿 2）
 *
 * 煙霧測試看得到後端計價、團頁渲染出 sizes 陣列；看不到 Alpine 把它畫成幾顆、選了哪顆、主鈕金額、加料列藏不藏、
 * 送出的表單到底帶什麼 size。這支把真實團頁載進 jsdom：
 *   那堤（中杯／大杯／特大杯）：三顆、預設中杯 $125；點特大杯主鈕變 $155；加燕麥奶 +20 → $175；表單送出 size=特大杯
 *   伯爵茶（只有大杯、不提供加料）：不顯示杯型列、不顯示加料列、主鈕 $95；上一個品項勾的加料要清掉
 *   紅茶（舊菜單 M／L）：兩顆 M $30／L $35
 *   記住上次：選過特大杯 → 再開那堤帶入特大杯；紅茶沒有特大杯就不帶
 *
 * 用法：node scripts/jsdom_size_check.js <團頁html>
 */
const fs = require("fs");
const [,, htmlPath] = process.argv;
const mode = "size";
if (!htmlPath || !mode) { console.error("用法：node jsdom_group_check.js <html檔> <member|owner> <mine片段> <wall片段>"); process.exit(2); }
let JSDOM, VirtualConsole, htmxSrc, alpineSrc;
try {
  ({ JSDOM, VirtualConsole } = require("jsdom"));
  htmxSrc = fs.readFileSync(require.resolve("htmx.org/dist/htmx.min.js"), "utf-8");
  alpineSrc = fs.readFileSync(require.resolve("alpinejs/dist/cdn.min.js"), "utf-8");
} catch (e) { console.log("SKIP 缺套件：" + e.message.split("\n")[0]); process.exit(3); }

const page = fs.readFileSync(htmlPath, "utf-8")
  .replace(/<script[^>]+src=["'][^"']*(?:alpinejs|htmx|tailwindcss)[^"']*["'][^>]*>\s*<\/script>/gi, "")
  .replace(/<link[^>]+>/g, "").replace(/<script>\s*tailwind\.config[\s\S]*?<\/script>/i, "");
const headScripts = (page.slice(0, page.indexOf("<body")).match(/<script>[\s\S]*?<\/script>/g) || []).join("\n");  // window.toast 在 head
const rawBody = page.slice(page.indexOf("<body")).replace(/^<body[^>]*>/, "").replace(/<\/body>\s*<\/html>\s*$/i, "");
// jsdom 沒有 IntersectionObserver（menuNav 的分類高亮用）；給個不做事的替身
const polyfill = `<script>window.IntersectionObserver = class { constructor() {} observe() {} unobserve() {} disconnect() {} };</script>`;
const html = `<html><head>${polyfill}${headScripts}</head><body>${rawBody}<script>document.evaluate = undefined;</script><script>${htmxSrc}</script><script>${alpineSrc}</script></body></html>`;

const vc = new VirtualConsole();
const jsErrors = [];
vc.on("jsdomError", (e) => jsErrors.push(String((e && e.message) || e).split("\n")[0].slice(0, 160)));
const dom = new JSDOM(html, { runScripts: "dangerously", url: "http://localhost/groups/1", pretendToBeVisual: true, virtualConsole: vc });
const w = dom.window;
w.confirm = () => true;
w.scrollTo = () => {};
w.Element.prototype.scrollIntoView = function () {};
const clip = [];
Object.defineProperty(w.navigator, "clipboard", { value: { writeText: (t) => { clip.push(t); return Promise.resolve(); } } });
const reqs = [];
w.XMLHttpRequest = class {
  constructor() { this.readyState = 0; this.status = 200; this.responseText = ""; this.upload = { addEventListener() {}, removeEventListener() {} }; this._l = {}; }
  open(m, u) { this._m = m; this._u = u;
    if (u.includes("/fulfillment") || u.includes("/qrcode") || u.includes("/items-panel")) this.responseText = "<div></div>";
    else this.responseText = "<div></div>";
    this.response = this.responseText; }
  setRequestHeader() {}
  getAllResponseHeaders() { return ""; }
  getResponseHeader() { return null; }
  overrideMimeType() {}
  addEventListener(ev, fn) { this._l[ev] = fn; }
  send() { reqs.push({ m: this._m, u: this._u }); this.readyState = 4; const s = this;
    setTimeout(() => { s.onload && s.onload(); s._l.load && s._l.load(); s.onloadend && s.onloadend(); }, 0); }
  abort() {}
};
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
const fail = (msg) => { console.log(JSON.stringify({ ok: false, mode, msg })); process.exit(1); };
const visible = (el) => !!el && el.style.display !== "none" && !el.closest("[hidden]");
const text = (el) => (el ? el.textContent.replace(/\s+/g, " ").trim() : "");

(async () => {
  await sleep(400);
  if (jsErrors.length) fail("頁面初始化有未攔截的 JS 錯誤：" + jsErrors.join(" | "));
  const d = w.document;
  const root = d.querySelector('[x-data^="orderPage"]');
  if (!root) fail("找不到 orderPage 根元素");
  const comp = w.Alpine.$data(root);
  const btn = (name) => [...d.querySelectorAll("button[data-menu-item-id]")].find(b => text(b).startsWith(name));
  const sheet = d.getElementById("add-item-sheet");
  const picker = d.getElementById("size-picker");
  const tops = d.getElementById("topping-picker");
  const submit = d.getElementById("add-item-submit");
  const chips = () => [...picker.querySelectorAll("input[name=size]")];
  const open = async (name) => { const b = btn(name); if (!b) fail("找不到品項 " + name); b.click(); await sleep(120); };

  await open("那堤");
  if (!comp.showAddItem) fail("按那堤沒開彈窗");
  if (!visible(picker)) fail("那堤應顯示杯型列");
  const labels = chips().map(c => text(c.closest("label")));
  if (labels.join("|") !== "中杯 $125|大杯 $140|特大杯 $155") fail("那堤杯型顆數或文字不對：" + labels.join("|"));
  if (!chips()[0].checked) fail("預設應選第一個杯型（中杯）");
  if (!text(submit).endsWith("$125")) fail("中杯主鈕應 $125（" + text(submit) + "）");
  chips()[2].click(); await sleep(60);
  if (comp.selectedSize !== "特大杯" || !text(submit).endsWith("$155")) fail("點特大杯主鈕應 $155（" + text(submit) + "）");
  if (!tops || !visible(tops)) fail("那堤應顯示加料列");
  const oat = tops.querySelector("input[name=toppings]");
  oat.click(); await sleep(60);
  if (!text(submit).endsWith("$175")) fail("特大杯加燕麥奶應 $175（" + text(submit) + "）");
  const fd = new w.FormData(sheet.querySelector("form"));
  if (fd.get("size") !== "特大杯") fail("表單送出的 size 應是「特大杯」：" + fd.get("size"));
  comp.saveLastPref();
  sheet.querySelector("button[aria-label='關閉']").click(); await sleep(60);

  await open("伯爵茶");
  if (visible(picker)) fail("只有一種杯型不該顯示杯型列");
  if (visible(tops)) fail("不提供加料的品項不該顯示加料列");
  if (oat.checked) fail("上一個品項勾的加料要清掉");
  if (!text(submit).endsWith("$95")) fail("伯爵茶主鈕應 $95（" + text(submit) + "）");
  if (new w.FormData(sheet.querySelector("form")).getAll("size").length) fail("單一規格不該送 size（後端自己帶標籤）");
  sheet.querySelector("button[aria-label='關閉']").click(); await sleep(60);

  await open("紅茶");
  const l2 = chips().map(c => text(c.closest("label")));
  if (l2.join("|") !== "M $30|L $35") fail("舊菜單應是 M／L：" + l2.join("|"));
  if (comp.selectedSize !== "M") fail("紅茶沒有特大杯，不該帶入上次的特大杯（" + comp.selectedSize + "）");
  sheet.querySelector("button[aria-label='關閉']").click(); await sleep(60);

  await open("那堤");
  if (comp.selectedSize !== "特大杯" || !chips()[2].checked) fail("再開那堤應帶入上次的特大杯");
  if (!text(d.getElementById("last-pref-note")).includes("特大杯")) fail("「已帶入上次」應寫特大杯");
  if (jsErrors.length) fail("操作過程有 JS 錯誤：" + jsErrors.join(" | "));
  console.log(JSON.stringify({ ok: true }));
  process.exit(0);
})();
