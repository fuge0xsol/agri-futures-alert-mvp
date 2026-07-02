#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/ubuntu/agri_futures_alert_mvp"
cd "$ROOT"

if ! /home/ubuntu/.local/bin/uv run python scripts/update_fundamentals.py >/tmp/agri_futures_fundamentals_update.log 2>&1; then
  printf '基本面更新失败，沿用上次 config/fundamental_factors.csv。\n' >/tmp/agri_futures_fundamentals_update_warning.log
fi

/home/ubuntu/.local/bin/uv run python scripts/akshare_agri_mvp.py >/tmp/agri_futures_alert_mvp_run.log
/home/ubuntu/.local/bin/uv run python scripts/build_dashboard.py >/tmp/agri_futures_dashboard_build.log

# Publish refreshed dashboard to GitHub Pages.
# Only commit generated dashboard/runtime data files and this script; keep large videos and local state out of git.
PUBLISH_STATUS="网页数据无变化，未提交。"
if ! git diff --quiet -- docs/index.html docs/dashboard_data.json config/fundamental_factors.csv scripts/run_and_print_telegram.sh; then
  git add docs/index.html docs/dashboard_data.json config/fundamental_factors.csv scripts/run_and_print_telegram.sh
  git commit -m "Update dashboard data $(date '+%Y-%m-%d %H:%M')" >/tmp/agri_futures_git_commit.log 2>&1
  PUBLISH_STATUS="网页数据已本地提交。"
fi

AHEAD_COUNT=$(git rev-list --count origin/main..HEAD 2>/dev/null || printf '0')
if [ "$AHEAD_COUNT" != "0" ]; then
  if git push origin main >/tmp/agri_futures_git_push.log 2>&1; then
    PUBLISH_STATUS="网页已推送到 GitHub Pages。"
  else
    PUBLISH_STATUS="网页本地已更新，但 GitHub 推送失败：缺少/失效的 GitHub 凭证。"
  fi
fi

printf '农产品期货预警\n'
printf '运行时间：'
date '+%Y-%m-%d %H:%M:%S %Z'
printf '%s\n' "$PUBLISH_STATUS"
printf '\n'
cat "$ROOT/output/telegram_delta_message.txt"
printf '\n输出文件：%s/output\n' "$ROOT"
