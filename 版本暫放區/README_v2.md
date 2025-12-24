# SELA Phase 1 剩餘功能實作說明

## 📦 本次新增的功能

| # | 功能 | 說明 |
|---|------|------|
| 1 | 首次登入設定暱稱 | 新用戶首次登入可設定暱稱 |
| 2 | 首頁到期自動刷新 | 團單截止時自動移到已截止區 |
| 3 | 催單功能 | 顯示未結單用戶名單 |
| 4 | 一鍵複製上次訂單 | 快速複製上次在同店家的訂單 |
| 5 | 隨機選擇器 | 不知道喝什麼？隨機抽一個 |
| 6 | 最常點清單 | 個人在該店家的常點品項 |
| 7 | 超夯清單 | 全站熱門品項排行 |
| 8 | 外送費分攤 | 自動計算每人分攤金額 |
| 9 | 問題回報功能 | 用戶提交問題，管理員處理 |

---

## 📁 新增的檔案

```
app/
├── models/
│   └── feedback.py              # 問題回報 Model
├── routers/
│   ├── feedback.py              # 問題回報路由
│   ├── orders_extra.py          # 訂單額外功能（複製、隨機、常點）
│   ├── auth_extra.py            # 首次登入設定
│   └── home_updated.py          # 首頁更新版（超夯清單、自動刷新）
├── services/
│   └── stats_service.py         # 統計服務（常點、熱門）
├── templates/
│   ├── welcome.html             # 首次登入歡迎頁
│   ├── feedback/
│   │   └── list.html            # 問題回報列表
│   ├── admin/
│   │   └── feedbacks.html       # 管理員問題回報頁面
│   └── partials/
│       └── hot_items.html       # 超夯清單區塊
└── static/js/
    └── home-refresh.js          # 首頁自動刷新 JS
```

---

## 🔧 需要修改的現有檔案

### 1. app/models/user.py

加入欄位：
```python
# 首次登入標記
is_first_login: Mapped[bool] = mapped_column(Boolean, default=True)

# LINE 原始名稱
line_display_name: Mapped[str | None] = mapped_column(String(100), nullable=True)

# 用戶回報關聯
feedbacks: Mapped[list["Feedback"]] = relationship(back_populates="user")
```

### 2. app/models/group.py

加入欄位：
```python
# 外送費
delivery_fee: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)

@property
def fee_per_person(self) -> float | None:
    if not self.delivery_fee:
        return None
    if self.submitted_count == 0:
        return self.delivery_fee
    return round(self.delivery_fee / self.submitted_count, 1)
```

### 3. app/models/order.py

加入欄位（如果沒有）：
```python
# OrderItem 加入建立時間
created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```

### 4. app/routers/auth.py

在 callback 函數最後加入：
```python
# 首次登入檢查
if user.is_first_login:
    return RedirectResponse("/auth/welcome", status_code=302)
```

### 5. app/main.py

加入新的 router：
```python
from app.routers import feedback, orders_extra, auth_extra

app.include_router(feedback.router, prefix="/feedback", tags=["feedback"])
app.include_router(orders_extra.router, prefix="/orders", tags=["orders"])
app.include_router(auth_extra.router, prefix="/auth", tags=["auth"])
```

### 6. app/templates/home.html

1. 加入超夯清單區塊：
```html
{% include "partials/hot_items.html" %}
```

2. 包裹團單列表：
```html
<div id="group-list" 
     x-data="homeAutoRefresh('{{ next_deadline.isoformat() if next_deadline else '' }}')">
    {% include "partials/home_groups.html" %}
</div>
```

3. 引入 JS：
```html
<script src="/static/js/home-refresh.js"></script>
```

### 7. app/templates/group.html

1. 加入催單按鈕（團主可見）：
```html
{% if is_owner %}
<button hx-get="/orders/{{ group.id }}/pending-users"
        hx-target="#pending-modal-content"
        @click="$refs.pendingModal.showModal()"
        class="text-orange-600 text-sm">
    ⏰ 催單
</button>

<dialog x-ref="pendingModal" class="modal">
    <div class="modal-box">
        <h3 class="font-bold text-lg mb-4">未結單名單</h3>
        <div id="pending-modal-content"></div>
    </div>
</dialog>
{% endif %}
```

2. 加入快速功能區：
```html
<div class="flex gap-2 mb-4">
    <button hx-post="/orders/{{ group.id }}/copy-last"
            hx-target="#my-cart"
            class="flex-1 bg-blue-50 text-blue-600 py-2 rounded-lg text-sm">
        📋 複製上次
    </button>
    <button hx-get="/orders/{{ group.id }}/random-pick"
            hx-target="#random-result"
            class="flex-1 bg-purple-50 text-purple-600 py-2 rounded-lg text-sm">
        🎲 隨機選
    </button>
</div>
<div id="random-result"></div>
```

