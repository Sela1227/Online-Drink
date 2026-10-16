#!/usr/bin/env node
/**
 * 團頁（V2.18.0 重排）的實際行為驗證
 *
 * 煙霧測試看得到模板渲染出什麼，看不到 Alpine／htmx 串起來以後「結帳列有沒有讀到件數與金額」
 * 「已送出後菜單有沒有收合」「更多 sheet 開不開得起來」。這支把 Python 渲染好的團頁載進 jsdom，
 * 載入 htmx 與 Alpine，攔截 XHR（/orders/mine 與 /orders/wall 回 TestClient 產生的真實片段），然後：
 *   member 模式：結帳列讀到「1 件 · $100」→ 按「查看並送出」開購物車 sheet → 導覽列有 常點／熱門／骰子、
 *               按骰子開隨機視窗 → 模擬送出（orderStatus='submitted'）後菜單收合、結帳列變說明、
 *               按「再加點 ›」菜單展開
 *   owner 模式：團主列三顆 → 按「更多」開 sheet、切「匯出」分頁看到點餐彙總 → 按「催單」寫進剪貼簿的文字含「截止」不含「結單」
 *
 * 用法：node scripts/jsdom_group_check.js <html檔> <member|owner> <mine片段html> <wall片段html>
 */
const fs = require("fs");
const [,, htmlPath, mode, minePath, wallPath] = process.argv;
if (!htmlPath || !mode) { console.error("用法：node jsdom_group_check.js <html檔> <member|owner> <mine片段> <wall片段>"); process.exit(2); }
// 片段刻意改成 2 件 $200（整頁渲染的初始值是 1 件 $100）：結帳列若沒真的從片段讀回來，就會卡在初始值
const mineFrag = (minePath ? fs.readFileSync(minePath, "utf-8") : "").replace('data-cart-count="1"', 'data-cart-count="2"').replace('data-cart-total="100"', 'data-cart-total="200"');
const wallFrag = wallPath ? fs.readFileSync(wallPath, "utf-8") : "";
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
    if (u.includes("/orders/mine")) this.responseText = mineFrag;
    else if (u.includes("/orders/wall")) this.responseText = wallFrag;
    else if (u.includes("/fulfillment") || u.includes("/qrcode") || u.includes("/items-panel")) this.responseText = "<div></div>";
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
  if (d.querySelector("nav")) fail("團頁不該有底部導航");

  if (mode === "member") {
    // 1) htmx load 換進購物車片段後，結帳列要讀到件數與金額
    if (!reqs.some(r => r.u.includes("/orders/mine"))) fail("沒有載入 /orders/mine 片段");
    const bar = d.getElementById("checkout-bar");
    if (!bar) fail("找不到結帳列");
    if (comp.cartCount !== 2 || String(comp.cartTotal) !== "200") fail("結帳列沒從片段讀回件數與金額（cartCount=" + comp.cartCount + ", cartTotal=" + comp.cartTotal + "）");
    if (!text(bar).includes("2 件 · $200")) fail("結帳列文字應為「2 件 · $200」（" + text(bar) + "）");
    // 2) 按「查看並送出」開購物車 sheet
    const go = [...bar.querySelectorAll("button")].find(b => b.textContent.includes("查看並送出"));
    if (!go || go.disabled) fail("「查看並送出」不存在或被停用");
    go.click(); await sleep(60);
    if (!comp.showCart) fail("按「查看並送出」後購物車 sheet 沒開");
    comp.showCart = false; await sleep(30);
    // 3) 導覽列：常點／熱門／骰子
    const nav = d.getElementById("menu-nav");
    if (!nav) fail("找不到菜單導覽列");
    const chips = [...nav.querySelectorAll("button")].map(b => text(b));
    if (!chips.some(c => c.includes("常點")) || !chips.some(c => c.includes("熱門"))) fail("導覽列應有 常點／熱門（" + chips.join("/") + "）");
    const dice = [...nav.querySelectorAll("button")].find(b => b.querySelector(".ti-dice"));
    if (!dice) fail("導覽列應有骰子");
    dice.click(); await sleep(60);
    if (!comp.showRandom || !comp.randomResult) fail("按骰子沒開隨機視窗");
    comp.showRandom = false;
    if (d.querySelector("#quick-mine") == null || d.querySelector("#quick-hot") == null) fail("菜單頂部應有 常點／熱門 兩段");
    if ([...d.querySelectorAll("h2")].some(h => text(h).includes("快速點餐"))) fail("「快速點餐」卡應已拿掉");
    // 4) 送出後：菜單收合、結帳列變說明；「再加點」展開
    const collapsed = d.getElementById("menu-collapsed"), section = d.getElementById("menu-section");
    if (!visible(section) || visible(collapsed)) fail("還沒送出時菜單應展開、收合列隱藏");
    comp.orderStatus = "submitted"; await sleep(80);
    if (visible(section) || !visible(collapsed)) fail("送出後菜單應收合成「再加點 ›」");
    if (!text(bar).includes("已送出")) fail("送出後結帳列應變成說明文字（" + text(bar) + "）");
    collapsed.click(); await sleep(60);
    if (!visible(section)) fail("按「再加點 ›」菜單應展開");
    // 5) 訂單牆：一行摘要、展開有跟單鈕
    const wallCard = d.getElementById("order-wall-card");
    if (!wallCard) fail("找不到訂單牆卡");
    const wallBtn = wallCard.querySelector("button");
    wallBtn.click(); await sleep(60);
    if (!wallCard.querySelector("[hx-post*='/orders/follow/']")) fail("訂單牆展開後應有跟單鈕");
    console.log(JSON.stringify({ ok: true, mode }));
    process.exit(0);
  }

  if (mode === "owner") {
    const bar = d.getElementById("owner-bar");
    if (!bar) fail("找不到團主列");
    const btns = [...bar.querySelectorAll("button")].map(b => text(b));
    if (!(btns.some(t => t.includes("分享")) && btns.some(t => t.includes("催單")) && btns.some(t => t.includes("更多")))) fail("團主列應有 分享／催單／更多（" + btns.join("/") + "）");
    // 更多 sheet
    [...bar.querySelectorAll("button")].find(b => text(b).includes("更多")).click(); await sleep(60);
    if (!comp.showMore) fail("按「更多」沒開 sheet");
    const tabs = d.getElementById("more-tabs");
    [...tabs.querySelectorAll("button")].find(b => text(b) === "匯出").click(); await sleep(60);
    if (comp.moreTab !== "export") fail("切「匯出」分頁失敗");
    if (!d.querySelector("a[href$='/export/order']")) fail("匯出分頁應有點餐彙總");
    comp.showMore = false;
    // 催單：剪貼簿文字
    [...bar.querySelectorAll("button")].find(b => text(b).includes("催單")).click(); await sleep(60);
    if (clip.length !== 1) fail("按「催單」應寫一次剪貼簿（" + clip.length + "）");
    if (!clip[0].includes("截止，還沒點的快來點餐") || clip[0].includes("結單") || !clip[0].includes("http://localhost/groups/")) fail("催單文字不對：" + clip[0]);
    // 分享：複製連結
    [...bar.querySelectorAll("button")].find(b => text(b).includes("分享")).click(); await sleep(60);
    if (!comp.showShare) fail("按「分享」沒開 sheet");
    [...d.querySelectorAll("button")].find(b => text(b).includes("複製連結")).click(); await sleep(60);
    if (clip.length !== 2 || !clip[1].startsWith("http://localhost/groups/")) fail("複製連結沒寫剪貼簿");
    // 舊的團主工具 7 格不該在
    if ([...d.querySelectorAll("button")].some(b => text(b) === "團主工具")) fail("團主工具收合列應已拿掉");
    console.log(JSON.stringify({ ok: true, mode }));
    process.exit(0);
  }
  fail("未知模式 " + mode);
})();
