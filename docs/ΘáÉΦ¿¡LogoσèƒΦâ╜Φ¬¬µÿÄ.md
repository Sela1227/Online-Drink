# 預設 Logo 功能 - 更新說明

## 📦 此次更新內容

### 新增檔案
```
線上訂餐/
├── .gitignore                              # Git 忽略設定
├── app/
│   ├── static/images/defaults/
│   │   ├── default-drink.svg               # 飲料店預設圖示
│   │   ├── default-meal.svg                # 餐廳預設圖示
│   │   └── default-group_buy.svg           # 團購預設圖示
│   └── templates/partials/
│       └── store_logo.html                 # Jinja2 宏
└── docs/
    └── 預設Logo功能說明.md
```

## 🚀 部署方式

解壓縮後直接覆蓋到專案根目錄即可。

## 🔧 使用方式

在需要顯示店家 Logo 的模板中：

```html
{# 1. 在模板開頭引入 #}
{% from "partials/store_logo.html" import store_logo %}

{# 2. 替換原本的 logo 顯示 #}
{{ store_logo(store, size="w-10 h-10") }}
```

### 原本寫法 → 新寫法

```html
<!-- 原本 -->
{% if store.logo_url %}
<img src="{{ store.logo_url }}" class="w-10 h-10 object-contain">
{% endif %}

<!-- 改為 -->
{% from "partials/store_logo.html" import store_logo %}
{{ store_logo(store, size="w-10 h-10") }}
```

## 🎨 預設圖示

| 類別 | 圖示 | 配色 |
|------|------|------|
| 飲料 DRINK | 🧋 飲料杯 | 橘色系 |
| 餐廳 MEAL | 🍽️ 餐盤 | 黃色系 |
| 團購 GROUP_BUY | 🛍️ 購物袋 | 綠色系 |
