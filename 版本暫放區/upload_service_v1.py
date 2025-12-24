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


async def upload_image(file: UploadFile, folder: str = "group-buy") -> str | None:
    """上傳圖片到 Cloudinary，回傳 URL"""
    if not settings.cloudinary_cloud_name:
        return None
    
    try:
        contents = await file.read()
        result = cloudinary.uploader.upload(
            contents,
            folder=folder,
            resource_type="image",
            transformation=[
                {"width": 200, "height": 200, "crop": "fill"},
                {"quality": "auto"},
                {"fetch_format": "auto"}
            ]
        )
        return result.get("secure_url")
    except Exception as e:
        print(f"Cloudinary upload error: {e}")
        return None


def delete_image(public_id: str) -> bool:
    """刪除 Cloudinary 圖片"""
    if not settings.cloudinary_cloud_name:
        return False
    
    try:
        result = cloudinary.uploader.destroy(public_id)
        return result.get("result") == "ok"
    except Exception as e:
        print(f"Cloudinary delete error: {e}")
        return False
