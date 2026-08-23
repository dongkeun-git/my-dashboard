"""오케스트레이터: 리스트 로드 -> 데이터수집 -> 지표 -> 스코어링 -> 신호 -> 대시보드."""
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from stock_list import load_stock_list
from data_fetcher import fetch_ohlcv, get_target_price
from indicators import calculate_indicators
from scoring_smooth import score_latest_smooth_v2 as score_latest
from signal_engine import build_signal, decide_action, classify_long_trend, classify_mid_trend
from dashboard_generator import generate_dashboard
from events import (
    resample_ohlcv, add_candle_features, add_daily_trim_signal,
    add_rsi_cross, add_ma20_cross, add_ma_cross, bool_at,
)

ROOT = Path(__file__).resolve().parent.parent
STOCK_LIST_PATH = ROOT / "Stock_List.txt"
DASHBOARD_PATH = ROOT / "dashboard.html"

# 주봉 20주선/월봉 20개월선 크로스까지 계산하려면 넉넉한 히스토리가 필요.
FETCH_DAYS = 1100

ALERT_LABELS = {
    "band_breakout_d": "밴드상단 돌파(일)",
    "trim_confirmed_d": "과열 반전 확정(일)",
    "rsi_crossdown70_d": "RSI 70 하향돌파(일)",
    "rsi_crossdown70_w": "RSI 70 하향돌파(주)",
    "rsi_crossup30_d": "RSI 30 상향돌파(일)",
    "rsi_crossup30_w": "RSI 30 상향돌파(주)",
    "ma20_crossup_d": "20일선 상향돌파",
    "ma20_crossdown_d": "20일선 하향돌파",
    "ma20_crossup_w": "20주선 상향돌파",
    "ma20_crossdown_w": "20주선 하향돌파",
    "ma20_crossup_m": "20개월선 상향돌파",
    "ma20_crossdown_m": "20개월선 하향돌파",
    "golden_5_20": "골든크로스(5/20)",
    "dead_5_20": "데드크로스(5/20)",
    "golden_60_200": "골든크로스(60/200)",
    "dead_60_200": "데드크로스(60/200)",
}


# 추이 비교 시점 (거래일 기준). 1주 ~= 5거래일, 1개월 ~= 21거래일 전.
TREND_OFFSETS = {"_1m": 21, "_1w": 5}

# 대시보드 기본 정렬과 동일한 기준(액션 우선순위 -> 점수 내림차순)으로 순위를 매긴다.
ACTION_PRIORITY = {"ADD": 0, "HOLD": 1, "TRIM": 2, "SELL": 3}


def assign_ranks(results: list[dict]) -> None:
    """rank_now(전체 기준 현재 순위)와 rank_1m(1개월 전 데이터 기준 순위)을 각 결과에 채운다."""
    def key_now(r):
        return (ACTION_PRIORITY.get(r["action"], 99), -(r["score_now"] if r["score_now"] is not None else -999))

    for rank, r in enumerate(sorted(results, key=key_now), start=1):
        r["rank_now"] = rank

    ranked_1m = [r for r in results if r.get("action_1m") is not None and r.get("score_1m") is not None]

    def key_1m(r):
        return (ACTION_PRIORITY.get(r["action_1m"], 99), -r["score_1m"])

    for rank, r in enumerate(sorted(ranked_1m, key=key_1m), start=1):
        r["rank_1m"] = rank
    for r in results:
        r.setdefault("rank_1m", None)


def score_trend(clean: "pd.DataFrame", target_price: float, score_now: float) -> dict:
    """현재/1주일전/1개월전 조정점수. 목표가는 현재 시점 값을 그대로 적용한 근사치."""
    n = len(clean)
    trend = {"score_now": score_now}
    for suffix, offset in TREND_OFFSETS.items():
        idx = n - 1 - offset
        trend[f"score{suffix}"] = round(score_latest(clean.iloc[idx], target_price)["adjusted_score"], 1) if idx >= 0 else None
    return trend


def price_trend(clean: "pd.DataFrame", price_now: float) -> dict:
    """현재/1주일전/1개월전 종가."""
    n = len(clean)
    trend = {"price_now": price_now}
    for suffix, offset in TREND_OFFSETS.items():
        idx = n - 1 - offset
        trend[f"price{suffix}"] = float(clean.iloc[idx]["Close"]) if idx >= 0 else None
    return trend


# 액션 추이는 1개월(약 21거래일)전 vs 현재 두 값만 비교한다. 점수/주가처럼 1주일전까지
# 넣으면 액션(이산값)은 아직 안 바뀐 경우가 대부분이라 정보량이 적고, 반대로 그보다
# 길게 잡으면 중간에 있었던 전환을 놓친다 - 이미 쓰고 있는 "1개월전" 기준(21거래일)과
# 맞춰 점수/주가 추이와 같은 시점을 비교할 수 있게 했다.
ACTION_TREND_OFFSET = 21


def action_trend(clean: "pd.DataFrame", target_price: float) -> str | None:
    """1개월 전 시점 기준으로 액션을 재계산 (주봉 신호는 정렬 비용 때문에 제외한 근사치)."""
    n = len(clean)
    idx = n - 1 - ACTION_TREND_OFFSET
    if idx < 0:
        return None
    row = clean.iloc[idx]
    score = score_latest(row, target_price)
    long_t = classify_long_trend(row)
    mid_t = classify_mid_trend(row)
    extra = {
        "trim_confirmed_d": bool_at(row, "TrimConfirmed"),
        "rsi_crossdown70_d": bool_at(row, "RSI_CrossDown70_D"),
        "rsi_crossup30_d": bool_at(row, "RSI_CrossUp30_D"),
    }
    return decide_action(row, score, long_t, mid_t, extra)["action"]


