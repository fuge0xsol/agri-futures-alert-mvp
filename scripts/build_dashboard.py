#!/usr/bin/env python3
"""Build a static GitHub Pages dashboard from MVP output files."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
DOCS = ROOT / "docs"
STATE = ROOT / "state"
DASHBOARD_STATE = STATE / "dashboard_state.json"
BEIJING_TZ = ZoneInfo("Asia/Shanghai")


def load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def format_beijing_time(dt: datetime) -> str:
    return dt.astimezone(BEIJING_TZ).strftime("%Y年%m月%d日%H时%M分")


def parse_dashboard_time(value: str) -> datetime | None:
    if not value:
        return None
    for parser in (
        lambda s: datetime.fromisoformat(s),
        lambda s: datetime.strptime(s, "%Y年%m月%d日%H时%M分").replace(tzinfo=BEIJING_TZ),
    ):
        try:
            dt = parser(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=BEIJING_TZ)
            return dt
        except ValueError:
            continue
    return None


def resolve_first_web_push_time(generated_at_display: str, generated_dt: datetime) -> str:
    """Keep a stable first web-push/deploy timestamp across local and GitHub runs."""
    state = load_json(DASHBOARD_STATE, {})
    existing = state.get("first_web_push_at")
    if existing:
        parsed = parse_dashboard_time(existing)
        return format_beijing_time(parsed) if parsed else existing

    existing_payload = load_json(DOCS / "dashboard_data.json", {})
    existing = existing_payload.get("first_web_push_at") or existing_payload.get("generated_at")
    parsed = parse_dashboard_time(existing) if existing else None
    first_web_push_at = format_beijing_time(parsed or generated_dt)
    save_json(DASHBOARD_STATE, {"first_web_push_at": first_web_push_at})
    return first_web_push_at


def fmt(v):
    return "-" if v is None or v == "" else v


def main() -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    signals = load_json(OUT / "signals.json", [])
    contracts = load_json(OUT / "main_contracts.json", [])
    generated_dt = datetime.now(BEIJING_TZ)
    generated_at = format_beijing_time(generated_dt)
    first_web_push_at = resolve_first_web_push_time(generated_at, generated_dt)

    active = [s for s in signals if s.get("signal_direction") in {"long", "short"}]
    long_count = sum(1 for s in active if s.get("signal_direction") == "long")
    short_count = sum(1 for s in active if s.get("signal_direction") == "short")

    payload = {
        "generated_at": generated_at,
        "first_web_push_at": first_web_push_at,
        "signals": signals,
        "contracts": contracts,
        "stats": {
            "products": len(contracts),
            "active_signals": len(active),
            "long_count": long_count,
            "short_count": short_count,
        },
    }

    html = f"""<!doctype html>
