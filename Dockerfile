FROM python:3.11-slim

WORKDIR /app

# 安裝系統依賴
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# 複製 requirements 並安裝
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 複製應用程式
COPY . .

# 設定啟動腳本權限
RUN chmod +x start.sh

# 設定環境變數
ENV PYTHONUNBUFFERED=1

# 啟動
CMD ["./start.sh"]
