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

  if (mode === "catalog_city" || mode === "picker_city") {
    // V2.26.0：只勾彰化縣。甲店彰化（10 天前）、乙店台中（1 天前，收藏）、丙店未設（5 天前）、丁店不分縣市（飲料）
    let readAll;
    if (mode === "picker_city") {
      [...d.querySelectorAll("button")].find(b => b.textContent.includes("餐廳") && (b.getAttribute("@click") || "").includes("selectCategory")).click();
      await sleep(100);
      [...d.querySelectorAll("button")].find(b => b.textContent.includes("點此選擇店家")).click();
      await sleep(150);
      readAll = () => [...d.querySelectorAll("div[role=button] .text-xs.font-medium")].map(e => e.textContent.trim()).filter(n => names.includes(n));
    } else {
      readAll = () => [...d.querySelectorAll("a[href^='/stores/'] .text-xs.font-medium")].map(e => e.textContent.trim()).filter(n => names.includes(n));
    }
    const box = d.getElementById(mode === "picker_city" ? "picker-city-filter" : "city-filter");
    if (!box || !box.textContent.includes("彰化縣")) fail("縣市篩選列應顯示「彰化縣」");
    let got = readAll();
    if (got.includes("乙店")) fail("只勾彰化縣，台中市的乙店不該出現（" + got.join("/") + "）");
    if (!got.includes("甲店") || !got.includes("丙店")) fail("彰化縣的甲店、沒設縣市的丙店都要出現（" + got.join("/") + "）");
    if (mode === "catalog_city") {
      if (!d.body.textContent.includes("丁店")) fail("不分縣市的丁店要出現");
      const m = box.textContent.match(/顯示 (\d+)／共 (\d+) 家/);
      if (!m || Number(m[2]) - Number(m[1]) !== 1) fail("應寫「顯示 N／共 N+1 家」（只藏台中的乙店）（" + box.textContent.replace(/\s+/g, " ") + "）");
    }
    const toggle = [...box.querySelectorAll("button")].find(b => b.textContent.trim() === "看全部");
    if (!toggle) fail("找不到「看全部」");
    toggle.click(); await sleep(80);
    got = readAll();
    if (!got.includes("乙店")) fail("按看全部後乙店要出現（" + got.join("/") + "）");
    if (![...box.querySelectorAll("button")].some(b => b.textContent.trim() === "只看我的縣市")) fail("看全部後按鈕應變「只看我的縣市」");
    // 最新加入：乙（1 天）→ 丙（5 天）→ 甲（10 天）
    if (mode === "picker_city") {
      [...d.querySelectorAll("button")].find(b => b.textContent.replace(/\s+/g, "") === "最新加入").click();
    } else {
      const sel = d.querySelector("select[aria-label=排序]");
      sel.value = "new"; sel.dispatchEvent(new w.Event("change", { bubbles: true }));
    }
    await sleep(80);
    got = readAll();
    const want = mode === "catalog_city" ? ["丙店", "甲店"] : ["乙店", "丙店", "甲店"];  // 店家頁：乙店在收藏區，另外讀
    const rest = mode === "catalog_city" ? got.filter(n => n !== "乙店") : got;
    if (rest.join() !== want.join()) fail("最新加入順序應為 " + want.join("/") + "（" + got.join("/") + "）");
    if (!d.body.textContent.includes("台中市")) fail("看全部時卡片要標縣市");
    if (!/\d\d\/\d\d 加入/.test(d.body.textContent)) fail("最新加入時卡片應顯示「月/日 加入」");
    console.log(JSON.stringify({ ok: true, mode }));
    process.exit(0);
  }

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

    // ---- V2.19.0：選好店 → 截止預設 1 小時後（chip 亮）、團名自動「店名 · 時段」 ----
    const comp = w.Alpine.$data(form);
    const dl = d.querySelector("input[name=deadline]");
    if (!dl.value) fail("選好店後截止應預設填好");
    const dlDate = new Date(dl.value), mins = (dlDate - new Date()) / 60000;
    if (mins < 55 || mins > 61) fail("預設截止應為 1 小時後（實際差 " + Math.round(mins) + " 分）");
    if (comp.deadlinePreset !== "1h") fail("「1 小時後」chip 應亮著（" + comp.deadlinePreset + "）");
    const slot = (h) => h < 10 ? "早餐" : h < 14 ? "午餐" : h < 17 ? "下午茶" : "晚餐";
    for (const [h, want] of [[9, "早餐"], [10, "午餐"], [13, "午餐"], [14, "下午茶"], [16, "下午茶"], [17, "晚餐"]]) {
      if (comp.slotOf(h) !== want) fail(h + " 點應是「" + want + "」（" + comp.slotOf(h) + "）");
    }
    const nameEl = d.querySelector("input[name=name]");
    if (nameEl.value !== "甲店 · " + slot(dlDate.getHours())) fail("團名應自動帶「甲店 · 時段」（" + nameEl.value + "）");
    // 換截止 → 團名跟著換（12:00 必為午餐）
    [...d.querySelectorAll("button")].find(b => /(今天|明天) 12:00/.test(b.textContent.trim())).click(); await sleep(60);
    if (nameEl.value !== "甲店 · 午餐") fail("換成 12:00 截止團名應變「甲店 · 午餐」（" + nameEl.value + "）");
    // 自己改過團名 → 再換截止也不動
    nameEl.value = "我的團"; nameEl.dispatchEvent(new w.Event("input", { bubbles: true })); await sleep(40);
    [...d.querySelectorAll("button")].find(b => /(今天|明天) 17:00/.test(b.textContent.trim())).click(); await sleep(60);
    if (nameEl.value !== "我的團") fail("改過團名後不該再自動換（" + nameEl.value + "）");
    // 進階設定：預設收合、摘要一行；改設定摘要跟著變
    const adv = d.getElementById("advanced");
    if (!adv) fail("找不到進階設定");
    if (comp.advOpen) fail("進階設定預設應收合");
    const summary = () => adv.querySelector("button").textContent.replace(/\s+/g, " ");
    if (!summary().includes("公開 · 無上限 · 無外送費")) fail("進階摘要不對（" + summary() + "）");
    const lim = d.querySelector("input[name=order_limit]"); lim.value = "140"; lim.dispatchEvent(new w.Event("input", { bubbles: true }));
    const dep = d.querySelector("input[name=visibility][value=departments]"); dep.checked = true; dep.dispatchEvent(new w.Event("change", { bubbles: true }));
    await sleep(60);
    if (!summary().includes("限定部門 · 上限 $140") || !summary().includes("湊團")) fail("改設定後摘要應跟著變（" + summary() + "）");
    adv.querySelector("button").click(); await sleep(60);
    if (!comp.advOpen) fail("按進階設定應展開");
    const sub = [...d.querySelectorAll("button[type=submit]")].find(b => b.textContent.trim() === "開團");
    if (!sub || !sub.className.includes("btn-primary")) fail("「開團」應是 .btn-primary 主鈕");
    const fd2 = fd();
    if (fd2.name !== "我的團" || !fd2.deadline || fd2.order_limit !== "140" || fd2.visibility !== "departments") fail("送出的欄位不對 " + JSON.stringify(fd2));
    if ("lucky_draw_count" in fd2) fail("沒開隨機免單卻送出 lucky_draw_count");
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
    // V2.27.0：列不再是整列 <a>；店名是 [data-store-name]，排序收進「篩選」
    if (d.querySelector("a a")) fail("不能有巢狀連結（a 裡面又有 a）");
    const readOrder = () => [...d.querySelectorAll("[data-store-row] [data-store-name]")].map(e => e.textContent.trim()).filter(n => names.includes(n));
    const panel = d.getElementById("filter-panel");
    if (!panel || panel.style.display !== "none") fail("篩選面板預設應收合");
    d.getElementById("filter-toggle").click(); await sleep(60);
    if (panel.style.display === "none") fail("按「篩選」應展開");
    const chips = () => [...panel.querySelectorAll("button")].filter(b => /^(熱門|名稱|最近開團|最新加入)$/.test(b.textContent.trim()));
    if (chips().length !== 4) fail("篩選裡應有四顆排序 chip（" + chips().length + "）");
    let got = readOrder();
    if (got.join() !== expect.hot.join()) fail("預設應依熱門：期望 " + expect.hot.join("/") + "，實際 " + got.join("/"));
    const row = [...d.querySelectorAll("[data-store-row]")].find(e => e.textContent.includes("甲店"));
    if (!row || !row.textContent.includes("開過 5 次")) fail("每列應顯示「開過 N 次」");
    const manage = [...row.querySelectorAll("a")].find(a => a.textContent.trim() === "管理");
    if (!manage || !/^\/admin\/stores\/\d+$/.test(manage.getAttribute("href"))) fail("每列要有獨立的「管理」連結");
    for (const [label, key] of [["名稱", "name"], ["最近開團", "recent"], ["熱門", "hot"]]) {
      chips().find(b => b.textContent.trim() === label).click();
      await sleep(80);
      got = readOrder();
      if (got.join() !== expect[key].join()) fail(label + "：期望 " + expect[key].join("/") + "，實際 " + got.join("/"));
    }
    // 問題標記：甲、乙有菜單（建了 Menu 但沒品項＝0 品項也算沒菜單）→ 只驗切換會篩、再按取消
    const nm = [...d.querySelectorAll("#issue-chips button")].find(b => b.textContent.includes("沒菜單"));
    if (!nm) fail("找不到「沒菜單」標記");
    const before = readOrder().length;
    nm.click(); await sleep(80);
    const rows = [...d.querySelectorAll("[data-store-row]")];
    if (!rows.length || rows.some(r => !r.textContent.includes("沒菜單"))) fail("按「沒菜單」後每列都應是沒菜單的店");
    const fix = [...rows[0].querySelectorAll("a")].find(a => a.textContent.trim() === "沒菜單");
    if (!fix || !fix.getAttribute("href").startsWith("/admin/import?store_id=")) fail("「沒菜單」要能直接點到匯入");
    nm.click(); await sleep(80);
    if (readOrder().length !== before) fail("再按一次應取消篩選");
    let st = {};
    try { st = JSON.parse(w.sessionStorage.getItem("admin_store_list_state") || "{}"); } catch (e) {}
    if (st.sort !== "hot") fail("排序選擇應記在 sessionStorage（" + JSON.stringify(st) + "）");
    console.log(JSON.stringify({ ok: true, mode }));
    process.exit(0);
  }
  fail("未知模式 " + mode);
})();
