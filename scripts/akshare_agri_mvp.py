#!/usr/bin/env python3
"""AKShare agricultural futures MVP.

Fetch active contracts, select the main contract only, pull daily bars, create
technical signal snapshots, match OTC option structures, and emit outputs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd


PRODUCTS = [
    {"code": "M", "name": "豆粕"},
    {"code": "RM", "name": "菜粕"},
    {"code": "Y", "name": "豆油"},
    {"code": "P", "name": "棕榈"},
    {"code": "OI", "name": "菜油"},
    {"code": "C", "name": "玉米"},
    {"code": "SR", "name": "白糖"},
    {"code": "CF", "name": "棉花"},
    {"code": "LH", "name": "生猪"},
    {"code": "PK", "name": "花生"},
    {"code": "AP", "name": "鲜苹果"},
    {"code": "JD", "name": "鸡蛋"},
]

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
STATE = ROOT / "state"
CONFIG = ROOT / "config"


@dataclass(frozen=True)
class RankingConfig:
    position_weight: float = 0.60
    volume_weight: float = 0.40
    top_n: int = 1


@dataclass(frozen=True)
class SignalConfig:
    actionable_score: int = 40
    stop_atr_multiplier: float = 1.5
    target_atr_multiplier: float = 2.5


def _import_akshare():
    try:
        import akshare as ak
    except ImportError as exc:
        raise SystemExit(
            "缺少 akshare。请在项目目录运行：uv sync 或 uv run python scripts/akshare_agri_mvp.py"
        ) from exc
    return ak


def normalize_score(series: pd.Series) -> pd.Series:
    series = pd.to_numeric(series, errors="coerce").fillna(0)
    max_value = series.max()
    if max_value <= 0:
        return pd.Series(0.0, index=series.index)
    return series / max_value



def load_fundamental_factors() -> dict[str, dict]:
    path = CONFIG / "fundamental_factors.csv"
    if not path.exists():
        return {}
    df = pd.read_csv(path)
    factors: dict[str, dict] = {}
    for _, row in df.iterrows():
        code = str(row.get("product_code", "")).strip()
        if not code:
            continue
        raw_score = pd.to_numeric(row.get("fundamental_score", 0), errors="coerce")
        score = 0 if pd.isna(raw_score) else int(max(-100, min(100, raw_score)))
        factors[code] = {
            "fundamental_score": score,
            "inventory_bias": row.get("inventory_bias", "neutral"),
            "supply_bias": row.get("supply_bias", "neutral"),
            "demand_bias": row.get("demand_bias", "neutral"),
            "macro_bias": row.get("macro_bias", "neutral"),
            "fundamental_note": row.get("note", ""),
            "fundamental_updated_at": row.get("updated_at", ""),
        }
    return factors


def combine_scores(technical_score: int, fundamental_score: int) -> int:
    """70% technical + 30% fundamental for MVP."""
    return int(round(0.70 * technical_score + 0.30 * fundamental_score))

def fetch_active_contracts(ak, product_name: str) -> pd.DataFrame:
    df = ak.futures_zh_realtime(symbol=product_name)
    if df.empty:
        return df

    df = df.copy()
    # Drop continuous contract row, e.g. M0 / SR0, keep concrete contracts only.
    df = df[~df["symbol"].astype(str).str.endswith("0")]
    for col in ["trade", "volume", "position", "settlement", "presettlement"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    return df


def rank_contracts(df: pd.DataFrame, cfg: RankingConfig) -> pd.DataFrame:
    if df.empty:
        return df
    ranked = df.copy()
    ranked["volume_score"] = normalize_score(ranked["volume"])
    ranked["position_score"] = normalize_score(ranked["position"])
    ranked["liquidity_score"] = (
        cfg.position_weight * ranked["position_score"]
        + cfg.volume_weight * ranked["volume_score"]
    )
    ranked = ranked.sort_values(
        ["liquidity_score", "position", "volume"], ascending=False
    ).reset_index(drop=True)
    ranked["rank"] = ranked.index + 1
    ranked["role"] = ranked["rank"].map({1: "main"}).fillna("watch")
    return ranked


def fetch_daily_bars(ak, symbol: str, tail: int = 100) -> pd.DataFrame:
    bars = ak.futures_zh_daily_sina(symbol=symbol)
    if bars.empty:
        return bars
    bars = bars.copy()
    bars["symbol"] = symbol
    bars["date"] = pd.to_datetime(bars["date"], errors="coerce")
    for col in ["open", "high", "low", "close", "volume", "hold", "settle"]:
        if col in bars.columns:
            bars[col] = pd.to_numeric(bars[col], errors="coerce")
    return bars.tail(tail)


def calc_atr(bars: pd.DataFrame, window: int = 14) -> float:
    if bars.empty or len(bars) < window + 1:
        return 0.0
    high = bars["high"].astype(float)
    low = bars["low"].astype(float)
    close = bars["close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    atr = tr.rolling(window).mean().iloc[-1]
    if pd.isna(atr):
        return 0.0
    return round(float(atr), 4)


def calc_technical_snapshot(bars: pd.DataFrame) -> dict:
    if bars.empty or len(bars) < 20:
        return {
            "bias": "insufficient_data",
            "technical_score": 0,
            "reason": "日线不足20根",
            "atr14": 0.0,
        }

    close = bars["close"].astype(float)
    ma5 = close.rolling(5).mean().iloc[-1]
    ma20 = close.rolling(20).mean().iloc[-1]
    latest = close.iloc[-1]
    prev = close.iloc[-2] if len(close) >= 2 else latest
    atr14 = calc_atr(bars)

    score = 0
    reasons = []
    if latest > ma20:
        score += 35
        reasons.append("收盘价高于MA20")
    else:
        score -= 35
        reasons.append("收盘价低于MA20")
    if ma5 > ma20:
        score += 25
        reasons.append("MA5高于MA20")
    else:
        score -= 25
        reasons.append("MA5低于MA20")
    if latest > prev:
        score += 10
        reasons.append("最新收盘上涨")
    else:
        score -= 10
        reasons.append("最新收盘未上涨")

    if score >= 40:
        bias = "bullish"
    elif score <= -40:
        bias = "bearish"
    else:
        bias = "neutral"
    return {
        "bias": bias,
        "technical_score": score,
        "latest_close": round(float(latest), 4),
        "ma5": round(float(ma5), 4),
        "ma20": round(float(ma20), 4),
        "atr14": atr14,
        "reason": "；".join(reasons),
    }


def match_otc_strategy(direction: str, confidence: int) -> tuple[str, str]:
    """Return user-provided OTC product family and explanation."""
    if direction == "long":
        if confidence >= 70:
            return (
                "采省易3.0 / 累进宝Plus",
                "偏多信号较强，优先用采购套保类结构：保护上涨采购风险，同时接受上涨保护封顶或下跌被动低位建多。",
            )
        return (
            "累进宝3.0 / 采省易3.0",
            "偏多但强度一般，适合震荡偏强采购场景：争取区间补贴或上涨保护，下跌时需能承接采购/多头敞口。",
        )
    if direction == "short":
        if confidence >= 70:
            return (
                "惠鑫保1.0 / 惠鑫保2.0",
                "偏空信号较强，优先用库存/销售保护类结构：保护下跌风险；1.0保护更完整，2.0成本更低但大跌可能保护中断。",
            )
        return (
            "凤凰累沽2.0 / 惠鑫保2.0",
            "偏空但强度一般，适合库存销售或高位增强：区间拿补贴或低成本保护；若选择凤凰累沽，默认用2.0版本，需接受上涨敲入后建空风险。",
        )
    return "暂不匹配", "信号不足，不建议新开方向性场外期权结构。"


def build_otc_fundamental_analysis(item: dict, direction: str, strategy: str) -> str:
    """Explain why the matched OTC structure fits or conflicts with fundamentals."""
    f_score = int(item.get("fundamental_score", 0) or 0)
    t_score = int(item.get("technical_score", 0) or 0)
    total_score = int(item.get("total_score", t_score) or 0)
    def bias_cn(value: str) -> str:
        mapping = {"bullish": "偏多", "bearish": "偏空", "neutral": "中性"}
        return mapping.get(str(value or "").lower(), "暂无")

    supply_bias = bias_cn(item.get("supply_bias", "neutral"))
    demand_bias = bias_cn(item.get("demand_bias", "neutral"))
    inventory_bias = bias_cn(item.get("inventory_bias", "neutral"))
    note = str(item.get("fundamental_note", "") or "")

    if f_score >= 30:
        f_view = "基本面偏多"
    elif f_score <= -30:
        f_view = "基本面偏空"
    else:
        f_view = "基本面中性"

    bias_text = f"供给：{supply_bias}，需求：{demand_bias}，库存：{inventory_bias}"
    proxy_note = "基本面来自现货/基差代理，需结合库存、仓单、进口利润和产业订单复核。"

    if direction == "long":
        if f_score >= 20:
            return (
                f"{f_view}，与采购/累购类策略方向一致；{bias_text}。"
                f"推{strategy}的基本面依据是现货/基差对期货有支撑，适合采购方防上涨或优化采购成本。{proxy_note}"
            )
        return (
            f"{f_view}，对采购/累购类策略支撑不足；{bias_text}。"
            f"若仍推{strategy}，应降低名义量，避免把技术信号交易变成无现货需求的投机多头。{proxy_note}"
        )

    if direction == "short":
        if f_score <= -20:
            return (
                f"{f_view}，与库存保护/累沽类策略方向一致；{bias_text}。"
                f"推{strategy}的基本面依据是现货或基差弱化，适合库存方锁定销售价格或增强下跌保护。{proxy_note}"
            )
        return (
            f"{f_view}，与偏空OTC策略存在冲突；{bias_text}。"
            f"若仍推{strategy}，应优先保护型结构、降低增强型敲入风险，尤其避免在强基差下过度做凤凰累沽。{proxy_note}"
        )

    if f_score >= 30:
        return (
            f"{f_view}但技术未确认，暂不做强方向匹配；{bias_text}。"
            f"更适合观察采购类结构的触发条件，例如采省易/累进宝，等待价格站回关键均线后再提高策略等级。{proxy_note}"
        )
    if f_score <= -30:
        return (
            f"{f_view}但技术未形成有效偏空信号，暂不做强方向匹配；{bias_text}。"
            f"库存方可观察惠鑫保类保护结构，等待价格跌破关键支撑或总分转负后再推送。{proxy_note}"
        )
    return (
        f"{f_view}，技术与基本面合成总分={total_score}，方向不足；{bias_text}。"
        f"当前不建议新开方向性场外结构，等待现货/基差或技术趋势给出更清晰信号。{proxy_note}"
    )


def generate_signal(item: dict, cfg: SignalConfig) -> dict:
    score = int(item.get("total_score", item.get("technical_score", 0)))
    latest = float(item.get("latest_close") or item.get("trade") or 0)
    atr = float(item.get("atr14") or 0)
    role = item.get("role")

    if role != "main":
        direction = "watch"
        status = "watch_only"
        action = "观察"
        entry = stop = target = None
        confidence = max(0, min(100, abs(score)))
    elif score >= cfg.actionable_score and latest > 0 and atr > 0:
        direction = "long"
        status = "pending"
        action = "偏多观察"
        entry = latest
        stop = latest - cfg.stop_atr_multiplier * atr
        target = latest + cfg.target_atr_multiplier * atr
        confidence = max(0, min(100, abs(score)))
    elif score <= -cfg.actionable_score and latest > 0 and atr > 0:
        direction = "short"
        status = "pending"
        action = "偏空观察"
        entry = latest
        stop = latest + cfg.stop_atr_multiplier * atr
        target = latest - cfg.target_atr_multiplier * atr
        confidence = max(0, min(100, abs(score)))
    else:
        direction = "neutral"
        status = "no_signal"
        action = "暂不操作"
        entry = stop = target = None
        confidence = max(0, min(100, abs(score)))

    strategy, strategy_reason = match_otc_strategy(direction, confidence)
    strategy_fundamental_analysis = build_otc_fundamental_analysis(item, direction, strategy)
    return {
        "signal_direction": direction,
        "signal_status": status,
        "action": action,
        "entry": round(entry, 4) if entry is not None else None,
        "stop_loss": round(stop, 4) if stop is not None else None,
        "take_profit": round(target, 4) if target is not None else None,
        "confidence": confidence,
        "otc_strategy": strategy,
        "otc_reason": strategy_reason,
        "otc_fundamental_analysis": strategy_fundamental_analysis,
    }



def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def signal_signature(item: dict) -> str:
    fields = [
        item.get("symbol"),
        item.get("signal_direction"),
        item.get("signal_status"),
        item.get("otc_strategy"),
        item.get("entry"),
        item.get("stop_loss"),
        item.get("take_profit"),
        item.get("total_score"),
        item.get("fundamental_score"),
        item.get("otc_fundamental_analysis"),
    ]
    return "|".join(str(x) for x in fields)


def apply_rollover_state(signal_rows: list[dict]) -> list[dict]:
    """Add 3-run rollover confirmation fields and persist contract state.

    MVP rule: rank-1 is detected main. A new detected main becomes confirmed main
    only after it remains rank-1 for 3 distinct trade dates/runs.
    """
    state_path = STATE / "contract_state.json"
    state = load_json(state_path, {})
    next_state = dict(state)

    for product in PRODUCTS:
        code = product["code"]
        rows = [r for r in signal_rows if r.get("product_code") == code]
        if not rows:
            continue
        main_row = next((r for r in rows if r.get("rank") == 1), rows[0])
        detected_main = main_row.get("symbol")
        trade_date = str(main_row.get("tradedate") or datetime.now().date())
        prev = state.get(code, {})
        confirmed = prev.get("confirmed_main") or detected_main
        candidate = prev.get("candidate")
        streak = int(prev.get("candidate_streak", 0) or 0)
        last_date = prev.get("last_trade_date")
        previous_confirmed = confirmed

        if detected_main == confirmed:
            candidate = None
            streak = 0
            status = "confirmed"
        else:
            if last_date != trade_date:
                if candidate == detected_main:
                    streak += 1
                else:
                    candidate = detected_main
                    streak = 1
            status = f"rollover_candidate_{streak}/3"
            if streak >= 3:
                confirmed = detected_main
                candidate = None
                streak = 0
                status = "confirmed_after_3"

        next_state[code] = {
            "confirmed_main": confirmed,
            "previous_confirmed_main": previous_confirmed,
            "detected_main": detected_main,
            "candidate": candidate,
            "candidate_streak": streak,
            "last_trade_date": trade_date,
            "rollover_status": status,
        }

        for r in rows:
            r["detected_main"] = detected_main
            r["confirmed_main"] = confirmed
            r["rollover_candidate"] = candidate
            r["rollover_streak"] = streak
            r["rollover_status"] = status
            r["is_confirmed_main"] = r.get("symbol") == confirmed
            r["is_detected_main"] = r.get("symbol") == detected_main
            r["main_changed"] = previous_confirmed != confirmed

    save_json(state_path, next_state)
    return signal_rows


def apply_signal_dedupe(signal_rows: list[dict]) -> list[dict]:
    """Mark each main-contract signal as new/changed/unchanged and persist signatures."""
    state_path = STATE / "signal_state.json"
    previous = load_json(state_path, {})
    current = {}

    for item in signal_rows:
        if item.get("role") != "main":
            item["signal_change"] = "watch_only"
            continue
        key = item["product_code"]
        sig = signal_signature(item)
        current[key] = sig
        if key not in previous:
            change = "new"
        elif previous[key] != sig:
            change = "changed"
        else:
            change = "unchanged"
        item["signal_change"] = change

    save_json(state_path, current)
    return signal_rows

def records_to_json(records: Iterable[dict]) -> str:
    return json.dumps(list(records), ensure_ascii=False, indent=2, default=str)


def fmt_value(value) -> str:
    return "-" if value is None or value == "" else str(value)


def build_telegram_message(signal_rows: list[dict], only_changes: bool = False) -> str:
    title = "农产品期货主力合约监控" if not only_changes else "农产品期货主力信号变化"
    lines = [
        title,
        f"生成时间：{datetime.now().isoformat(timespec='seconds')}",
        "规则：只跟踪主力合约；换月需连续3次确认。",
        "",
    ]
    included = 0
    for item in signal_rows:
        if item.get("role") != "main":
            continue
        if only_changes and item.get("signal_change") == "unchanged" and not item.get("main_changed"):
            continue
        included += 1
        lines.extend(
            [
                f"{item['product_name']} {item['symbol']}",
                f"状态：{item.get('signal_change', '-')}，换月：{item.get('rollover_status', '-')}",
                f"确认主力：{item.get('confirmed_main', '-')}，检测主力：{item.get('detected_main', '-')}",
                f"方向：{item['action']} / {item['signal_direction']}",
                f"最新价：{fmt_value(item.get('latest_close'))}",
                f"技术分：{item['technical_score']}，基本面分：{item.get('fundamental_score', 0)}，总分：{item.get('total_score', item['technical_score'])}，置信度：{item['confidence']}",
                f"基本面：{item.get('fundamental_note', '未配置，按中性处理')}",
                f"入场参考：{fmt_value(item.get('entry'))}",
                f"止损：{fmt_value(item.get('stop_loss'))}，目标：{fmt_value(item.get('take_profit'))}",
                f"OTC策略：{item['otc_strategy']}",
                f"策略基本面：{item.get('otc_fundamental_analysis', '-')}",
                f"理由：{item['reason']}；{item['otc_reason']}",
                "",
            ]
        )
    if only_changes and included == 0:
        lines.append("本次无新增或变化信号。")
    return "\n".join(lines).strip() + "\n"


def main() -> None:
    ak = _import_akshare()
    OUT.mkdir(parents=True, exist_ok=True)
    STATE.mkdir(parents=True, exist_ok=True)
    CONFIG.mkdir(parents=True, exist_ok=True)
    fundamentals = load_fundamental_factors()
    rank_cfg = RankingConfig()
    signal_cfg = SignalConfig()

    contract_rows: list[dict] = []
    signal_rows: list[dict] = []
    bar_rows: list[pd.DataFrame] = []
    summary_lines = [
        f"AKShare 农产品期货 MVP 输出时间：{datetime.now().isoformat(timespec='seconds')}",
        "规则：持仓量60% + 成交量40%，每品种只取主力合约。",
        "信号：主力合约生成方向观察；止损/目标用 ATR14。",
        "换月：检测主力需连续3次保持第一才确认切换。",
        "总分：技术70% + 基本面30%；基本面配置见 config/fundamental_factors.csv。",
        "",
    ]

    for product in PRODUCTS:
        code = product["code"]
        name = product["name"]
        try:
            active = fetch_active_contracts(ak, name)
            ranked = rank_contracts(active, rank_cfg).head(rank_cfg.top_n)
            if ranked.empty:
                summary_lines.append(f"{code} {name}: 无活跃合约返回")
                continue

            summary_lines.append(f"{code} {name}:")
            for _, row in ranked.iterrows():
                symbol = str(row["symbol"])
                bars = fetch_daily_bars(ak, symbol)
                tech = calc_technical_snapshot(bars)
                fundamental = fundamentals.get(code, {"fundamental_score": 0, "fundamental_note": "未配置，按中性处理"})
                total_score = combine_scores(int(tech.get("technical_score", 0)), int(fundamental.get("fundamental_score", 0)))
                if not bars.empty:
                    bar_rows.append(bars)

                item = {
                    "product_code": code,
                    "product_name": name,
                    "rank": int(row["rank"]),
                    "role": row["role"],
                    "symbol": symbol,
                    "exchange": row.get("exchange"),
                    "contract_name": row.get("name"),
                    "trade": row.get("trade"),
                    "volume": int(row.get("volume", 0)),
                    "position": int(row.get("position", 0)),
                    "tradedate": row.get("tradedate"),
                    "ticktime": row.get("ticktime"),
                    "liquidity_score": round(float(row.get("liquidity_score", 0)), 6),
                    **tech,
                    **fundamental,
                    "total_score": total_score,
                }
                contract_rows.append(item)
                signal = {**item, **generate_signal(item, signal_cfg)}
                signal_rows.append(signal)
                summary_lines.append(
                    f"  {item['rank']}. {item['symbol']} {item['role']} "
                    f"成交量={item['volume']} 持仓量={item['position']} "
                    f"技术={item['bias']}({item['technical_score']}) 基本面={item.get('fundamental_score', 0)} 总分={item.get('total_score', 0)} "
                    f"信号={signal['action']} 策略={signal['otc_strategy']}"
                )
        except Exception as exc:  # Keep MVP run from failing on one data-source issue.
            summary_lines.append(f"{code} {name}: ERROR {type(exc).__name__}: {exc}")

    signal_rows = apply_rollover_state(signal_rows)
    signal_rows = apply_signal_dedupe(signal_rows)
    contract_lookup = {(r["product_code"], r["symbol"]): r for r in signal_rows}
    contract_rows = [
        {**item, **{k: v for k, v in contract_lookup.get((item["product_code"], item["symbol"]), {}).items()
                   if k in ["detected_main", "confirmed_main", "rollover_candidate", "rollover_streak", "rollover_status", "is_confirmed_main", "is_detected_main", "main_changed"]}}
        for item in contract_rows
    ]

    contracts_df = pd.DataFrame(contract_rows)
    contracts_df.to_csv(OUT / "main_contracts.csv", index=False, encoding="utf-8-sig")
    (OUT / "main_contracts.json").write_text(
        records_to_json(contract_rows), encoding="utf-8"
    )
    # Backward-compatible filenames for existing cron/downstream scripts.
    contracts_df.to_csv(OUT / "main_secondary_contracts.csv", index=False, encoding="utf-8-sig")
    (OUT / "main_secondary_contracts.json").write_text(
        records_to_json(contract_rows), encoding="utf-8"
    )

    signals_df = pd.DataFrame(signal_rows)
    signals_df.to_csv(OUT / "signals.csv", index=False, encoding="utf-8-sig")
    (OUT / "signals.json").write_text(records_to_json(signal_rows), encoding="utf-8")
    (OUT / "telegram_message.txt").write_text(
        build_telegram_message(signal_rows), encoding="utf-8"
    )
    (OUT / "telegram_delta_message.txt").write_text(
        build_telegram_message(signal_rows, only_changes=True), encoding="utf-8"
    )

    if bar_rows:
        bars_df = pd.concat(bar_rows, ignore_index=True)
        bars_df.to_csv(OUT / "latest_bars.csv", index=False, encoding="utf-8-sig")

    (OUT / "summary.txt").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    print("\n".join(summary_lines))
    print(f"\n输出目录：{OUT}")


if __name__ == "__main__":
    main()
