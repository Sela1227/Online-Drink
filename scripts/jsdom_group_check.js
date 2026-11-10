#!/usr/bin/env node
/**
 * 團頁（V2.18.0 重排）的實際行為驗證
 *
 * 煙霧測試看得到模板渲染出什麼，看不到 Alpine／htmx 串起來以後「結帳列有沒有讀到件數與金額」
 * 「已送出後菜單有沒有收合」「更多 sheet 開不開得起來」。這支把 Python 渲染好的團頁載進 jsdom，
 * 載入 htmx 與 Alpine，攔截 XHR（/orders/mine 與 /orders/wall 回 TestClient 產生的真實片段），然後：
 *   V2.36.0：我的訂單改抽屜（Esc／返回鍵／背景鎖／focus）、已點 ×N、熱門火焰、上限先擋、候補提示在結帳列、加點後只刷新訂單牆
 *   member 模式（V2.33.0 S-2 改寫）：結帳列讀到「你點了 2 件 · $200」、沒有購物車 sheet、我的訂單卡在頁面上 → 導覽列有 常點／熱門／骰子、
 *               按骰子開隨機視窗 → 模擬送出（orderStatus='submitted'）後菜單收合、結帳列變說明、
 *               按「再加點 ›」菜單展開
 *               V2.20.0：加點 sheet 主鈕帶金額、＋ 數量金額加倍、備註收合、✕ 關閉；購物車數量 1 是垃圾桶、⋯ 才有清空
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
  open(m, u) { this._m = m; this._u = u; this.status = 200;
    const ov = w.__xhrOverride && w.__xhrOverride(m, u);  // V2.35.1：測試可指定某個請求回錯誤
    if (ov) { this.status = ov.status; this.responseText = ov.body; this.response = ov.body; return; }
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
    // 1) V2.36.0（G-7）：我的訂單片段在整頁已 include，不再 hx-trigger="load" 重拿；結帳列直接讀到 1 件 $100
    if (reqs.some(r => r.u.includes("/orders/mine"))) fail("G-7：一進頁不該再拿一次 /orders/mine（整頁已經有了）");
    const bar = d.getElementById("checkout-bar");
    if (!bar) fail("找不到結帳列");
    if (comp.cartCount !== 1 || String(comp.cartTotal) !== "100") fail("結帳列沒讀到整頁裡的件數與金額（cartCount=" + comp.cartCount + ", cartTotal=" + comp.cartTotal + "）");
    if (!text(bar).includes("你點了 1 件 · $100") || !text(bar).includes("前都能改")) fail("結帳列應為「你點了 1 件 · $100／已點好 · HH:MM 前都能改」（" + text(bar) + "）");
    if (d.getElementById("cart-content")) fail("不該再有購物車 sheet");
    // 1b) R-5：已點的品項標「已點 ×1」並加框
    const orderedId = Object.keys(comp.orderedQty || {})[0];
    if (!orderedId || comp.orderedQty[orderedId] !== 1) fail("R-5：orderedQty 應從 data-ordered 讀到 1 份（" + JSON.stringify(comp.orderedQty) + "）");
    const itemRow = d.querySelector(`[data-menu-item-id="${orderedId}"]`);
    const badge = itemRow && [...itemRow.querySelectorAll("span")].find(sp => text(sp).startsWith("已點 ×"));
    if (!badge || !visible(badge) || text(badge) !== "已點 ×1") fail("R-5：菜單品項應顯示「已點 ×1」（" + text(badge) + "）");
    // 2) R-2：我的訂單改底部抽屜（G-9：背景不捲、Esc 關、返回鍵關、focus 回按鈕）
    const sheetMine = d.getElementById("mine-sheet");
    if (!sheetMine || visible(sheetMine)) fail("我的訂單抽屜一開始應該關著");
    if (!d.querySelector("#mine-sheet #my-order-display #my-order-card")) fail("我的訂單卡應在抽屜裡");
    if (d.querySelectorAll("#my-order-card").length !== 1) fail("頁面上只該有一張我的訂單卡");
    const goMine = d.getElementById("open-mine");
    if (!goMine || !visible(goMine)) fail("結帳列應有「我的訂單」鈕");
    goMine.focus(); goMine.click(); await sleep(120);
    if (!comp.showMine || !visible(sheetMine)) fail("按「我的訂單」應打開抽屜");
    if (!d.body.classList.contains("overflow-hidden")) fail("G-9：抽屜開著背景不該捲動");
    if (!(w.history.state && w.history.state.sheet)) fail("G-9：打開抽屜要 pushState，返回鍵才會先關抽屜");
    if (!sheetMine.contains(d.activeElement)) fail("G-9：打開抽屜 focus 要進抽屜");
    w.dispatchEvent(new w.KeyboardEvent("keydown", { key: "Escape" })); await sleep(150);
    if (comp.showMine) fail("G-9：按 Esc 應關抽屜");
    if (d.body.classList.contains("overflow-hidden")) fail("G-9：關掉後背景要能捲動");
    if (d.activeElement !== goMine) fail("G-9：關掉後 focus 要回「我的訂單」鈕");
    goMine.click(); await sleep(120);
    if (!comp.showMine) fail("再按應打開抽屜");
    w.history.back(); await sleep(200);
    if (comp.showMine) fail("G-9：按返回鍵應關抽屜、不離開團頁");
    if (w.location.pathname !== "/groups/1") fail("G-9：返回鍵不該離開團頁");
    // 2b) R-1：資訊 sheet
    d.getElementById("info-btn").click(); await sleep(100);
    if (!comp.showInfo || !visible(d.getElementById("info-sheet"))) fail("R-1：按「資訊」應打開團單資訊");
    w.dispatchEvent(new w.KeyboardEvent("keydown", { key: "Escape" })); await sleep(150);
    if (comp.showInfo) fail("R-1：Esc 應關資訊");
    // V2.35.0：菜單照片——菜單上方一排縮圖，點了全螢幕看、左右切、Esc 關
    const strip = d.getElementById("menu-photos-strip");
    if (!strip) fail("菜單上方應有菜單照片縮圖");
    const thumbs = strip.querySelectorAll("button[aria-label^='看菜單照片']");
    if (thumbs.length !== 2) fail("應有 2 張縮圖（" + thumbs.length + "）");
    const viewer = d.getElementById("menu-photo-viewer");
    if (visible(viewer)) fail("看圖一開始應該關著");
    thumbs[1].click(); await sleep(60);
    if (!visible(viewer)) fail("點縮圖應打開看圖");
    const cnt = () => text(viewer).match(/\d+ \/ \d+/)?.[0];
    if (cnt() !== "2 / 2") fail("點第 2 張應顯示 2 / 2（" + cnt() + "）");
    if (!viewer.querySelector("img").getAttribute("src").endsWith("/b.jpg")) fail("應顯示第 2 張圖");
    if (!d.body.classList.contains("overflow-hidden")) fail("看圖時背景不該捲動");
    viewer.querySelector("button[aria-label='下一張']").click(); await sleep(40);
    if (cnt() !== "1 / 2") fail("最後一張再下一張應回到第 1 張（" + cnt() + "）");
    viewer.querySelector("button[aria-label='上一張']").click(); await sleep(40);
    if (cnt() !== "2 / 2") fail("上一張應回到第 2 張（" + cnt() + "）");
    w.dispatchEvent(new w.KeyboardEvent("keydown", { key: "Escape" })); await sleep(60);
    if (visible(viewer)) fail("按 Esc 應關閉看圖");
    if (d.body.classList.contains("overflow-hidden")) fail("關掉後背景要能捲動");
    // 3) 導覽列：分類＋骰子；熱門改成品項上的火焰（R-4），分類不帶數量（R-10）
    const nav = d.getElementById("menu-nav");
    if (!nav) fail("找不到菜單導覽列");
    const chips = [...nav.querySelectorAll("button")].map(b => text(b));
    if (chips.some(c => c.includes("熱門"))) fail("R-4：導覽列不該再有「熱門」（" + chips.join("/") + "）");
    if (chips.some(c => /\d/.test(c))) fail("R-10：分類 chip 不帶數量（" + chips.join("/") + "）");
    const dice = [...nav.querySelectorAll("button")].find(b => b.querySelector(".ti-dice"));
    if (!dice) fail("導覽列應有骰子");
    dice.click(); await sleep(60);
    if (!comp.showRandom || !comp.randomResult) fail("按骰子沒開隨機視窗");
    comp.showRandom = false;
    if (d.querySelector("#quick-hot")) fail("R-4：「大家常點」那段應拿掉");
    if (!d.querySelector("[data-hot] .ti-flame")) fail("R-4：大家常點的品項應有火焰");
    // R-3：開放中訂單牆在菜單下面
    const ms = d.getElementById("menu-section"), ow = d.getElementById("order-wall");
    if (!(ms.compareDocumentPosition(ow) & w.Node.DOCUMENT_POSITION_FOLLOWING)) fail("R-3：訂單牆要在菜單下面");
    if ([...d.querySelectorAll("h2")].some(h => text(h).includes("快速點餐"))) fail("「快速點餐」卡應已拿掉");
    // 3b) V2.20.0 加點 sheet：主鈕帶金額、＋ 數量金額跟著變、＋ 加備註展開、✕ 關閉
    const addBtn = [...d.querySelectorAll("button")].find(b => (b.getAttribute("@click") || "").startsWith("openAddItem("));
    if (!addBtn) fail("找不到可加點的菜單品項");
    addBtn.click(); await sleep(120);
    const sheet = d.getElementById("add-item-sheet");
    if (!comp.showAddItem || !visible(sheet)) fail("按品項後加點 sheet 沒開");
    const submit = d.getElementById("add-item-submit");
    const m1 = text(submit).match(/^點這份・\$(\d+)$/);
    if (!m1 || Number(m1[1]) <= 0) fail("加點主鈕應為「點這份・$金額」（餐點團；" + text(submit) + "）");
    const plus = [...sheet.querySelectorAll("button")].find(b => b.getAttribute("aria-label") === "增加數量");
    if (submit.disabled) fail("R-8：沒超過上限時主鈕不該停用");
    plus.click(); await sleep(60);
    // V2.36.0（R-8）：已點 $100、上限 $250，再點 2 份 $200 → 先擋，不用等後端 400
    if (text(submit) !== "超過上限 $250" || !submit.disabled) fail("R-8：超過上限時主鈕應停用並寫「超過上限 $250」（" + text(submit) + "）");
    sheet.querySelector("button[aria-label='減少數量']")?.click(); await sleep(60);
    if (text(submit) !== "點這份・$" + m1[1] || submit.disabled) fail("R-8：減回 1 份應恢復（" + text(submit) + "）");
    // R-11a：只有一種規格時標題下寫「大杯 $45」
    const keepItem = comp.selectedItem;
    comp.selectedItem = { name: "測", sizes: [{ label: "大杯", price: 45 }], options: [] }; await sleep(40);
    if (comp.sizeSummary() !== "大杯 $45" || !visible(d.getElementById("size-summary"))) fail("R-11：單一規格標題下應寫「大杯 $45」");
    comp.selectedItem = { name: "測", sizes: [{ label: "M", price: 40 }, { label: "L", price: 50 }], options: [] }; await sleep(40);
    if (comp.sizeSummary() !== "") fail("R-11：多規格不寫摘要（有杯型列）");
    comp.selectedItem = keepItem; await sleep(40);
    if ([...sheet.querySelectorAll("button")].some(b => text(b) === "取消")) fail("加點 sheet 底部不該再有「取消」（改右上 ✕）");
    const noteInput = sheet.querySelector("input[name=note]");
    if (visible(noteInput.closest("[x-show]"))) fail("備註應預設收合");
    [...sheet.querySelectorAll("button")].find(b => text(b) === "＋ 加備註").click(); await sleep(60);
    if (!comp.noteOpen || !visible(noteInput.closest("[x-show]"))) fail("按「＋ 加備註」沒展開輸入框");
    sheet.querySelector("button[aria-label='關閉']").click(); await sleep(60);
    if (comp.showAddItem) fail("按 ✕ 沒關掉加點 sheet");
    // 3c) 我的訂單卡（V2.33.0）：數量 1 的「−」是垃圾桶（數量 0）；「全部取消」是小字、直接看得到
    const trash = d.querySelector("#my-order-content button[aria-label='移除品項']");
    if (!trash || !(trash.getAttribute("hx-vals") || "").includes('"quantity": 0')) fail("數量 1 的品項應顯示垃圾桶（hx-vals quantity 0）");
    const clear = d.getElementById("clear-cart");
    if (!clear || !visible(clear) || !text(clear).includes("全部取消")) fail("我的訂單卡應有「全部取消」");
    if ([...d.querySelectorAll("#my-order-content button")].some(b => /送出訂單|修改訂單|取消修改/.test(text(b)))) fail("我的訂單不該再有送出／修改鈕");
    // 4) V2.33.0：點了之後菜單照常展開（要第二杯直接點），沒有「再加點 ›」
    const section = d.getElementById("menu-section");
    if (d.getElementById("menu-collapsed")) fail("不該再有菜單收合列");
    comp.orderStatus = "submitted"; await sleep(80);
    if (!visible(section)) fail("點了之後菜單仍要展開");
    if (!text(bar).includes("你點了")) fail("點了之後結帳列仍報件數金額（" + text(bar) + "）");
    // 5) 訂單牆：一行摘要、展開有跟單鈕
    const wallCard = d.getElementById("order-wall-card");
    if (!wallCard) fail("找不到訂單牆卡");
    const wallBtn = wallCard.querySelector("button");
    wallBtn.click(); await sleep(60);
    if (!wallCard.querySelector("[hx-post*='/orders/follow/']")) fail("訂單牆展開後應有跟單鈕");
    // 6) V2.31.1（內部審核 B-1）：購物車裡的按鈕回應後會被 hx-swap 換掉，按鈕已離開 DOM，
    //    從它身上 $dispatch 的事件傳不到 body——訂單牆、我的訂單、結帳列都不會更新。要從 body 發
    const count = (k) => reqs.filter(r => r.m === "GET" && r.u.includes(k)).length;
    const cartBtn = (pred) => [...d.querySelectorAll("#my-order-content button")].find(pred);
    let w0 = count("/orders/wall"), m0 = count("/orders/mine");
    const plusBtn = cartBtn(b => b.getAttribute("aria-label") === "增加數量");
    if (!plusBtn) fail("購物車找不到 ＋ 鈕");
    plusBtn.click(); await sleep(250);
    if (count("/orders/wall") <= w0 || count("/orders/mine") <= m0) fail("購物車按 ＋ 之後訂單牆與我的訂單沒有重新載入（$dispatch 從被換掉的按鈕發出，傳不到 body）");
    w0 = count("/orders/wall");
    const cancelAll = cartBtn(b => b.id === "clear-cart");
    if (!cancelAll) fail("我的訂單重新載入後找不到「全部取消」");
    cancelAll.click(); await sleep(250);
    if (count("/orders/wall") <= w0) fail("全部取消後訂單牆沒有重新載入（B-1）");
    if (comp.orderStatus !== "none") fail("全部取消後應回到沒點（orderStatus=" + comp.orderStatus + "）");
    // 7) V2.32.0（內部審核 B-5）：打開購物車時先收掉之前的 toast（不然壓在第一個品項的加減鈕上）；剛跳出來的留著
    comp.showAddItem = false; await sleep(60);
    const toastBox = () => [...d.querySelectorAll("[x-show='show']")].find(el => el.textContent.includes("測試提示"));
    w.toast("測試提示"); await sleep(500);
    if (!toastBox() || !visible(toastBox())) fail("toast 應該出現");
    comp.showAddItem = true; await sleep(120);
    if (visible(toastBox())) fail("打開加點 sheet 應收掉之前的 toast（B-5）");
    comp.showAddItem = false; await sleep(60);
    // 實際順序：sheet 一打開就緊接著 toast、緊接著 toast('已設定候補')
    comp.showAddItem = true; w.toast("測試提示"); await sleep(120);
    if (!visible(toastBox())) fail("剛跳出來的 toast 不該被收掉");
    comp.showAddItem = false; await sleep(60);
    // 8) V2.35.1（內部審核 G-1，P0）：加點被後端擋下（400）——彈窗要留著、toast 顯示原因，不能再說「已點好」
    const toastText = () => [...d.querySelectorAll("[x-show='show']")].filter(el => visible(el)).map(el => text(el)).join(" | ");
    // 假片段寫 2 件 $200（上面全部取消後重拿的就是它），再點 $100 會碰到 R-8 的 $250 上限；這裡要測後端擋下，先歸零
    comp.cartTotal = "0";
    addBtn.click(); await sleep(150);
    if (!comp.showAddItem) fail("G-1：再按品項應打開加點 sheet");
    const prefBefore = w.localStorage.getItem(Object.keys(w.localStorage).find(k => k.startsWith("selapref_")) || "_none_");
    w.__xhrOverride = (m, u) => (m === "POST" && u.includes("/orders/items")) ? { status: 400, body: JSON.stringify({ detail: "團單已截止" }) } : null;
    const orderedBefore = comp.orderStatus;
    d.getElementById("add-item-submit").click(); await sleep(400);
    if (!reqs.some(r => r.m === "POST" && r.u.includes("/orders/items"))) fail("G-1：按「點這份」應送出加點請求");
    if (!comp.showAddItem) fail("G-1：加點失敗時彈窗要留著讓人改（被關掉了）");
    if (!toastText().includes("團單已截止")) fail("G-1：失敗要顯示後端原因（toast：" + toastText() + "）");
    if (toastText().includes("已點好")) fail("G-1：失敗不能顯示「已點好」（" + toastText() + "）");
    if (comp.orderStatus !== orderedBefore) fail("G-1：失敗不能把狀態改成已點");
    // 成功照舊：關彈窗、toast 已點好
    w.__xhrOverride = null;
    const wb = count("/orders/wall"), mb = count("/orders/mine");
    d.getElementById("add-item-submit").click(); await sleep(400);
    // V2.36.0（G-7）：加點回應已換進我的訂單，只刷新訂單牆（原本 orderUpdated 會再拿一次我的訂單）
    if (count("/orders/wall") <= wb) fail("G-7：加點成功後訂單牆要刷新");
    if (count("/orders/mine") !== mb) fail("G-7：加點成功後不該再拿一次 /orders/mine");
    if (comp.showAddItem) fail("G-1：成功時彈窗應關閉");
    if (!toastText().includes("已點好")) fail("G-1：成功時應 toast「已點好」（" + toastText() + "）");
    // 8b) V2.36.0（G-4）：候補從抽屜開始 → 關抽屜、結帳列改顯示候補提示、取消回來
    comp.showMine = true; await sleep(100);
    comp.startBackup(1, "雞腿飯", 1, 100); await sleep(150);
    if (comp.showMine) fail("G-4：選候補要關抽屜、回到菜單");
    const bb = d.getElementById("backup-bar");
    if (!bb || !text(bb).includes("選候補 1") || !text(bb).includes("雞腿飯")) fail("G-4：結帳列應顯示「選候補 1：「雞腿飯」…」（" + text(bb) + "）");
    [...bb.querySelectorAll("button")].find(b => text(b) === "取消").click(); await sleep(80);
    if (comp.backupMode || d.getElementById("backup-bar")) fail("G-4：取消後回到一般結帳列");
    // 9) V2.35.1（G-2）：倒數歸零 → 排一次重新整理；同一個團只排一次（手機時鐘比伺服器快時不會一直重整）
    if (typeof w.countdown !== "function") fail("G-2：找不到 countdown()");
    const cd = w.countdown(new Date(Date.now() - 1000).toISOString());
    cd.update();
    if (cd.display !== "已截止" || !cd.isClosed) fail("G-2：歸零應顯示已截止");
    if (!w.__closedReloaded) fail("G-2：歸零應排重新整理");
    const keys = Object.keys(w.sessionStorage).filter(k => k.startsWith("closedReload_"));
    if (keys.length !== 1) fail("G-2：應記下這個團已自動重整過（sessionStorage）");
    w.__closedReloaded = false; cd.update();
    if (w.__closedReloaded) fail("G-2：同一個團重整回來還是歸零時，不能再重整");
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
