#!/usr/bin/env node
/**
 * 匯入頁「貼上就自動檢查」的實際行為驗證 —— V2.15.0
 *
 * 後端測試看得到片段內容，看不到「貼上後 htmx 會不會真的發請求」。這支把 Python 渲染好的
 * 匯入頁載進 jsdom，載入 htmx 與 Alpine，攔截 XHR，然後：
 *   1. 貼上文字 → 0.7 秒後應發一次 POST /admin/import/preview
 *   2. 清空 → 不發
 *   3. 拖一個帶 BOM 的檔案進輸入框 → 讀入、去 BOM、自動檢查
 *   4. 回傳的片段要換進 #import-result
 *   5.（沒選店家的頁面）換店家下拉 → 重新檢查
 *
 * V2.15.0 開發時 jsdom 抓到兩個真問題：`changed` 修飾在 form 上永遠不觸發（它比對的是 form.value）；
 * `from:find select` 找不到元素時 htmx 直接拋錯。兩者都改掉了。
 *
 * 用法：node scripts/jsdom_import_check.js <html檔> <store|nostore>
 * 需要 node_modules 的 jsdom、alpinejs、htmx.org（或 NODE_PATH）。
 */
const fs = require("fs");
const [,, htmlPath, mode, fragPath, similarFragPath] = process.argv;
if (!htmlPath || !mode) { console.error("用法：node jsdom_import_check.js <html檔> <store|nostore> [預覽片段html]"); process.exit(2); }
// V2.15.1 審核 P1-1：預覽的假回應改用真實片段（TestClient 產生），才測得到確認鈕
const fragment = fragPath ? fs.readFileSync(fragPath, "utf-8") : "<div id='frag'>ok</div>";
// V2.16.1 B-8：「新增一家店」但店名近似的真實片段（含「改為更新」按鈕）
const similarFragment = similarFragPath ? fs.readFileSync(similarFragPath, "utf-8") : "";
let JSDOM, VirtualConsole, htmxSrc, alpineSrc;
try {
  ({ JSDOM, VirtualConsole } = require("jsdom"));
  htmxSrc = fs.readFileSync(require.resolve("htmx.org/dist/htmx.min.js"), "utf-8");
  alpineSrc = fs.readFileSync(require.resolve("alpinejs/dist/cdn.min.js"), "utf-8");
} catch (e) { console.log("SKIP 缺套件：" + e.message.split("\n")[0]); process.exit(3); }

