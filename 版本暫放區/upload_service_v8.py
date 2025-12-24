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
    """上傳圖片到 Cloudinary，回傳 URL"""
    if not file or not file.filename:
        return None
    
    # 檢查是否有設定 Cloudinary
    if not settings.cloudinary_cloud_name:
        print("Cloudinary not configured")
        return None
    
    try:
        content = await file.read()
        
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
        print(f"Cloudinary upload error: {e}")
        return None


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