<html lang=\"zh-CN\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <meta http-equiv=\"refresh\" content=\"300\" />
  <link rel=\"icon\" type=\"image/png\" sizes=\"192x192\" href=\"assets/brand/favicon-192.png\" />
  <link rel=\"apple-touch-icon\" sizes=\"512x512\" href=\"assets/brand/favicon-512.png\" />
  <title>农产品期货主力合约 Dashboard（七彩云南丰收组）</title>
  <style>
    :root {{ --bg:#0f172a; --panel:#111827; --panel2:#1f2937; --text:#e5e7eb; --muted:#94a3b8; --red:#f87171; --green:#34d399; --yellow:#facc15; --blue:#60a5fa; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--text); font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,"Noto Sans SC",sans-serif; }}
    header {{ padding:18px 24px; border-bottom:1px solid #263244; background:linear-gradient(180deg,#0b1220 0%,#0f172a 100%); position:sticky; top:0; z-index:2; }}
    .brand {{ display:flex; align-items:center; gap:20px; }}
    .brand-left {{ display:flex; align-items:center; gap:16px; min-width:0; }}
    .brand-icon {{ width:260px; height:auto; max-height:88px; border-radius:18px; background:#fff; box-shadow:0 12px 28px rgba(0,0,0,.22); flex:0 0 auto; object-fit:contain; }}
    .brand-copy {{ min-width:0; }}
    .brand-kicker {{ color:#9fbe9f; font-size:13px; font-weight:700; letter-spacing:.14em; text-transform:uppercase; margin-bottom:4px; }}
    h1 {{ margin:0 0 8px; font-size:25px; letter-spacing:-.02em; }}
    .muted {{ color:var(--muted); font-size:13px; }}
    .grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; padding:18px 24px; }}
    .card {{ background:var(--panel); border:1px solid #263244; border-radius:14px; padding:16px; box-shadow:0 8px 24px rgba(0,0,0,.18); }}
    .stat {{ font-size:28px; font-weight:700; margin-top:8px; }}
    .toolbar {{ padding:0 24px 12px; display:flex; gap:8px; flex-wrap:wrap; }}
    button {{ background:var(--panel2); color:var(--text); border:1px solid #374151; border-radius:999px; padding:8px 12px; cursor:pointer; }}
    button.active {{ border-color:var(--blue); color:#bfdbfe; }}
    main {{ padding:0 24px 32px; }}
    .table-wrap {{ width:100%; overflow-x:auto; border:1px solid #263244; border-radius:14px; background:var(--panel); }}
    table {{ width:100%; min-width:1180px; border-collapse:collapse; background:var(--panel); }}
    thead {{ display:table-header-group; }} tbody {{ display:table-row-group; }}
    th,td {{ padding:10px 12px; border-bottom:1px solid #263244; text-align:left; vertical-align:top; font-size:13px; }}
    th {{ color:#cbd5e1; background:#172033; position:static; top:auto; z-index:auto; }}
    tr:hover {{ background:#172033; }}
    .tag {{ display:inline-block; border-radius:999px; padding:2px 8px; font-size:12px; border:1px solid #334155; }}
    .long {{ color:var(--green); }} .short {{ color:var(--red); }} .neutral {{ color:var(--muted); }}
    .dynamic-update-time {{ color:#86efac !important; font-weight:900 !important; font-size:14px; }}
    .score {{ font-weight:700; }}
    .reason {{ max-width:420px; line-height:1.45; color:#cbd5e1; }}
    .alert {{ border-left:4px solid var(--yellow); }}
    @media (max-width:900px) {{ .brand {{ align-items:flex-start; flex-direction:column; }} .brand-left {{ align-items:flex-start; flex-direction:column; }} .brand-icon {{ width:min(260px,100%); max-height:none; border-radius:16px; }} .grid {{ grid-template-columns:repeat(2,1fr); }} .table-wrap {{ overflow-x:auto; }} }}
  </style>
</head>
<body>
<header>
  <div class=\"brand\">
    <div class=\"brand-left\">
      <img class=\"brand-icon\" src=\"assets/brand/nongchan-dashboard-logo.jpg\" alt=\"nongchan.us Agri Future Dashboard logo\" />
      <div class=\"brand-copy\">
        <div class=\"brand-kicker\">Agri Futures Dashboard</div>
        <h1>农产品期货主力合约 Dashboard（七彩云南丰收组）</h1>
        <div class=\"muted\">只跟踪主力合约；技术分 + 基本面分；OTC策略使用用户场外期权产品库。<strong class=\"dynamic-update-time\">动态更新时间：{generated_at}（北京时间）</strong></div>
      </div>
    </div>
  </div>
</header>
<section class=\"grid\">
  <div class=\"card\"><div class=\"muted\">跟踪品种</div><div class=\"stat\" id=\"products\">-</div></div>
  <div class=\"card\"><div class=\"muted\">有效信号</div><div class=\"stat\" id=\"activeSignals\">-</div></div>
  <div class=\"card\"><div class=\"muted\">偏多</div><div class=\"stat long\" id=\"longCount\">-</div></div>
  <div class=\"card\"><div class=\"muted\">偏空</div><div class=\"stat short\" id=\"shortCount\">-</div></div>
</section>
<div class=\"toolbar\">
  <button data-filter=\"all\" class=\"active\">全部</button>
  <button data-filter=\"signal\">只看有信号</button>
  <button data-filter=\"long\">偏多</button>
  <button data-filter=\"short\">偏空</button>
  <button data-filter=\"changed\">新增/变化</button>
</div>
<main>
  <div class="table-wrap">
  <table>
    <thead>
      <tr>
        <th>品种/合约</th><th>方向</th><th>价格</th><th>分数</th><th>风控</th><th>OTC策略</th><th>理由</th><th>状态</th>
      </tr>
    </thead>
    <tbody id=\"rows\"></tbody>
  </table>
  </div>
</main>
<script>
const DATA = {json.dumps(payload, ensure_ascii=False)};
const rows = DATA.signals || [];
document.getElementById('products').textContent = DATA.stats.products;
document.getElementById('activeSignals').textContent = DATA.stats.active_signals;
document.getElementById('longCount').textContent = DATA.stats.long_count;
document.getElementById('shortCount').textContent = DATA.stats.short_count;

function cls(dir) {{ return dir === 'long' ? 'long' : dir === 'short' ? 'short' : 'neutral'; }}
function biasText(v) {{
  if (v === 'bullish') return '偏多';
  if (v === 'bearish') return '偏空';
  if (v === 'neutral') return '中性';
  return '暂无';
}}
function factorBiasText(r) {{ return `供给：${{biasText(r.supply_bias)}} / 需求：${{biasText(r.demand_bias)}} / 库存：${{biasText(r.inventory_bias)}}`; }}
function directionText(r) {{ return `${{r.action || '-'}} / ${{r.signal_direction || '-'}}`; }}
function isChanged(r) {{ return ['new','changed'].includes(r.signal_change) || r.main_changed; }}
function render(filter='all') {{
  const tbody = document.getElementById('rows');
  tbody.innerHTML = '';
  rows.filter(r => {{
    if (filter === 'signal') return ['long','short'].includes(r.signal_direction);
    if (filter === 'long') return r.signal_direction === 'long';
    if (filter === 'short') return r.signal_direction === 'short';
    if (filter === 'changed') return isChanged(r);
    return true;
  }}).forEach(r => {{
    const tr = document.createElement('tr');
    if (['long','short'].includes(r.signal_direction)) tr.classList.add('alert');
    tr.innerHTML = `
      <td><b>${{r.product_name || ''}} ${{r.symbol || ''}}</b><br><span class=\"muted\">确认主力：${{r.confirmed_main || '-'}}</span></td>
      <td><span class=\"tag ${{cls(r.signal_direction)}}\">${{directionText(r)}}</span></td>
      <td>最新：${{r.latest_close ?? '-'}}<br><span class=\"muted\">MA5：${{r.ma5 ?? '-'}} / MA20：${{r.ma20 ?? '-'}}</span></td>
      <td><span class=\"score ${{Number(r.total_score) >= 0 ? 'long' : 'short'}}\">总分：${{r.total_score ?? '-'}}</span><br><span class=\"muted\">技术：${{r.technical_score ?? '-'}} / 基本面：${{r.fundamental_score ?? 0}} / 置信：${{r.confidence ?? '-'}}</span></td>
      <td>入场：${{r.entry ?? '-'}}<br>止损：${{r.stop_loss ?? '-'}}<br>目标：${{r.take_profit ?? '-'}}</td>
      <td><b>${{r.otc_strategy || '-'}}</b><br><span class=\"muted\">${{r.otc_reason || ''}}</span><br><span class=\"muted\">策略基本面：${{r.otc_fundamental_analysis || '-'}}</span></td>
      <td class=\"reason\">${{r.reason || '-'}}<br><span class=\"muted\">${{factorBiasText(r)}}</span><br><span class=\"muted\">${{r.fundamental_note || ''}}</span></td>
      <td>${{r.signal_change || '-'}}<br><span class=\"muted\">换月：${{r.rollover_status || '-'}}</span></td>`;
    tbody.appendChild(tr);
  }});
}}

document.querySelectorAll('button[data-filter]').forEach(btn => btn.addEventListener('click', () => {{
  document.querySelectorAll('button[data-filter]').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  render(btn.dataset.filter);
}}));
render();
</script>
</body>
</html>
"""
    (DOCS / "index.html").write_text(html, encoding="utf-8")
    (DOCS / "dashboard_data.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Dashboard written: {DOCS / 'index.html'}")


if __name__ == "__main__":
    main()
