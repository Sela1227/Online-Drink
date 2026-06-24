# SELA-logo-prompt.md — 快點來點餐（Online-Drink）

> 由 Claude 依 SELA-Starter-Kit V1.18.0 §17 自動工作流產出。
> 給其他 AI（Midjourney / DALL-E / Adobe Firefly / Gemini 等）生 logo 用。

## 〇、產出資訊（讓 SELA 驗證）

- **專案名稱：** 快點來點餐（GitHub repo：Online-Drink）
- **產出日期：** 2026-05-30
- **使用 Kit 版本：** V1.18.0（§17 自動工作流）
- **使用範本：** A 業務工具型（調性往親和 / 生活感調整）
- **資訊來源：** 從專案 CLAUDE.md 自動萃取

## 一、萃取的設計 context

- **這 app 做什麼：** LINE Login 認證的團體飲料／餐點／團購訂餐系統，讓團隊每日揪團點餐、自動彙總訂單、跟店家核對。
- **給誰用：** 彰濱秀傳特定醫療團隊（約 30 人），每日午餐／飲料揪團的發起人與參與者。
- **解決什麼痛點：** 取代 LINE 群組裡你一句我一句的混亂接龍，自動彙總「誰點了什麼、總共幾份、各付多少」，團主一鍵跟店家核對。
- **情緒基調：** 親和、輕快、日常 —— 是同事間每天會用的小工具，不該嚴肅或企業感，但要清楚可靠（牽涉到收錢對帳）。
- **使用情境：** 每天接近用餐時間打開，快速點餐、看團單、結單、匯出核對單。短時間高頻使用。

## 二、自動決策

### 範本類型

**A 業務工具型**（調性往親和／生活感調整）。本質是團隊每日用的效率工具，但內容是「吃喝揪團」這種有生活溫度的事，所以避免冷冰冰的純工具感，往溫暖親和靠。

### 壁虎 / 蜥蜴傾向

**not a natural fit, but the AI's call。** 訂餐揪團跟「守護 / 跨環境 / 靜默常駐」的壁虎象徵不契合，不強制用壁虎。讓生圖 AI 從「揪團、飲食、彙集」的精神自由發揮更合適的符號（例如杯子、餐點、聚集的點、一起舉杯的意象等，但交給 AI 判斷）。

### 背景色

提案 1-2 個候選：

1. **#653985 北歐低彩度紫（首選）** — 跟 app 主題色完全一致，使用者打開 app 跟看到 logo 是同一個視覺記憶；且紫色跟 SELA 主 logo 的橘色明確區隔，dock／分頁不會跟 SELA 主品牌混淆。
2. **暖橘偏珊瑚（備選）** — 若覺得紫色不夠「食慾感」，可考慮帶暖的橘紅，但要避開 SELA 愛馬仕橘 #F36825 本身（會跟主 logo 撞），用更偏珊瑚／番茄的暖色。

> 建議首選 #653985，跟 app 一致性最高。

## 三、完整 Prompt（複製這段貼到生圖 AI）

```
A flat 2D vector app logo in a 1:1 square aspect ratio.

═══ ABOUT THIS APP (so you can design a fitting symbol) ═══
WHAT IT DOES: A group food-ordering app — a team starts an order, everyone joins
and picks their drinks/meals, and the app auto-tallies who ordered what, how many
of each, and the total, so the organizer can reconcile with the shop in one tap.
WHO USES IT: A ~30-person workplace team, every day around meal time — the person
who starts the group order and the colleagues who join in.
MEANING / SPIRIT: Gathering people together around food; turning a messy chat-thread
of "me too / one more" into one clean, friendly, organized order.
MOOD: warm & approachable, light and everyday, friendly but still clear and reliable
(it handles money and tallying). NOT corporate-stiff, NOT a cold utility.

→ YOU (the AI) decide what visual symbol best represents this app.
  Interpret its spirit — gathering, food, a shared order coming together — and pick
  a symbol a user would instantly recognize. Don't limit yourself to the most literal cup.

═══ FIXED CONSTRAINTS (SELA brand family — always follow) ═══
- 1:1 square, rounded-square frame (corner radius ~15% of edge)
- Flat 2D vector, pure white silhouette for the main subject
- Bold sans-serif app name at bottom, all caps
- Subject occupies top 60-70%, app name bottom 30-40%
- Padding 8-15% between subject and frame edge
- NO gradient, NO shadow, NO 3D, NO glow, NO texture, NO embossing
- Sharp clean edges, must still read at 16x16 favicon size

CONTEXT HINT FOR THIS APP:
- A daily-use team tool, but the subject is food & gathering — keep it warm, not clinical
- Mood leans: friendly, light, everyday — like something colleagues happily open at lunch
- (Let the AI pick the symbol from the app's spirit — don't dictate a literal object)

FRAME FILL COLOR (the rounded square fill; sits on the white background):
- Nordic low-chroma Purple #653985 (preferred — matches the app's own theme color,
  and clearly distinct from SELA's orange main logo)

APP NAME: ORDER  (or leave the AI to letter the app name; Chinese UI name is 快點來點餐)

GECKO MOTIF: a gecko is not a natural fit for a food-ordering app — but if the AI
finds a subtle fitting use, that's the AI's call; don't force it.

═══ BACKGROUND & OUTPUT (important for post-processing) ═══
- Put the logo on a CLEAN SOLID WHITE background — flat pure white (#FFFFFF)
- NO drop shadow under the logo, NO off-white, NO gradient, NO page texture
- (We post-process the white into transparency later — a clean flat white makes that reliable)
- Export as PNG

═══ REFERENCE ═══
Sibling to the SELA brand logo (orange #F36825 rounded square, white gecko + "SELA").
Same design language (flat, rounded square, white foreground), different symbol and color.
```

## 四、拿到圖之後

1. 把生圖 AI 給的 PNG 存下來，回到這個專案對話傳給 Claude。
2. Claude 走 `logo/CLAUDE.md` §10.2 工作流 B：規整比例、白底去背、用 Pillow 生成多解析度套組（16~1024 PNG + favicon.ico + apple-touch-icon），套進 `app/static/favicon/` 與 `app/static/images/`。
3. app logo 取代目前當 favicon 的 SELA logo；SELA 主 logo 降為品牌歸屬印記（依 V1.13.0 雙軌系統）。

## 五、SELA 驗證點（Kit V1.14.1 §17.4 鐵律）

- ✓ 檔案存在於專案根目錄
- ✓ 使用範本：A 業務工具型（往親和調整）
- ✓ 三個自動決策都有寫（範本／壁虎傾向／背景色）
- ✓ 主體交給 AI（沒有寫死「畫一個杯子」）
- ✓ 背景色從 app 主題色 #653985 萃取，附理由
