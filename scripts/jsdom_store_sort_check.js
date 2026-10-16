#!/usr/bin/env node
/**
 * 店家排序的實際行為驗證 —— V2.16.2
 *
 * 煙霧測試只看得到「資料有傳到模板」，看不到 Alpine 排出來的順序對不對。
 * 這支把 Python 渲染好的頁面載進 jsdom + Alpine，切換排序 chip 後讀卡片／列的順序。
 *
 * 用法：node scripts/jsdom_store_sort_check.js <html檔> <picker|admin|catalog>
 *   catalog：店家分頁 /stores（V2.17.0；乙店已收藏，驗收藏區／只看收藏／排序下拉／分類／搜尋攤平）
 *   picker：開團頁選店覆蓋層（先按「選擇店家」打開覆蓋層，再切排序）
 *   admin ：後台店家列表
 * 店家資料固定三家（由 check_frontend_import.py 建）：
 *   甲店 開過 5 次、上次最舊；乙店 開過 1 次、上次最新；丙店 沒開過
 *   熱門 → 甲乙丙；名稱 → 注音序（丙乙甲 / 甲乙丙 依 localeCompare）；最近 → 乙甲丙
 */
const fs = require("fs");
const [,, htmlPath, mode] = process.argv;
if (!htmlPath || !mode) { console.error("用法：node jsdom_store_sort_check.js <html檔> <picker|admin>"); process.exit(2); }
let JSDOM, VirtualConsole, alpineSrc;
try {
  ({ JSDOM, VirtualConsole } = require("jsdom"));
  alpineSrc = fs.readFileSync(require.resolve("alpinejs/dist/cdn.min.js"), "utf-8");
} catch (e) { console.log("SKIP 缺套件：" + e.message.split("\n")[0]); process.exit(3); }