def compute_timeframe_events(df_raw: "pd.DataFrame") -> dict:
    """일봉 원본으로부터 일/주/월봉 지표+크로스 시그널을 계산해 최신 시점 플래그를 반환."""
    daily = calculate_indicators(df_raw)
    daily = add_candle_features(daily)
    daily = add_daily_trim_signal(daily)
    daily = add_rsi_cross(daily, "_D")
    daily = add_ma20_cross(daily, "_D")
    daily = add_ma_cross(daily, "SMA5", "SMA20", "GC_5_20")
    daily = add_ma_cross(daily, "SMA60", "SMA200", "GC_60_200")
    daily_clean = daily.dropna(subset=["SMA20", "RSI14", "Band_Pct"])
    latest_d = daily_clean.iloc[-1] if len(daily_clean) else None

    def latest_timeframe_row(rule):
        try:
            resampled = resample_ohlcv(df_raw, rule)
            ind = calculate_indicators(resampled)
            ind = add_rsi_cross(ind, "")
            ind = add_ma20_cross(ind, "")
            ind_clean = ind.dropna(subset=["RSI14"])
            return ind_clean.iloc[-1] if len(ind_clean) else None
        except Exception:
            return None

    latest_w = latest_timeframe_row("W-FRI")
    latest_m = latest_timeframe_row("ME")

    flags = {
        "band_breakout_d": bool_at(latest_d, "BandBreakout"),
        "trim_confirmed_d": bool_at(latest_d, "TrimConfirmed"),
        "rsi_crossdown70_d": bool_at(latest_d, "RSI_CrossDown70_D"),
        "rsi_crossdown70_w": bool_at(latest_w, "RSI_CrossDown70"),
        "rsi_crossup30_d": bool_at(latest_d, "RSI_CrossUp30_D"),
        "rsi_crossup30_w": bool_at(latest_w, "RSI_CrossUp30"),
        "ma20_crossup_d": bool_at(latest_d, "MA20_CrossUp_D"),
        "ma20_crossdown_d": bool_at(latest_d, "MA20_CrossDown_D"),
        "ma20_crossup_w": bool_at(latest_w, "MA20_CrossUp"),
        "ma20_crossdown_w": bool_at(latest_w, "MA20_CrossDown"),
        "ma20_crossup_m": bool_at(latest_m, "MA20_CrossUp"),
        "ma20_crossdown_m": bool_at(latest_m, "MA20_CrossDown"),
        "golden_5_20": bool_at(latest_d, "GC_5_20_Golden"),
        "dead_5_20": bool_at(latest_d, "GC_5_20_Dead"),
        "golden_60_200": bool_at(latest_d, "GC_60_200_Golden"),
        "dead_60_200": bool_at(latest_d, "GC_60_200_Dead"),
    }
    return daily_clean, flags


def process_entry(entry: dict) -> dict:
    df = fetch_ohlcv(entry, days=FETCH_DAYS)
    clean, flags = compute_timeframe_events(df)
    latest = clean.iloc[-1]

    target_price, target_source, is_etf = get_target_price(entry, clean)
    score = score_latest(latest, target_price)
    signal = build_signal(latest, score, extra=flags)
    s_trend = score_trend(clean, target_price, score["adjusted_score"])
    p_trend = price_trend(clean, float(latest["Close"]))
    action_1m = action_trend(clean, target_price)
    alerts = [label for key, label in ALERT_LABELS.items() if flags.get(key)]

    return {
        "name": entry["name"],
        "code": entry["code"],
        "market": entry["market"],
        "is_etf": is_etf,
        "target_price": target_price,
        "target_source": target_source,
        "rsi": float(latest["RSI14"]),
        "band_pct": float(latest["Band_Pct"]),
        "vol_ratio": float(latest["Vol_Ratio"]),
        "disparity20": float(latest["Disparity20"]),
        "adx14": float(latest["ADX14"]) if latest.get("ADX14") == latest.get("ADX14") else None,
        "atr14": float(latest["ATR14"]) if latest.get("ATR14") == latest.get("ATR14") else None,
        "as_of": latest.name.strftime("%Y-%m-%d"),
        "alerts": alerts,
        "alert_count": len(alerts),
        "action_1m": action_1m,
        **score,
        **s_trend,
        **p_trend,
        **signal,
    }


def run(stock_list_path: Path, dashboard_path: Path, title: str = "보유 주식/ETF 매매 신호 대시보드") -> None:
    """리스트 로드 -> 처리 -> 대시보드 생성. 입출력 경로/제목만 바꿔 다른 종목군에도 그대로 재사용."""
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    entries = load_stock_list(stock_list_path)
    results, failures = [], []

    for i, entry in enumerate(entries, 1):
        label = f"{entry['name']} ({entry['code']})"
        try:
            res = process_entry(entry)
            results.append(res)
            print(f"[{i}/{len(entries)}] OK  {label}: score={res['adjusted_score']:.0f} action={res['action']}")
        except Exception as e:
            failures.append({"name": entry["name"], "code": entry["code"], "error": f"{type(e).__name__}: {e}"})
            print(f"[{i}/{len(entries)}] FAIL {label}: {type(e).__name__}: {e}")
            traceback.print_exc(limit=1)
        time.sleep(0.3)

    assign_ranks(results)
    generate_dashboard(results, failures, dashboard_path, title=title)

    print("\n" + "=" * 60)
    print(f"성공: {len(results)}/{len(entries)}  실패: {len(failures)}")
    if failures:
        for f in failures:
            print(f"  - {f['name']} ({f['code']}): {f['error']}")
    print(f"대시보드 생성: {dashboard_path}")
    print("=" * 60)


def main():
    run(STOCK_LIST_PATH, DASHBOARD_PATH)


if __name__ == "__main__":
    main()
