#!/usr/bin/env node
/**
 * 店家工作台「共用選項」分頁的實際行為（V2.21.0）
 *
 * 煙霧測試看得到標籤元件拿到哪些初始值、後端怎麼處理 toppings_json，
 * 看不到 Alpine 點了以後「真正會送出的欄位值」。這支把渲染好的工作台載進 jsdom：
 *   甜冰標籤：初始順序 → 新增（含全形逗號拆開、重複不加）→ 往前移 → 移除 → 套預設組 → 隱藏欄位的值跟著變
 *   加料：沒改時儲存停用 → 改名就能存 → 名稱清空／重複會擋 → 新增一列 → 刪除既有列（可復原）→ 往上移 →
 *         toppings_json 的內容與順序 → 送出時有刪除要確認、取消確認就不送
 *   分頁：按「店家設定」切過去、網址 ?tab= 跟著換
 *
 * 用法：node scripts/jsdom_workbench_check.js <html檔>
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
const dom = new JSDOM(html, { runScripts: "dangerously", url: "http://localhost/admin/stores/1?tab=options", pretendToBeVisual: true, virtualConsole: vc });
const w = dom.window;
const confirms = [];
let confirmAnswer = true;
w.confirm = (m) => { confirms.push(m); return confirmAnswer; };
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
const fail = (msg) => { console.log(JSON.stringify({ ok: false, msg })); process.exit(1); };
const visible = (el) => { for (let e = el; e; e = e.parentElement) { if (e.style && e.style.display === "none") return false; } return !!el; };
const text = (el) => (el ? el.textContent.replace(/\s+/g, " ").trim() : "");
const setVal = async (el, v) => { el.value = v; el.dispatchEvent(new w.Event("input", { bubbles: true })); await sleep(30); };

(async () => {
  await sleep(400);
  if (jsErrors.length) fail("頁面初始化有未攔截的 JS 錯誤：" + jsErrors.join(" | "));
  const d = w.document;
  const opts = d.getElementById("tab-options"), sets = d.getElementById("tab-settings");
  if (!visible(opts) || visible(sets)) fail("?tab=options 應只顯示共用選項分頁");

  // ── 甜冰標籤 ──
  const [sugarEd, iceEd] = [...d.querySelectorAll(".tag-editor")];
  if (!sugarEd || !iceEd) fail("找不到甜度／冰塊標籤元件");
  const hidden = (ed) => ed.querySelector("input[type=hidden]").value;
  const chips = (ed) => [...ed.querySelectorAll(".tag-chip")].map(c => text(c.querySelector("span")));
  if (hidden(sugarEd) !== "全糖,半糖" || chips(sugarEd).join() !== "全糖,半糖") fail("甜度初始應為 全糖,半糖（" + hidden(sugarEd) + "）");
  const optForm = d.getElementById("options-form");
  const dirtyNote = [...optForm.querySelectorAll("span")].find(s => text(s) === "有未儲存的變更");
  if (visible(dirtyNote)) fail("甜冰沒改時不該顯示「有未儲存的變更」");
  const sInput = sugarEd.querySelector("input[type=text]");
  const sAdd = [...sugarEd.querySelectorAll("button")].find(b => text(b) === "新增");
  await setVal(sInput, "微糖，半糖, 無糖 "); sAdd.click(); await sleep(50);
  if (hidden(sugarEd) !== "全糖,半糖,微糖,無糖") fail("新增要拆全形逗號、去空白、重複不加（" + hidden(sugarEd) + "）");
  if (sInput.value !== "") fail("新增後輸入框要清空");
  if (!visible(dirtyNote)) fail("改了甜冰應顯示「有未儲存的變更」");
  sugarEd.querySelectorAll(".tag-chip")[2].querySelector("[aria-label='往前']").click(); await sleep(50);
  if (hidden(sugarEd) !== "全糖,微糖,半糖,無糖") fail("往前移應交換順序（" + hidden(sugarEd) + "）");
  if (visible(sugarEd.querySelectorAll(".tag-chip")[0].querySelector("[aria-label='往前']"))) fail("第一個標籤不該有往前");
  sugarEd.querySelectorAll(".tag-chip")[0].querySelector("[aria-label='移除']").click(); await sleep(50);
  if (hidden(sugarEd) !== "微糖,半糖,無糖") fail("移除第一個（" + hidden(sugarEd) + "）");
  const icePreset = [...iceEd.querySelectorAll(".preset-btn")].find(b => text(b) === "含常溫／熱");
  icePreset.click(); await sleep(50);
  if (hidden(iceEd) !== "正常冰,少冰,微冰,去冰,常溫,熱") fail("套預設組應整組取代（" + hidden(iceEd) + "）");
  const fd1 = new w.FormData(optForm);
  if (fd1.get("sugar_options") !== "微糖,半糖,無糖" || fd1.get("ice_options") !== "正常冰,少冰,微冰,去冰,常溫,熱") fail("甜冰表單送出值不對：" + fd1.get("sugar_options") + " / " + fd1.get("ice_options"));

  // ── 加料 ──
  const tf = d.getElementById("toppings-form");
  const save = d.getElementById("toppings-save");
  const rows = () => [...tf.querySelectorAll(".topping-row")];
  const payload = () => JSON.parse(new w.FormData(tf).get("toppings_json"));
  const errEl = () => [...tf.querySelectorAll("span.text-red-600")].find(visible);
  if (rows().length !== 2) fail("加料初始應有 2 列（" + rows().length + "）");
  if (!save.disabled) fail("加料沒改時儲存鈕應停用");
  const p0 = payload();
  if (p0.map(r => r.name).join() !== "珍珠,椰果" || p0[1].active !== false || p0[0].price !== 10) fail("初始 payload 不對：" + JSON.stringify(p0));
  await setVal(rows()[0].querySelector("input[type=text]"), "黑糖珍珠");
  if (save.disabled) fail("改名後儲存鈕應可按");
  await setVal(rows()[0].querySelector("input[type=text]"), "  ");
  if (!save.disabled || !errEl() || !text(errEl()).includes("沒填名稱")) fail("名稱清空要擋並提示");
  await setVal(rows()[0].querySelector("input[type=text]"), "椰果");
  if (!save.disabled || !errEl() || !text(errEl()).includes("重複")) fail("名稱重複要擋並提示");
  await setVal(rows()[0].querySelector("input[type=text]"), "黑糖珍珠");
  [...tf.querySelectorAll("button")].find(b => text(b).includes("新增一項")).click(); await sleep(60);
  if (rows().length !== 3) fail("新增一項後應有 3 列");
  if (!save.disabled) fail("新增的空白列沒填名稱時應停用儲存");
  await setVal(rows()[2].querySelector("input[type=text]"), "仙草");
  await setVal(rows()[2].querySelector("input[type=number]"), "5");
  rows()[2].querySelector("[aria-label='往上']").click(); await sleep(50);
  rows()[2].querySelector("[aria-label='刪除加料']").click(); await sleep(50);  // 刪掉「椰果」（既有）
  const p1 = payload();
  if (JSON.stringify(p1.map(r => [r.id === null ? "new" : "old", r.name, r.price, r.active])) !== JSON.stringify([["old", "黑糖珍珠", 10, true], ["new", "仙草", 5, true]]))
    fail("payload 應為 黑糖珍珠、仙草（新）且椰果移除：" + JSON.stringify(p1));
  const removedChips = [...tf.querySelectorAll("button.line-through")];
  if (removedChips.length !== 1 || text(removedChips[0]) !== "椰果") fail("刪除的既有加料應列在「儲存後刪除」");
  // 送出：有刪除要確認；取消就不送
  confirmAnswer = false;
  let ev = new w.Event("submit", { cancelable: true, bubbles: true }); tf.dispatchEvent(ev); await sleep(30);
  if (!ev.defaultPrevented || confirms.length !== 1 || !confirms[0].includes("刪除 1 項加料")) fail("有刪除時送出要確認、取消就不送（" + confirms.join("|") + "）");
  removedChips[0].click(); await sleep(50);  // 復原椰果
  if (payload().map(r => r.name).join() !== "黑糖珍珠,仙草,椰果") fail("復原後椰果應回到清單最後");
  confirmAnswer = true;
  ev = new w.Event("submit", { cancelable: true, bubbles: true }); tf.dispatchEvent(ev); await sleep(30);
  if (ev.defaultPrevented || confirms.length !== 1) fail("沒有刪除時直接送出、不該再確認");

  // ── 分頁切換 ──
  const tabBtn = [...d.querySelectorAll("button")].find(b => text(b) === "店家資料");
  tabBtn.click(); await sleep(60);
  if (!visible(sets) || visible(opts)) fail("按「店家資料」應切到店家資料分頁");
  if (!w.location.search.includes("tab=settings")) fail("切分頁後網址應更新為 ?tab=settings（" + w.location.search + "）");
  const tabNames = [...d.querySelectorAll("button")].filter(b => b.className.includes("border-b-2")).map(text);
  if (tabNames.join("/") !== "菜單/甜冰加料/店家資料/停用／刪除") fail("分頁應為 菜單/甜冰加料/店家資料/停用／刪除（" + tabNames.join("/") + "）");
  // V2.27.0：頂部摘要可點——縣市 → 店家資料分頁、捲到縣市欄位；甜冰加料 → 甜冰加料分頁
  const summary = d.getElementById("wb-summary");
  if (!summary) fail("找不到店家資料摘要 #wb-summary");
  const sbtn = (kw) => [...summary.querySelectorAll("button")].find(b => text(b).includes(kw));
  // V2.29.0（審稿 P2-B）：摘要只留縣市／分店／可見範圍三顆
  if (summary.querySelectorAll("button").length !== 3) fail("摘要應只有 3 顆（" + summary.querySelectorAll("button").length + "）");
  if (sbtn("甜度") || sbtn("電話")) fail("摘要不該再有甜冰／電話");
  const cityBtn = sbtn("縣市") || sbtn("市") || sbtn("縣");
  if (!cityBtn) fail("摘要應有縣市");
  cityBtn.click(); await sleep(80);
  if (!visible(sets)) fail("按摘要的縣市應切到店家資料分頁");
  if (d.activeElement !== d.querySelector("#store-city select")) fail("按摘要的縣市應聚焦到縣市下拉");
  for (const kw of ["分店", "公開"]) { if (!sbtn(kw)) fail("摘要應有「" + kw + "」"); }
  // V2.29.0（審稿 P1-A）：按摘要切分頁，網址要帶 #欄位；之後點分頁鈕要拿掉 #，tab 參數跟著換
  if (w.location.hash !== "#store-city" || !w.location.search.includes("tab=settings")) fail("按摘要的縣市，網址應是 ?tab=settings#store-city（" + w.location.search + w.location.hash + "）");
  [...d.querySelectorAll("button")].find(b => text(b) === "菜單").click(); await sleep(60);
  if (w.location.hash !== "" || !w.location.search.includes("tab=menu")) fail("點分頁鈕應拿掉 #欄位（" + w.location.search + w.location.hash + "）");
  sbtn("分店").click(); await sleep(60);
  if (w.location.hash !== "#branches") fail("按摘要的分店，網址應帶 #branches（" + w.location.hash + "）");
  // V2.29.0：刪除店家改確認框——按鈕打開、取消關閉、確定送出 confirm=yes
  [...d.querySelectorAll("button")].find(b => text(b).includes("停用／刪除")).click(); await sleep(60);
  const dlg = d.getElementById("del-store-dialog");
  if (!dlg || visible(dlg)) fail("確認框一開始不顯示");
  d.getElementById("del-store-btn").click(); await sleep(60);
  if (!visible(dlg)) fail("按「刪除這家店」應跳出確認框");
  if (!text(dlg).includes("無法復原")) fail("確認框要寫出影響");
  [...dlg.querySelectorAll("button")].find(b => text(b) === "取消").click(); await sleep(60);
  if (visible(dlg)) fail("按取消應關閉確認框");
  const dform = dlg.querySelector("form");
  if (!dform || new w.FormData(dform).get("confirm") !== "yes") fail("確認框的表單要送 confirm=yes");
  if (d.querySelector("input[name=confirm_name]")) fail("不該再要求輸入店名");
  // V2.29.0（審稿 P2-C）：改了沒存就離開要提醒。前面的步驟真的送出過表單（jsdom 不會換頁），先把狀態歸零
  const rootData = w.Alpine.$data(d.querySelector("[x-data*='delOpen']"));
  rootData.leaving = false; rootData.unsaved = false; await sleep(20);
  const ev1 = new w.Event("beforeunload", { cancelable: true });
  w.dispatchEvent(ev1);
  if (ev1.defaultPrevented) fail("沒改東西不該提醒");
  const ph = d.querySelector("#branches input[name=phone]");
  ph.value = "04"; ph.dispatchEvent(new w.Event("input", { bubbles: true })); await sleep(20);
  const ev2 = new w.Event("beforeunload", { cancelable: true });
  w.dispatchEvent(ev2);
  if (!ev2.defaultPrevented) fail("改了沒存就離開應提醒");
  if (jsErrors.length) fail("操作過程有 JS 錯誤：" + jsErrors.join(" | "));
  console.log(JSON.stringify({ ok: true }));
  process.exit(0);
})();