const page = fs.readFileSync(htmlPath, "utf-8")
  .replace(/<script[^>]+src=["'][^"']*(?:alpinejs|htmx|tailwindcss)[^"']*["'][^>]*>\s*<\/script>/gi, "")
  .replace(/<link[^>]+>/g, "").replace(/<script>\s*tailwind\.config[\s\S]*?<\/script>/i, "");
const rawBody = page.slice(page.indexOf("<body")).replace(/^<body[^>]*>/, "").replace(/<\/body>\s*<\/html>\s*$/i, "");
const html = `<html><head></head><body>${rawBody}<script>${alpineSrc}</script></body></html>`;
const vc = new VirtualConsole();
const jsErrors = [];
vc.on("jsdomError", (e) => jsErrors.push(String((e && e.message) || e).split("\n")[0].slice(0, 160)));
const dom = new JSDOM(html, { runScripts: "dangerously", url: "http://localhost/x", pretendToBeVisual: true, virtualConsole: vc });
const w = dom.window;
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
const fail = (msg) => { console.log(JSON.stringify({ ok: false, mode, msg })); process.exit(1); };
const zh = (a, b) => a.localeCompare(b, "zh-Hant");

(async () => {
  await sleep(100);
  if (jsErrors.length) fail("頁面初始化有未攔截的 JS 錯誤：" + jsErrors.join(" | "));
  const d = w.document;
  const names = ["甲店", "乙店", "丙店"];
  const byName = [...names].sort(zh);
  const expect = { hot: ["甲店", "乙店", "丙店"], name: byName, recent: ["乙店", "甲店", "丙店"] };

  if (mode === "picker") {
    // 選類別（餐廳）→ 按「點此選擇店家」打開覆蓋層
    const catBtn = [...d.querySelectorAll("button")].find(b => b.textContent.includes("餐廳") && (b.getAttribute("@click") || "").includes("selectCategory"));
    if (!catBtn) fail("找不到「餐廳」類別按鈕");
    catBtn.click();
    await sleep(100);
    const open = [...d.querySelectorAll("button")].find(b => b.textContent.includes("點此選擇店家"));
    if (!open) fail("找不到「點此選擇店家」");
    open.click();
    await sleep(150);
    const readOrder = () => [...d.querySelectorAll("div[role=button] .text-xs.font-medium")].map(e => e.textContent.trim()).filter(n => names.includes(n));
    const chips = () => [...d.querySelectorAll("button")].filter(b => /^(熱門|名稱|最近開過)$/.test(b.textContent.replace(/\s+/g, "")));
    if (chips().length !== 3) fail("覆蓋層應有三顆排序 chip（" + chips().length + "）");
    // 預設熱門
    let got = readOrder();
    if (got.join() !== expect.hot.join()) fail("預設應依熱門：期望 " + expect.hot.join("/") + "，實際 " + got.join("/"));
    const meta = [...d.querySelectorAll("div[role=button]")].find(e => e.textContent.includes("甲店"));
    if (!meta || !meta.textContent.includes("開過 5 次")) fail("熱門排序時卡片應顯示「開過 N 次」");
    for (const [label, key] of [["名稱", "name"], ["最近開過", "recent"], ["熱門", "hot"]]) {
      chips().find(b => b.textContent.replace(/\s+/g, "") === label).click();
      await sleep(80);
      got = readOrder();
      if (got.join() !== expect[key].join()) fail(label + "：期望 " + expect[key].join("/") + "，實際 " + got.join("/"));
      if (key === "recent") {
        const m2 = [...d.querySelectorAll("div[role=button]")].find(e => e.textContent.includes("乙店"));
        if (!m2 || !m2.textContent.includes("上次 ")) fail("最近開過排序時卡片應顯示「上次 月/日」");
      }
    }
    let stored = "";
    try { stored = w.localStorage.getItem("sela_store_sort"); } catch (e) {}
    if (stored !== "hot") fail("排序選擇應記在 localStorage（" + stored + "）");

    // ---- V2.16.3 審核 P0-1：沒勾湊團／催單時，藏起來的欄位不能送出 ----
    const form = d.querySelector("form[action='/groups'], form[method=POST], form");
    const fd = () => { const o = {}; new w.FormData(form).forEach((v, k) => { o[k] = v; }); return o; };
    let data = fd();
    if ("min_members" in data || "auto_remind_minutes" in data || "auto_extend" in data) fail("沒勾湊團／催單卻送出了 " + JSON.stringify(Object.keys(data).filter(k => /min_members|auto_remind|auto_extend/.test(k))));
    const minCb = [...d.querySelectorAll("input[type=checkbox]")].find(cb => (cb.getAttribute("@change") || "").includes("enableMinMembers"));
    if (!minCb) fail("找不到湊團勾選框");
    minCb.checked = true; minCb.dispatchEvent(new w.Event("change", { bubbles: true }));
    await sleep(60);
    data = fd();
    if (data.min_members !== "5") fail("勾了湊團後 min_members 應送出 5（" + data.min_members + "）");

    // ---- V2.16.3 審核 P0-2：甜冰預設選項依店家 ----
    // 先選一家餐廳：飲料團設定不該出現
    [...d.querySelectorAll("div[role=button]")].find(e => e.textContent.includes("甲店")).click();
    await sleep(100);
    if (d.querySelector("select[name=default_sugar]")) fail("餐廳不該有預設甜度");
    // 切到飲料、選丁店（有 全糖/半糖 與 去冰）
    [...d.querySelectorAll("button")].find(b => b.textContent.includes("飲料") && (b.getAttribute("@click") || "").includes("selectCategory")).click();
    await sleep(80);
    [...d.querySelectorAll("button")].find(b => b.textContent.includes("點此選擇店家")).click();
    await sleep(120);
    const ding = [...d.querySelectorAll("div[role=button]")].find(e => e.textContent.includes("丁店"));
    if (!ding) fail("覆蓋層找不到丁店");
    ding.click();
    await sleep(120);
    const sel = d.querySelector("select[name=default_sugar]");
    if (!sel) fail("飲料店應有預設甜度");
    const opts = [...sel.options].map(o => o.value);
    if (opts.join() !== ",全糖,半糖") fail("預設甜度選項應來自店家 store_options（" + opts.join("/") + "）");
    const selIce = d.querySelector("select[name=default_ice]");
    if (!selIce || [...selIce.options].map(o => o.value).join() !== ",去冰") fail("預設冰塊選項應來自店家");
    if (/正常糖/.test(d.body.textContent)) fail("不該再有寫死的「正常糖」");

    // ---- V2.16.3 審核 P1-2c：快捷標籤今天／明天 ----
    const lbl = [...d.querySelectorAll("button")].filter(b => /(今天|明天) 1[27]:00/.test(b.textContent.trim()));
    if (lbl.length !== 2) fail("截止快捷應有「今天／明天 12:00」「今天／明天 17:00」兩顆（" + lbl.length + "）");
    const h = new Date().getHours();
    const exp12 = h >= 12 ? "明天 12:00" : "今天 12:00";
    if (!lbl.some(b => b.textContent.trim() === exp12)) fail("12:00 快捷標籤應為「" + exp12 + "」");

    console.log(JSON.stringify({ ok: true, mode }));
    process.exit(0);
  }

  if (mode === "catalog") {
    // V2.17.0 店家分頁：乙店已收藏。預設熱門：收藏區 乙店；全部 甲店→丙店（其餘店家不看）
    const cards = () => [...d.querySelectorAll("a[href^='/stores/']")].filter(a => a.offsetParent !== undefined);
    const readSection = (title) => {
      const sec = [...d.querySelectorAll("section")].find(s => s.textContent.includes(title) && s.style.display !== "none");
      return sec ? [...sec.querySelectorAll("a[href^='/stores/'] .text-xs.font-medium")].map(e => e.textContent.trim()).filter(n => names.includes(n)) : null;
    };
    let fav = readSection("我的收藏"), all = readSection("全部");
    if (!fav || fav.join() !== "乙店") fail("收藏區應只有乙店（" + JSON.stringify(fav) + "）");
    if (!all || all.join() !== "甲店,丙店") fail("預設熱門：全部區應為 甲店/丙店（" + JSON.stringify(all) + "）");
    const card = cards().find(a => a.textContent.includes("甲店"));
    if (!card || !card.textContent.includes("開過 5 次")) fail("熱門時卡片應顯示「開過 N 次」");
    // 只看收藏
    const favBtn = [...d.querySelectorAll("button")].find(b => b.textContent.includes("只看收藏"));
    if (!favBtn) fail("找不到「只看收藏」");
    favBtn.click(); await sleep(80);
    if (readSection("全部") !== null) fail("只看收藏時不該有「全部」區");
    if ((readSection("我的收藏") || []).join() !== "乙店") fail("只看收藏時應只剩乙店");
    favBtn.click(); await sleep(80);
    // 排序下拉：名稱／最近開過
    const sel = d.querySelector("select[aria-label=排序]");
    if (!sel) fail("找不到排序下拉");
    sel.value = "name"; sel.dispatchEvent(new w.Event("change", { bubbles: true })); await sleep(80);
    all = readSection("全部");
    if (all.join() !== ["甲店", "丙店"].sort(zh).join()) fail("名稱排序：期望注音序（" + all.join("/") + "）");
    sel.value = "recent"; sel.dispatchEvent(new w.Event("change", { bubbles: true })); await sleep(80);
    all = readSection("全部");
    if (all.join() !== "甲店,丙店") fail("最近開過：甲店（30 天前）應排在沒開過的丙店前面（" + all.join("/") + "）");
    const c2 = cards().find(a => a.textContent.includes("乙店"));
    if (!c2 || !c2.textContent.includes("上次 ")) fail("最近開過時卡片應顯示「上次 月/日」");
    let stored = "";
    try { stored = w.localStorage.getItem("sela_store_sort"); } catch (e) {}
    if (stored !== "recent") fail("排序選擇應記在 localStorage（" + stored + "）");
    // 分類 chip：飲料 → 只剩丁店
    [...d.querySelectorAll("button")].find(b => b.textContent.trim() === "飲料").click(); await sleep(80);
    const drinkNames = [...d.querySelectorAll("a[href^='/stores/'] .text-xs.font-medium")].map(e => e.textContent.trim());
    if (!drinkNames.includes("丁店") || drinkNames.some(n => names.includes(n))) fail("飲料分類應只剩丁店（" + drinkNames.join("/") + "）");
    [...d.querySelectorAll("button")].find(b => b.textContent.trim() === "全部").click(); await sleep(80);
    // 搜尋：攤平成一列
    const q = d.querySelector("input[type=search]");
    q.value = "甲"; q.dispatchEvent(new w.Event("input", { bubbles: true })); await sleep(80);
    if (readSection("全部") !== null) fail("搜尋時不該再分區");
    const hits = [...d.querySelectorAll("a[href^='/stores/'] .text-xs.font-medium")].map(e => e.textContent.trim());
    if (hits.join() !== "甲店") fail("搜尋「甲」應只剩甲店（" + hits.join("/") + "）");
    q.value = "沒這家"; q.dispatchEvent(new w.Event("input", { bubbles: true })); await sleep(80);
    if (!d.body.textContent.includes("找不到「沒這家」")) fail("搜尋無結果應有提示");
    console.log(JSON.stringify({ ok: true, mode }));
    process.exit(0);
  }

  if (mode === "admin") {
    const readOrder = () => [...d.querySelectorAll("a[href^='/admin/stores/'] .font-medium")].map(e => e.textContent.trim()).filter(n => names.includes(n));
    const chips = () => [...d.querySelectorAll("button")].filter(b => /^(熱門|名稱|最近開團)$/.test(b.textContent.trim()));
    if (chips().length !== 3) fail("後台列表應有三顆排序 chip（" + chips().length + "）");
    let got = readOrder();
    if (got.join() !== expect.hot.join()) fail("預設應依熱門：期望 " + expect.hot.join("/") + "，實際 " + got.join("/"));
    const row = [...d.querySelectorAll("a[href^='/admin/stores/']")].find(e => e.textContent.includes("甲店"));
    if (!row || !row.textContent.includes("開過 5 次")) fail("每列應顯示「開過 N 次」");
    for (const [label, key] of [["名稱", "name"], ["最近開團", "recent"], ["熱門", "hot"]]) {
      chips().find(b => b.textContent.trim() === label).click();
      await sleep(80);
      got = readOrder();
      if (got.join() !== expect[key].join()) fail(label + "：期望 " + expect[key].join("/") + "，實際 " + got.join("/"));
    }
    let st = {};
    try { st = JSON.parse(w.sessionStorage.getItem("admin_store_list_state") || "{}"); } catch (e) {}
    if (st.sort !== "hot") fail("排序選擇應記在 sessionStorage（" + JSON.stringify(st) + "）");
    console.log(JSON.stringify({ ok: true, mode }));
    process.exit(0);
  }
  fail("未知模式 " + mode);
})();