const page = fs.readFileSync(htmlPath, "utf-8")
  .replace(/<script[^>]+src=["'][^"']*(?:alpinejs|htmx|tailwindcss)[^"']*["'][^>]*>\s*<\/script>/gi, "")
  .replace(/<link[^>]+>/g, "").replace(/<script>\s*tailwind\.config[\s\S]*?<\/script>/i, "");
// 只取 body 內容重組（整份文件直接餵 jsdom 時 Alpine 的魔法變數會失效，原因未查明；body 重組就正常）
const rawBody = page.slice(page.indexOf("<body")).replace(/^<body[^>]*>/, "").replace(/<\/body>\s*<\/html>\s*$/i, "");
// document.evaluate：jsdom 的實作與 htmx 掃 hx-on 的 XPath 呼叫不合，關掉讓 htmx 走 fallback
const html = `<html><head></head><body>${rawBody}<script>document.evaluate = undefined;</script><script>${htmxSrc}</script><script>${alpineSrc}</script></body></html>`;

const vc = new VirtualConsole();
const jsErrors = [];
vc.on("jsdomError", (e) => jsErrors.push(String((e && e.message) || e).split("\n")[0].slice(0, 160)));
const dom = new JSDOM(html, { runScripts: "dangerously", url: "http://localhost/admin/import", pretendToBeVisual: true, virtualConsole: vc });
const w = dom.window;
// jsdom 沒有 createObjectURL；B-3 對照照片只需要一個字串
w.URL.createObjectURL = () => "blob:local/photo"; w.URL.revokeObjectURL = () => {};
w.confirm = () => true;
const posts = [];
w.XMLHttpRequest = class {
  constructor() { this.readyState = 0; this.status = 200; this.responseText = fragment; this.response = this.responseText; this.upload = { addEventListener() {}, removeEventListener() {} }; this._l = {}; }
  open(m, u) { this._m = m; this._u = u;
    if (u.endsWith("/admin/import")) { this.responseText = "<div id='imported'>done</div>"; }
    // V2.16.1 B-5：帶入目前菜單的 JSON 端點
    if (u.includes("/menu-json")) { this.responseText = JSON.stringify({ version: 1, items: 1, text: '{\n  "menu": {"categories": [{"name": "主食", "items": [{"name": "雞腿飯", "price": 100}]}]}\n}' }); }
    this.response = this.responseText; }
  setRequestHeader() {}
  getAllResponseHeaders() { return ""; }
  getResponseHeader() { return null; }
  overrideMimeType() {}
  addEventListener(ev, fn) { this._l[ev] = fn; }
  send(body) { posts.push({ m: this._m, u: this._u }); this.readyState = 4; const s = this;
    setTimeout(() => { s.onload && s.onload(); s._l.load && s._l.load(); s.onloadend && s.onloadend(); }, 0); }
  abort() {}
};
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
const fail = (msg) => { console.log(JSON.stringify({ ok: false, mode, msg, posts: posts.length })); process.exit(1); };

(async () => {
  await sleep(80);
  if (jsErrors.length) fail("頁面初始化有未攔截的 JS 錯誤：" + jsErrors.join(" | "));
  const ta = w.document.querySelector("textarea[name=json_text]");
  if (!ta) fail("找不到 textarea[name=json_text]");
  const form = ta.closest("form");
  ta.value = '{"menu": {}}';
  ta.dispatchEvent(new w.Event("input", { bubbles: true }));
  await sleep(1000);
  if (posts.length !== 1 || !posts[0].u.endsWith("/admin/import/preview")) fail("貼上後沒有自動檢查（或打錯端點）");
  if (!w.document.querySelector("#import-result").innerHTML.trim()) fail("片段沒換進 #import-result");
  if (fragPath) {
    // 確認鈕要能送 POST /admin/import
    let btn = w.document.querySelector("#import-result form button[type=submit]");
    if (!btn) fail("真實片段裡找不到確認鈕");
    if (btn.closest("form").closest("form") !== btn.closest("form")) fail("確認表單不該是巢狀 form");
    if (btn.disabled) fail("確認鈕一開始不該停用");
    btn.click();
    await sleep(300);
    const confirmPosts = posts.filter(p => p.u.endsWith("/admin/import"));
    if (confirmPosts.length !== 1) fail("按確認沒有送 POST /admin/import（" + confirmPosts.length + "）");
    // 重新放回片段（上一步已被換成完成訊息），再改內容後立刻按確認 → 不應送出（P1-1）
    w.document.getElementById("import-result").innerHTML = fragment;
    await sleep(50);
    ta.value = '{"menu": {"categories": [{"name": "主食", "items": [{"name": "雞腿飯", "price": 120}]}]}}';
    ta.dispatchEvent(new w.Event("input", { bubbles: true }));
    await sleep(20);
    btn = w.document.querySelector("#import-result form button[type=submit]");
    if (!btn || !btn.disabled) fail("改內容後舊的確認鈕應立即停用");
    btn.click();
    await sleep(200);
    if (posts.filter(p => p.u.endsWith("/admin/import")).length !== 1) fail("改內容後 100ms 內按確認仍送出了舊內容（P1-1）");
    await sleep(1000);  // 等自動重新檢查換進新片段
    const nb = w.document.querySelector("#import-result form button[type=submit]");
    if (!nb || nb.disabled) fail("重新檢查後確認鈕應恢復");
  }
  // 拖文字（P3-4）
  {
    const n0 = posts.length;
    const ev = new w.Event("drop", { bubbles: true, cancelable: true }); ev.dataTransfer = { files: [], getData: () => '{"menu": {"items": [{"name": "拖進來的", "price": 1}]}}' };
    ta.dispatchEvent(ev);
    await sleep(1000);
    if (!ta.value.includes("拖進來的")) fail("拖文字沒有讀進輸入框");
    if (posts.length !== n0 + 1) fail("拖文字後沒有自動檢查");
  }
  const nClear = posts.length;
  ta.value = "";
  ta.dispatchEvent(new w.Event("input", { bubbles: true }));
  await sleep(1000);
  if (posts.length !== nClear) fail("清空後仍發送");
  if (w.document.getElementById("import-result").innerHTML.trim()) fail("清空後結果區應清空");
  const n = posts.length;
  const file = new w.File(['﻿{"menu": {"items": []}}'], "menu.json", { type: "application/json" });
  const ev = new w.Event("drop", { bubbles: true, cancelable: true }); ev.dataTransfer = { files: [file] };
  ta.dispatchEvent(ev);
  await sleep(1500);
  if (posts.length < n + 1) fail("拖檔後沒有自動檢查");
  if (ta.value.charCodeAt(0) === 0xFEFF) fail("拖檔的 BOM 沒去掉");
  // V2.16.1 B-3：拖圖片進輸入框 → 當對照照片，不碰輸入框內容
  {
    const before = ta.value; const n0 = posts.length;
    const img = new w.File(["x"], "menu.jpg", { type: "image/jpeg" });
    const ev = new w.Event("drop", { bubbles: true, cancelable: true }); ev.dataTransfer = { files: [img], getData: () => "" };
    ta.dispatchEvent(ev);
    await sleep(100);
    const pic = w.document.querySelector("img[alt=菜單照片]");
    if (!pic || pic.getAttribute("src") !== "blob:local/photo") fail("拖圖片進來應顯示對照照片");
    if (ta.value !== before) fail("拖圖片不該改到輸入框");
    if (posts.length !== n0) fail("拖圖片不該觸發檢查");
    if (pic.closest("[x-show]") && pic.closest("[x-show]").style.display === "none") fail("照片區應展開");
  }
  if (mode === "nostore") {
    if (form.querySelector("select")) fail("V2.16.1 起沒選店家的頁面也不該有原生下拉（改搜尋）");
    const q = form.querySelector("input[x-ref=storeQuery]");
    if (!q) fail("沒選店家的頁面應有搜尋店名的輸入框");
    const hidden = form.querySelector("input[name=store_id]");
    if (!hidden || hidden.value !== "") fail("一開始 store_id 應為空（新增一家店）");
    q.focus(); q.value = "檢查"; q.dispatchEvent(new w.Event("input", { bubbles: true }));
    await sleep(100);
    const opts = [...form.querySelectorAll("button")].filter(b => b.textContent.includes("檢查店"));
    if (opts.length !== 1) fail("輸入「檢查」應只列出「檢查店」一家（" + opts.length + "）");
    const m = posts.length;
    opts[0].click();
    await sleep(1000);
    if (hidden.value === "") fail("選了店家後 store_id 應有值");
    if (posts.length !== m + 1) fail("換店家沒有重新檢查");
    // B-5：帶入目前菜單
    const loadBtn = [...form.querySelectorAll("button")].find(b => b.textContent.includes("帶入目前菜單"));
    if (!loadBtn) fail("選了店家後應出現「帶入目前菜單」");
    const m2 = posts.length;
    loadBtn.click();
    await sleep(1000);
    if (!posts.some(p => p.u.includes("/menu-json"))) fail("帶入目前菜單沒有去拿 menu-json");
    if (!ta.value.includes("雞腿飯")) fail("帶入的菜單沒有進輸入框");
    if (posts.filter(p => p.u.endsWith("/admin/import/preview")).length <= m2 - 1) fail("帶入後沒有自動檢查");
    // B-8：近似店名片段 → 「改為更新」會切店家並重查；「確定是新店家」會收起提醒
    if (similarFragment) {
      // 先回到「新增一家店」
      [...form.querySelectorAll("button")].find(b => b.textContent.trim() === "更換").click();
      await sleep(50);
      if (hidden.value !== "") fail("按更換後 store_id 應清空");
      w.document.getElementById("import-result").innerHTML = similarFragment;
      await sleep(80);
      const sw = [...w.document.querySelectorAll("#import-result button")].find(b => b.textContent.includes("改為更新"));
      if (!sw) fail("近似店名片段裡找不到「改為更新」");
      const m3 = posts.length;
      sw.click();
      await sleep(1000);
      if (hidden.value === "") fail("按「改為更新」後 store_id 應被切到那家店");
      if (!posts.slice(m3).some(p => p.u.endsWith("/admin/import/preview"))) fail("切店家後沒有重新檢查");
      // 再放一次片段，按「確定是新店家」應收起
      w.document.getElementById("import-result").innerHTML = similarFragment;
      await sleep(80);
      const dismiss = [...w.document.querySelectorAll("#import-result button")].find(b => b.textContent.includes("確定是新店家"));
      if (!dismiss) fail("找不到「確定是新店家」");
      const banner = dismiss.closest("[x-show]");
      dismiss.click();
      await sleep(80);
      if (!banner || banner.style.display !== "none") fail("按「確定是新店家」後提醒應收起");
    }
  } else {
    if (form.querySelector("select")) fail("選定店家的頁面不該有下拉");
    const loadBtn = [...form.querySelectorAll("button")].find(b => b.textContent.includes("帶入目前菜單"));
    if (!loadBtn) fail("選定店家的頁面應有「帶入目前菜單」");
    const copyBtns = [...form.querySelectorAll("button")].filter(b => b.textContent.includes("AI 轉換指令"));
    if (copyBtns.length !== 1) fail("V2.16.1 起只該有一顆「複製 AI 轉換指令」");
  }
  console.log(JSON.stringify({ ok: true, mode, posts: posts.length }));
  process.exit(0);
})();
