import cloudinary
import cloudinary.uploader
from fastapi import UploadFile
from app.config import get_settings

settings = get_settings()

# 設定 Cloudinary
if settings.cloudinary_cloud_name:
    cloudinary.config(
        cloud_name=settings.cloudinary_cloud_name,
        api_key=settings.cloudinary_api_key,
        api_secret=settings.cloudinary_api_secret,
        secure=True
    )


async def upload_image(file: UploadFile, folder: str = "sela/stores") -> str | None:
    """上傳圖片到 Cloudinary，回傳 URL。
    V2.8.0：格式白名單（JPG/PNG/WebP）＋ 5MB 上限（讀取階段即拒絕），失敗回明確 400。"""
    from fastapi import HTTPException
    
    if not file or not file.filename:
        return None
    
    # 檢查是否有設定 Cloudinary
    if not settings.cloudinary_cloud_name:
        print("Cloudinary not configured")
        return None
    
    _ALLOWED = {"image/jpeg", "image/png", "image/webp"}
    if file.content_type not in _ALLOWED:
        raise HTTPException(status_code=400, detail="圖片僅支援 JPG／PNG／WebP")
    _MAX = 5 * 1024 * 1024
    content = await file.read(_MAX + 1)
    if len(content) > _MAX:
        raise HTTPException(status_code=400, detail="圖片請小於 5MB")
    
    try:
        # 上傳到 Cloudinary
        result = cloudinary.uploader.upload(
            content,
            folder=folder,
            resource_type="image",
            transformation=[
                {"width": 400, "height": 400, "crop": "limit"},
                {"quality": "auto"},
                {"fetch_format": "auto"}
            ]
        )
        return result.get("secure_url")
    except Exception as e:
        print(f"Cloudinary upload failed: {e}")
        raise HTTPException(status_code=400, detail="圖片上傳失敗，請稍後再試")

def delete_image(url: str) -> bool:
    """刪除 Cloudinary 圖片"""
    if not url or "cloudinary" not in url:
        return False
    
    try:
        # 從 URL 取得 public_id
        # URL 格式: https://res.cloudinary.com/{cloud}/image/upload/v123/{folder}/{filename}.jpg
        parts = url.split("/upload/")
        if len(parts) < 2:
            return False
        
        # 取得 public_id（去掉版本號和副檔名）
        path = parts[1]
        if path.startswith("v"):
            path = "/".join(path.split("/")[1:])
        public_id = path.rsplit(".", 1)[0]
        
        cloudinary.uploader.destroy(public_id)
        return True
    except Exception as e:
        print(f"Cloudinary delete error: {e}")
        return False
