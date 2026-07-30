#!/bin/sh
# 启动序列：迁移 → seed（由应用 lifespan 幂等执行）→ 服务
# 依据 system-architecture.md 第六节。
set -e

echo "[entrypoint] 等待数据库就绪…"
python - <<'PY'
import time
from sqlalchemy import create_engine, text
from app.config import get_settings

url = get_settings().database_url
for attempt in range(60):
    try:
        create_engine(url, connect_args={"connect_timeout": 2}).connect().execute(text("SELECT 1"))
        print(f"[entrypoint] 数据库就绪（第 {attempt + 1} 次尝试）")
        break
    except Exception:
        time.sleep(1)
else:
    raise SystemExit("[entrypoint] 数据库在 60 秒内未就绪")
PY

echo "[entrypoint] 执行数据库迁移…"
# 迁移在此单点执行，不放进应用 lifespan：多 worker 启动会并发争锁。
alembic upgrade head

echo "[entrypoint] 启动服务…"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers "${UVICORN_WORKERS:-4}"
