#!/usr/bin/env python3
"""Semi-automatic fundamental factor updater for the AKShare MVP.

Uses AKShare futures_spot_price_daily as a lightweight proxy:
- spot momentum: rising spot price is bullish
- dominant basis rate: spot premium over futures is bullish, futures premium is bearish

This is not a complete fundamental model. It creates an inspectable baseline that can
be overridden manually in config/fundamental_factors.csv.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"
OUT = ROOT / "output"

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


def _import_akshare():
    try:
        import akshare as ak
    except ImportError as exc:
        raise SystemExit("缺少 akshare。请在项目目录运行 uv run python scripts/update_fundamentals.py") from exc
    return ak


def clip(value: float, low: int = -100, high: int = 100) -> int:
    return int(round(max(low, min(high, value))))


def bias_label(score: int) -> str:
    if score >= 20:
        return "bullish"
    if score <= -20:
        return "bearish"
    return "neutral"


def safe_sum(series: pd.Series) -> float:
    """Sum numeric-looking values from AKShare tables; tolerate comma strings and blanks."""
    if series is None:
        return 0.0
    cleaned = series.astype(str).str.replace(",", "", regex=False).str.strip()
    return float(pd.to_numeric(cleaned, errors="coerce").fillna(0).sum())


def calc_inventory_score(daily_change: float) -> int:
    """Rising warehouse receipts are bearish inventory pressure; falling receipts are bullish."""
    if daily_change >= 500:
        return -25
    if daily_change >= 100:
        return -12
    if daily_change <= -500:
        return 25
    if daily_change <= -100:
        return 12
    return 0


def fetch_cotton_inventory_factor(ak, trade_date: str) -> dict:
    """Fetch CZCE cotton warehouse receipts and convert daily change into inventory bias."""
    try:
        receipt_map = ak.futures_warehouse_receipt_czce(date=trade_date)
        cf = receipt_map.get("CF") if isinstance(receipt_map, dict) else None
        if cf is None or cf.empty:
            return {"inventory_score": 0, "inventory_bias": "neutral", "inventory_note": "郑商所棉花仓单表为空，库存按中性处理。"}

        warehouse_receipts = safe_sum(cf.get("仓单数量"))
        daily_change = safe_sum(cf.get("当日增减"))
        effective_forecast = safe_sum(cf.get("有效预报"))
        inventory_score = calc_inventory_score(daily_change)
        inventory_note = (
            f"郑商所棉花仓单：仓单{warehouse_receipts:.0f}张，"
            f"当日增减{daily_change:+.0f}张，有效预报{effective_forecast:.0f}张，"
            f"库存分{inventory_score}。"
        )
        return {
            "inventory_score": inventory_score,
            "inventory_bias": "bullish" if inventory_score > 0 else "bearish" if inventory_score < 0 else "neutral",
            "inventory_note": inventory_note,
        }
    except Exception as exc:
        return {
            "inventory_score": 0,
            "inventory_bias": "neutral",
            "inventory_note": f"郑商所棉花仓单获取失败，库存按中性处理：{type(exc).__name__}: {exc}",
        }


def calc_factor(row_group: pd.DataFrame, code: str, name: str, extra: dict | None = None) -> dict:
    df = row_group.sort_values("date").copy()
    latest = df.iloc[-1]
    first = df.iloc[0]
    extra = extra or {}

    spot_latest = pd.to_numeric(latest.get("spot_price"), errors="coerce")
    spot_first = pd.to_numeric(first.get("spot_price"), errors="coerce")
    basis_rate = pd.to_numeric(latest.get("dom_basis_rate"), errors="coerce")

    spot_momentum_score = 0
    if pd.notna(spot_latest) and pd.notna(spot_first) and spot_first:
        # 5% spot move -> roughly 25 score points.
        spot_momentum_score = clip(((spot_latest / spot_first) - 1) * 500, -30, 30)

    basis_score = 0
    if pd.notna(basis_rate):
        # futures below spot (negative dom_basis_rate) treated as bullish spot premium.
        basis_score = clip(-basis_rate * 1000, -40, 40)

    inventory_score = int(extra.get("inventory_score", 0) or 0)
    inventory_bias = extra.get("inventory_bias") or bias_label(inventory_score)
    inventory_note = extra.get("inventory_note", "")

    score = clip(spot_momentum_score + basis_score + inventory_score, -100, 100)
    note = (
        f"AKShare现货/基差代理：现货{spot_latest}，主力基差率{basis_rate:.4f}，"
        f"现货动量分{spot_momentum_score}，基差分{basis_score}。"
        f"{inventory_note}"
        "该分数是半自动代理，不等同完整库存/供需模型。"
    )
    return {
        "product_code": code,
        "product_name": name,
        "fundamental_score": score,
        "inventory_bias": inventory_bias,
        "supply_bias": bias_label(basis_score),
        "demand_bias": bias_label(spot_momentum_score),
        "macro_bias": "neutral",
        "note": note,
        "updated_at": str(latest.get("date")),
    }


def default_factor(code: str, name: str, reason: str) -> dict:
    return {
        "product_code": code,
        "product_name": name,
        "fundamental_score": 0,
        "inventory_bias": "neutral",
        "supply_bias": "neutral",
        "demand_bias": "neutral",
        "macro_bias": "neutral",
        "note": f"未取得AKShare现货/基差数据，按中性处理：{reason}",
        "updated_at": date.today().isoformat(),
    }


def main() -> None:
    ak = _import_akshare()
    CONFIG.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)

    codes = [p["code"] for p in PRODUCTS]
    end_day = date.today().strftime("%Y%m%d")
    start_day = (date.today() - timedelta(days=10)).strftime("%Y%m%d")

    rows = []
    raw = pd.DataFrame()
    extra_factors = {"CF": fetch_cotton_inventory_factor(ak, end_day)}
    try:
        raw = ak.futures_spot_price_daily(start_day=start_day, end_day=end_day, vars_list=codes)
        raw.to_csv(OUT / "fundamental_spot_basis_raw.csv", index=False, encoding="utf-8-sig")
    except Exception as exc:
        for p in PRODUCTS:
            rows.append(default_factor(p["code"], p["name"], f"接口失败 {type(exc).__name__}: {exc}"))
    else:
        if raw.empty:
            for p in PRODUCTS:
                rows.append(default_factor(p["code"], p["name"], "接口返回空表"))
        else:
            raw["symbol"] = raw["symbol"].astype(str).str.upper()
            for p in PRODUCTS:
                code = p["code"]
                name = p["name"]
                group = raw[raw["symbol"] == code]
                if group.empty:
                    rows.append(default_factor(code, name, "该品种无现货/基差行"))
                else:
                    rows.append(calc_factor(group, code, name, extra_factors.get(code)))

    df = pd.DataFrame(rows)
    df.to_csv(CONFIG / "fundamental_factors.csv", index=False, encoding="utf-8-sig")
    df.to_csv(OUT / "fundamental_factors_latest.csv", index=False, encoding="utf-8-sig")
    print(df[["product_code", "product_name", "fundamental_score", "inventory_bias", "supply_bias", "demand_bias", "updated_at"]].to_string(index=False))
    print(f"\n已更新：{CONFIG / 'fundamental_factors.csv'}")


if __name__ == "__main__":
    main()
