#!/bin/sh
exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port ${PORT:-8080} \
  --workers 3 \
  --proxy-headers \
  --forwarded-allow-ips="*"