3. 加入常點/熱門清單：
```html
<div x-data="{ tab: 'favorites' }" class="mb-4">
    <div class="flex border-b">
        <button @click="tab = 'favorites'" 
                :class="tab === 'favorites' ? 'border-b-2 border-orange-500' : ''"
                class="flex-1 py-2 text-sm">⭐ 我的常點</button>
        <button @click="tab = 'hot'" 
                :class="tab === 'hot' ? 'border-b-2 border-orange-500' : ''"
                class="flex-1 py-2 text-sm">🔥 熱門</button>
    </div>
    <div x-show="tab === 'favorites'" 
         hx-get="/orders/{{ group.id }}/my-favorites" 
         hx-trigger="load"></div>
    <div x-show="tab === 'hot'" 
         hx-get="/orders/{{ group.id }}/hot-items" 
         hx-trigger="load"></div>
</div>
```

4. 加入外送費顯示：
```html
{% if group.delivery_fee %}
<div class="bg-blue-50 rounded-lg p-3 mb-4">
    <div class="flex justify-between">
        <span>🚗 外送費</span>
        <span class="font-medium">${{ group.delivery_fee }}</span>
    </div>
    <div class="text-sm text-gray-500 text-right">
        每人分攤 ${{ group.fee_per_person }}（{{ group.submitted_count }} 人）
    </div>
</div>
{% endif %}
```

### 8. app/templates/group_new.html

加入外送費欄位：
```html
<div class="mb-4">
    <label class="block text-sm font-medium text-gray-700 mb-1">
        外送費（選填）
    </label>
    <div class="relative">
        <span class="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500">$</span>
        <input type="number" name="delivery_fee" 
               class="w-full border rounded-lg pl-8 pr-4 py-2"
               placeholder="0" min="0" step="1">
    </div>
    <p class="text-xs text-gray-400 mt-1">會自動平均分攤給所有結單的人</p>
</div>
```

### 9. app/templates/base.html

在導航列加入問題回報連結：
```html
<a href="/feedback" class="text-gray-600 hover:text-orange-600">
    📝 回報問題
</a>
```

### 10. app/templates/admin/index.html

加入問題回報管理入口：
```html
<a href="/feedback/admin" class="block p-4 bg-white rounded-xl shadow hover:shadow-md">
    <div class="text-2xl mb-2">📋</div>
    <div class="font-medium">問題回報</div>
    <div class="text-sm text-gray-500">查看用戶回報</div>
</a>
```

---

## 🗄️ 資料庫遷移

新增的欄位會由 SQLAlchemy 自動建立：

- `users.is_first_login` - BOOLEAN DEFAULT TRUE
- `users.line_display_name` - VARCHAR(100)
- `groups.delivery_fee` - NUMERIC(10,2)
- `order_items.created_at` - TIMESTAMP
- 新表 `feedbacks`

---

## 🚀 部署步驟

```powershell
cd C:\Users\cbrto\Documents\Python\線上訂餐
# 解壓 sela-phase1-remaining.zip 覆蓋

git add .
git commit -m "Phase 1 complete: nickname, auto-refresh, copy order, random, favorites, hot items, delivery fee, feedback"
git push
```

---

## 📊 Phase 1 完成清單

| # | 功能 | 狀態 |
|---|------|------|
| 49 | 首頁公告區 | ✅ |
| 50 | 團主備註欄 | ✅ |
| 51 | 編輯/取消團 | ✅ |
| - | 轉移團擁有權 | ✅ |
| 53 | 飲料加料系統 | ✅ |
| - | 個人資料頁面 | ✅ |
| - | 管理者查看登入資訊 | ✅ |
| - | 便利貼顯示備註 | ✅ |
| - | 設定→修改 改名 | ✅ |
| - | 關團→提早結單 改名 | ✅ |
| - | 已結單可收合 | ✅ |
| - | 菜單分類導覽 | ✅ |
| - | 便利貼顯示 Logo+訂單統計 | ✅ |
| - | 開團分類選擇 | ✅ |
| **NEW** | 首次登入設定暱稱 | ✅ |
| **NEW** | 首頁到期自動刷新 | ✅ |
| 30 | 催單功能 | ✅ |
| 31 | 一鍵複製上次訂單 | ✅ |
| 47 | 隨機選擇器 | ✅ |
| 9 | 最常點清單 | ✅ |
| 8 | 超夯清單 | ✅ |
| 36 | 外送費分攤 | ✅ |
| 60 | 問題回報功能 | ✅ |

**Phase 1 完成！** 🎉
