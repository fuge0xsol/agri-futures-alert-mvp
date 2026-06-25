#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/ubuntu/agri_futures_alert_mvp"
cd "$ROOT"

if ! /home/ubuntu/.local/bin/uv run python scripts/update_fundamentals.py >/tmp/agri_futures_fundamentals_update.log 2>&1; then
  printf '基本面更新失败，沿用上次 config/fundamental_factors.csv。\n' >/tmp/agri_futures_fundamentals_update_warning.log
fi

/home/ubuntu/.local/bin/uv run python scripts/akshare_agri_mvp.py >/tmp/agri_futures_alert_mvp_run.log
/home/ubuntu/.local/bin/uv run python scripts/build_dashboard.py >/tmp/agri_futures_dashboard_build.log

printf '农产品期货预警\n'
printf '运行时间：'
date '+%Y-%m-%d %H:%M:%S %Z'
printf '\n'
cat "$ROOT/output/telegram_delta_message.txt"
printf '\n输出文件：%s/output\n' "$ROOT"
