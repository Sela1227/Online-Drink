"""
外送費分攤功能

=== 資料庫修改 ===

在 app/models/group.py 的 Group class 中加入：

    # 外送費（選填）
    delivery_fee: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True, default=None)
    
    @property
    def fee_per_person(self) -> float | None:
        \"\"\"每人分攤的外送費\"\"\"
        if not self.delivery_fee:
            return None
        submitted_count = self.submitted_count
        if submitted_count == 0:
            return self.delivery_fee
        return round(self.delivery_fee / submitted_count, 1)


=== 開團頁面修改 ===

在 group_new.html 加入：

<div class="mb-4">
    <label class="block text-sm font-medium text-gray-700 mb-1">
        外送費（選填）
    </label>
    <div class="relative">
        <span class="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500">$</span>
        <input type="number" name="delivery_fee" 
               class="w-full border rounded-lg pl-8 pr-4 py-2"
               placeholder="0"
               min="0" step="1">
    </div>
    <p class="text-xs text-gray-400 mt-1">會自動平均分攤給所有結單的人</p>
</div>


=== 團單頁面顯示 ===

在 group.html 加入（在總金額附近）：

{% if group.delivery_fee %}
<div class="flex justify-between text-sm text-gray-600 mb-2">
    <span>🚗 外送費</span>
    <span>${{ group.delivery_fee }} （每人 ${{ group.fee_per_person }}）</span>
</div>
{% endif %}


=== 個人明細顯示 ===

{% if group.delivery_fee %}
<div class="text-sm text-gray-500">
    + 外送費分攤 ${{ group.fee_per_person }}
</div>
{% endif %}


=== 匯出文字修改 ===

在 export_service.py 的收款文字中加入：

if group.delivery_fee and group.submitted_count > 0:
    fee_per_person = round(group.delivery_fee / group.submitted_count, 1)
    text += f"\\n🚗 外送費：${group.delivery_fee}（每人 ${fee_per_person}）"
    
# 計算每人總額時也要加上外送費
for order in orders:
    order_total = sum(item.total_price for item in order.items)
    if group.delivery_fee:
        order_total += fee_per_person
    text += f"\\n{order.user.display_name}：${order_total}"
"""

# 這個檔案只是說明文件，實際修改需要套用到對應的檔案中
