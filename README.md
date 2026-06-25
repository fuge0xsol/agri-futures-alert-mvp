# AKShare 农产品期货预警 MVP

## 目标

使用 AKShare 作为主数据源，完成：

1. 每个品种获取全部活跃合约
2. 按持仓量 60% + 成交量 40% 评分
3. 只选出主力合约
4. 拉取主力合约日线
5. 生成简单技术状态和 CSV/JSON 输出

## 运行

```bash
cd /home/ubuntu/agri_futures_alert_mvp
uv run python scripts/akshare_agri_mvp.py
```

## 输出

```text
output/main_contracts.csv
output/main_contracts.json
output/latest_bars.csv
output/signals.csv
output/signals.json
output/telegram_message.txt
output/telegram_delta_message.txt
output/summary.txt
```

## 基本面配置

```text
config/fundamental_factors.csv
scripts/update_fundamentals.py
```

`update_fundamentals.py` 会用 AKShare `futures_spot_price_daily` 自动更新现货/基差代理分数，并输出：

```text
output/fundamental_spot_basis_raw.csv
output/fundamental_factors_latest.csv
```

字段：

```text
product_code
fundamental_score    # -100 到 100，默认 0
inventory_bias
supply_bias
demand_bias
macro_bias
note
updated_at
```

当前总分规则：

```text
total_score = 技术分 × 70% + 基本面分 × 30%
```

信号方向现在使用 `total_score`，不是单独使用技术分。

OTC 策略优先使用用户提供的场外期权产品体系：

```text
偏多：累进宝3.0 / 累进宝Plus / 采省易3.0
偏空：惠鑫保1.0 / 惠鑫保2.0 / 凤凰累沽2.0
无信号：暂不匹配
```

每条 OTC 策略推送会同时输出 `策略基本面`：

```text
基本面方向是否支持该策略
供给/需求/库存偏向
为什么适合采购方或库存方
若基本面与策略方向冲突，提示降低名义量或优先保护型结构
```

说明：当前基本面主要来自 AKShare 现货/基差代理，需结合库存、仓单、进口利润和产业订单复核。

## 状态文件

```text
state/contract_state.json   # 主力切换确认状态，连续3次确认
state/signal_state.json     # 信号去重状态
```

定时推送脚本默认发送 `telegram_delta_message.txt`，即只推送新增/变化信号；无变化时只提示“本次无新增或变化信号”。

## Dashboard / GitHub Pages

静态 Dashboard 由以下脚本生成：

```bash
uv run python scripts/build_dashboard.py
```

输出：

```text
docs/index.html
docs/dashboard_data.json
```

`run_and_print_telegram.sh` 已接入 Dashboard 生成，因此每次定时预警都会同步刷新 `docs/index.html`。

如推送到 GitHub Pages：

1. 将项目提交到 GitHub 仓库。
2. 仓库 Settings → Pages → Source 选择 GitHub Actions。
3. 使用 `.github/workflows/pages.yml` 自动构建和部署。
4. GitHub Actions 定时规则为每小时更新一次网页，通常在每小时第 5 分钟触发，实际可能延迟数分钟。

Dashboard 页头会标注：

```text
生成时间：本次网页构建时间，格式为 xxxx年xx月xx日xx时xx分（北京时间）
```

注意：GitHub Pages 是静态网页，本身不能主动推送手机通知；动态提醒继续用 Telegram 定时任务。当前 Telegram 动态提醒也已设置为每小时第 5 分钟运行，网页负责展示最新信号和状态。

## 当前品种

```text
M 豆粕, RM 菜粕, Y 豆油, P 棕榈, OI 菜油, C 玉米,
SR 白糖, CF 棉花, LH 生猪, PK 花生, AP 鲜苹果, JD 鸡蛋
```

## 注意

- AKShare 适合 MVP 与本地试用，不保证生产级稳定性。
- `futures_zh_realtime(symbol="中文品种名")` 用于主力合约识别。
- `futures_zh_daily_sina(symbol="M2609")` 用于具体合约日线。
- 换月确认：连续 3 次排名第一才切换主力。
