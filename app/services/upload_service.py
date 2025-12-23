import os
import uuid
from fastapi import UploadFile


async def upload_image(file: UploadFile, folder: str = "stores") -> str | None:
    """上傳圖片到本地，回傳 URL"""
    if not file or not file.filename:
        return None
    
    try:
        # 確保目錄存在
        upload_dir = f"app/static/uploads/{folder}"
        os.makedirs(upload_dir, exist_ok=True)
        
        # 產生檔名
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
            ext = '.png'
        filename = f"{uuid.uuid4().hex[:12]}{ext}"
        filepath = os.path.join(upload_dir, filename)
        
        # 儲存檔案
        content = await file.read()
        with open(filepath, "wb") as f:
            f.write(content)
        
        return f"/static/uploads/{folder}/{filename}"
    except Exception as e:
        print(f"Upload error: {e}")
        return None


def delete_image(url: str) -> bool:
    """刪除本地圖片"""
    if not url or not url.startswith("/static/uploads/"):
        return False
    
    try:
        filepath = f"app{url}"
        if os.path.exists(filepath):
            os.remove(filepath)
            return True
        return False
    except Exception as e:
        print(f"Delete error: {e}")
        return False
