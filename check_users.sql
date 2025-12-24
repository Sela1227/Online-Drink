-- SELA 用戶資料檢查腳本
-- 在 Railway 的 Database 頁面執行這些 SQL

-- 1. 檢查所有用戶資料
SELECT 
    id, 
    line_user_id, 
    display_name, 
    is_admin,
    created_at
FROM users 
ORDER BY id;

-- 2. 檢查是否有重複的 line_user_id（應該要是 0）
SELECT 
    line_user_id, 
    COUNT(*) as count,
    STRING_AGG(display_name, ', ') as names
FROM users 
GROUP BY line_user_id 
HAVING COUNT(*) > 1;

-- 3. 檢查是否有重複的 display_name
SELECT 
    display_name, 
    COUNT(*) as count,
    STRING_AGG(CAST(id AS VARCHAR), ', ') as user_ids,
    STRING_AGG(SUBSTRING(line_user_id, 1, 8), ', ') as line_user_ids
FROM users 
GROUP BY display_name 
HAVING COUNT(*) > 1;

-- 4. 檢查特定用戶 A 和 B 的資料（替換 'A的名字' 和 'B的名字'）
SELECT * FROM users WHERE display_name IN ('A的名字', 'B的名字');

-- 5. 檢查最近的訂單（看看誰的訂單顯示在誰名下）
SELECT 
    o.id as order_id,
    o.group_id,
    o.user_id,
    u.display_name as order_owner,
    u.line_user_id,
    o.status,
    o.created_at
FROM orders o
JOIN users u ON o.user_id = u.id
ORDER BY o.created_at DESC
LIMIT 20;

-- 6. 檢查特定團單的所有訂單
-- SELECT * FROM orders WHERE group_id = 替換團單ID;
