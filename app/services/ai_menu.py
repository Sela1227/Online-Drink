"""V2.25.0：站內「拍照轉成菜單」——菜單照片送 Claude API，回匯入格式的 JSON 文字。

- 誰能用：只有 ADMIN_LINE_USER_ID 那位（Sela 指定「只有我能作」），而且要設 ANTHROPIC_API_KEY。
- 結果只是填進匯入頁的輸入框，照舊走「自動檢查 → 預覽 → 確認」，AI 讀錯的價格擋得下來。
- 照片：自己上傳的在瀏覽器先縮成 JPEG（長邊 1600）；推薦的照片從 Cloudinary 取 JPEG 版本。
"""
import base64
import json

import httpx

from app.config import get_settings
from app.services.menu_prompt import PROMPT_LINES, prompt_tail

MAX_PHOTOS = 5
MAX_BYTES = 5 * 1024 * 1024          # Claude API 單張上限
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
API_URL = "https://api.anthropic.com/v1/messages"


class AIMenuError(Exception):
    """給使用者看的錯誤（中文）"""


def ai_enabled() -> bool:
    s = get_settings()
    return bool(s.anthropic_api_key and s.admin_line_user_id)


def can_use_ai(user) -> bool:
    s = get_settings()
    return bool(ai_enabled() and user is not None and user.line_user_id == s.admin_line_user_id)


def cloudinary_jpg(url: str, width: int = 1600) -> str:
    """Cloudinary 網址插入轉換參數，拿 JPEG、長邊 ≤ width（HEIC 推薦照片也能送）"""
    marker = "/image/upload/"
    if "res.cloudinary.com" in url and marker in url:
        head, tail = url.split(marker, 1)
        return f"{head}{marker}f_jpg,q_85,w_{width},h_{width},c_limit/{tail}"
    return url


async def fetch_images(urls: list[str]) -> list[tuple[bytes, str]]:
    out = []
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
        for u in urls[:MAX_PHOTOS]:
            r = await c.get(cloudinary_jpg(u))
            if r.status_code != 200:
                raise AIMenuError("推薦的菜單照片讀不到（可能已被刪除）")
            ct = r.headers.get("content-type", "image/jpeg").split(";")[0].strip()
            if ct not in ALLOWED_TYPES:
                ct = "image/jpeg"
            out.append((r.content, ct))
    return out


def extract_json_text(reply: str) -> str:
    """AI 回覆 → 排好版的 JSON 文字；解析不了就原樣交給匯入頁（那邊有清理與錯誤定位）"""
    from app.routers.admin import clean_pasted_json
    t = (reply or "").strip()
    for cand in (t, clean_pasted_json(t)[0]):
        try:
            return json.dumps(json.loads(cand), ensure_ascii=False, indent=2)
        except (json.JSONDecodeError, TypeError):
            continue
    return t


async def convert_menu(images: list[tuple[bytes, str]], store_name: str | None = None,
                       existing: bool = False) -> str:
    """照片 → JSON 文字。images：[(bytes, media_type)]"""
    s = get_settings()
    if not images:
        raise AIMenuError("請先加入菜單照片")
    if len(images) > MAX_PHOTOS:
        raise AIMenuError(f"菜單照片最多 {MAX_PHOTOS} 張")
    content = []
    for data, mt in images:
        if len(data) > MAX_BYTES:
            raise AIMenuError("有照片超過 5MB，請重拍或裁小一點")
        content.append({"type": "image", "source": {
            "type": "base64", "media_type": mt, "data": base64.b64encode(data).decode("ascii")}})
    content.append({"type": "text", "text": "\n".join(PROMPT_LINES + prompt_tail(store_name, existing))})
    body = {"model": s.anthropic_model, "max_tokens": 16000,
            "messages": [{"role": "user", "content": content}]}
    headers = {"x-api-key": s.anthropic_api_key, "anthropic-version": "2023-06-01",
               "content-type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=180) as c:
            r = await c.post(API_URL, json=body, headers=headers)
    except httpx.TimeoutException:
        raise AIMenuError("AI 太久沒回應，請再按一次（照片少一點會比較快）")
    except httpx.HTTPError:
        raise AIMenuError("連不上 AI 服務，請稍後再試")
    if r.status_code == 401:
        raise AIMenuError("AI 金鑰無效，請檢查 Railway 的 ANTHROPIC_API_KEY")
    if r.status_code == 429 or r.status_code >= 500:
        raise AIMenuError("AI 服務忙碌中，請過一分鐘再試")
    if r.status_code != 200:
        print(f"AI 轉換失敗 {r.status_code}：{r.text[:300]}")
        raise AIMenuError("AI 轉換失敗，可以改用「複製 AI 轉換指令」手動轉")
    data = r.json()
    text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    if not text.strip():
        raise AIMenuError("AI 沒有回傳內容，請再試一次")
    if data.get("stop_reason") == "max_tokens":
        print("AI 轉換：回覆被截斷（max_tokens）")
    return extract_json_text(text)
