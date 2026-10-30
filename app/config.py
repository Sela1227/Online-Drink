from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # App
    app_name: str = "SELA 快點來點餐"
    debug: bool = False
    secret_key: str = "change-me-in-production"
    
    # Database
    database_url: str = "postgresql://postgres:postgres@localhost:5432/groupbuy"
    
    # LINE Login
    line_channel_id: str = ""
    line_channel_secret: str = ""
    line_redirect_uri: str = "http://localhost:8000/auth/callback"
    
    # Admin
    admin_line_user_id: str = ""
    
    # V2.25.0：站內「拍照轉成菜單」（Claude API）。沒設金鑰就不顯示這個功能；
    # 只有 ADMIN_LINE_USER_ID 那位能用（Sela 指定），其他管理員照舊複製指令
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5-5"

    # Base URL (for QR code)
    base_url: str = "http://localhost:8000"
    
    # Cloudinary
    cloudinary_cloud_name: str = ""
    cloudinary_api_key: str = ""
    cloudinary_api_secret: str = ""
    
    class Config:
        env_file = ".env"


@lru_cache()
def get_settings():
    return Settings()
