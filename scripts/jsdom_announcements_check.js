#!/usr/bin/env node
/**
 * 公告頁原地展開編輯（V2.28.0 內部審核 B-1）
 *
 * 煙霧測試看得到每則公告的 HTML 都在，看不到 Alpine 的展開／收合。這支載進 jsdom 驗：
 *   進頁（帶 ?open=<id>）那則就是展開的；其他收合、只露摘要
 *   點另一則標題 → 換那則展開、原本那則收合；再點一次收合
 *   「新增公告」→ 新增區出現；「取消」收起
 *   字數提示跟著輸入變
 *
 * 用法：node scripts/jsdom_announcements_check.js <html檔> <預先展開的id> <另一則id>
 */
const fs = require("fs");
const [,, htmlPath, openId, otherId] = process.argv;
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
const dom = new JSDOM(html, { runScripts: "dangerously", url: "http://localhost/admin/announcements", pretendToBeVisual: true, virtualConsole: vc });
const w = dom.window;
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
const fail = (msg) => { console.log(JSON.stringify({ ok: false, msg })); process.exit(1); };
const visible = (el) => { for (let e = el; e; e = e.parentElement) { if (e.style && e.style.display === "none") return false; } return !!el; };

(async () => {
  await sleep(120);
  if (jsErrors.length) fail("頁面初始化有未攔截的 JS 錯誤：" + jsErrors.join(" | "));
  const d = w.document;
  const card = (id) => d.getElementById("ann-" + id);
  const formOf = (id) => card(id) && card(id).querySelector("form[action='/admin/announcements/" + id + "']");
  const head = (id) => card(id).querySelector("button[aria-expanded]");
  if (!card(openId) || !card(otherId)) fail("找不到公告卡");
  if (!visible(formOf(openId))) fail("?open= 指定的那則應一進頁就展開");
  if (visible(formOf(otherId))) fail("其他則應收合");
  if (head(openId).getAttribute("aria-expanded") !== "true") fail("展開的那則 aria-expanded 應為 true");
  head(otherId).click(); await sleep(60);
  if (!visible(formOf(otherId)) || visible(formOf(openId))) fail("點另一則應換它展開、原本那則收合");
  head(otherId).click(); await sleep(60);
  if (visible(formOf(otherId))) fail("再點一次應收合");
  const newBox = d.getElementById("ann-new");
  if (visible(newBox)) fail("新增區預設不顯示");
  d.getElementById("ann-new-btn").click(); await sleep(60);
  if (!visible(newBox)) fail("按「新增公告」應出現新增區");
  const ta = newBox.querySelector("textarea[name=content]");
  ta.value = "一二三四五"; ta.dispatchEvent(new w.Event("input", { bubbles: true })); await sleep(40);
  if (!newBox.textContent.replace(/\s+/g, "").includes("5／500字")) fail("字數提示沒跟著變");
  [...newBox.querySelectorAll("button")].find(b => b.textContent.trim() === "取消").click(); await sleep(60);
  if (visible(newBox)) fail("按「取消」應收起新增區");
  console.log(JSON.stringify({ ok: true }));
  process.exit(0);
})();
