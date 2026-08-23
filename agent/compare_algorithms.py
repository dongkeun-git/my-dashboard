"""3개 알고리즘 성과 비교: 우리 스코어링 시스템 vs 터틀 트레이딩 vs 골든/데드크로스.

세 알고리즘 모두 동일한 종목군(Stock_List.txt), 동일한 과거 데이터(약 2년),
동일한 주간 샘플링, 동일한 1개월/3개월 순방향수익률·PASS 기준으로 채점한다.
인터넷에 발표된 각 알고리즘의 수익률을 그대로 인용하지 않고, 우리 파이프라인
안에서 직접 재구현해 같은 조건으로 비교하기 위함 (그래야 공정한 비교).

대상:
- 우리 시스템: 계층형 복합 스코어링(기존 signal_engine.decide_action, 70/40 임계값)
- 터틀 트레이딩: Donchian 55일 돌파 진입 / 20일 이탈 청산 (System 2, 항상 신호 취함)
- 골든/데드크로스: 50일선-200일선 교차, 상시 롱/현금 이진 상태

한계: 터틀의 피라미딩/ATR 포지션사이징, 골든크로스의 밴드필터 등 자금관리 규칙은
"어느 방향에 서야 하는가"라는 신호 자체와 무관하므로 제외했다. 목표가 팩터는
우리 시스템에만 존재하는 개념이라 다른 두 알고리즘에는 해당 없음.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from stock_list import load_stock_list
from data_fetcher import fetch_ohlcv, get_target_price
from indicators import calculate_indicators
from scoring_smooth import score_latest_smooth_v2 as score_latest
from signal_engine import decide_action, classify_long_trend, classify_mid_trend
from events import add_candle_features, add_daily_trim_signal, add_rsi_cross, bool_at
from benchmark_algos import turtle_actions, golden_cross_actions
from validate_scoring import (
    HORIZONS, PRIMARY_HORIZON, SAMPLE_STEP, HISTORY_DAYS,
    aggregate, print_horizon_report, evaluate_pass_criteria,
)

ROOT = Path(__file__).resolve().parent.parent
STOCK_LIST_PATH = ROOT / "Stock_List.txt"


def collect_all_algo_samples(entry: dict) -> tuple[list[dict], list[dict], list[dict]]:
    df = fetch_ohlcv(entry, days=HISTORY_DAYS)
    data = calculate_indicators(df)
    data = add_candle_features(data)
    data = add_daily_trim_signal(data)
    data = add_rsi_cross(data, "_D")
    clean = data.dropna(subset=["SMA20", "SMA200", "RSI14", "Band_Pct"])
    target_price, _, _ = get_target_price(entry, data)

    turtle_series = turtle_actions(data)
    gc_series = golden_cross_actions(data)

    n = len(clean)
    max_horizon_days = max(h for h, _ in HORIZONS.values())
    ours, turtle, gc = [], [], []
    for i in range(0, n - max_horizon_days, SAMPLE_STEP):
        row = clean.iloc[i]
        date = row.name
        entry_price = row["Close"]
        rets = {}
        for hname, (hdays, _theta) in HORIZONS.items():
            fwd_price = clean.iloc[i + hdays]["Close"]
            rets[hname] = (fwd_price - entry_price) / entry_price * 100

        score = score_latest(row, target_price)
        long_t = classify_long_trend(row)
        mid_t = classify_mid_trend(row)
        extra = {
            "trim_confirmed_d": bool_at(row, "TrimConfirmed"),
            "rsi_crossdown70_d": bool_at(row, "RSI_CrossDown70_D"),
            "rsi_crossup30_d": bool_at(row, "RSI_CrossUp30_D"),
        }
        our_action = decide_action(row, score, long_t, mid_t, extra)["action"]
        ours.append({"action": our_action, **{f"ret_{h}": rets[h] for h in HORIZONS}})

        t_action = turtle_series.get(date)
        if t_action:
            turtle.append({"action": t_action, **{f"ret_{h}": rets[h] for h in HORIZONS}})

        g_action = gc_series.get(date)
        if g_action:
            gc.append({"action": g_action, **{f"ret_{h}": rets[h] for h in HORIZONS}})

    return ours, turtle, gc


def report_algorithm(name: str, records: list[dict]) -> dict:
    print("\n" + "=" * 78)
    print(f" {name}  (표본 {len(records)}개)")
    print("=" * 78)
    result = {}
    for hname, (_hdays, theta) in HORIZONS.items():
        summary, baseline = aggregate(records, hname, theta)
        print_horizon_report(hname, theta, summary, baseline, len(records))
        result[hname] = (summary, baseline)

    primary_summary, primary_baseline = result[PRIMARY_HORIZON]
    checks, overall_pass = evaluate_pass_criteria(primary_summary, primary_baseline)
    n_pass = sum(1 for _, ok, _ in checks if ok)
    n_decidable = sum(1 for _, ok, _ in checks if ok is not None)
    print(f"\n  PASS {n_pass}/{n_decidable} ({PRIMARY_HORIZON} 기준) -> {'PASS' if overall_pass else 'FAIL'}")
    add_s = primary_summary.get("ADD")
    return {
        "n_pass": n_pass, "overall_pass": overall_pass,
        "add_ret": add_s["avg_ret"] if add_s else None,
        "add_n": add_s["n"] if add_s else 0,
        "baseline": primary_baseline,
    }


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    entries = load_stock_list(STOCK_LIST_PATH)
    all_ours, all_turtle, all_gc = [], [], []

    print(f"3개 알고리즘 비교 백테스트 시작 - {len(entries)}개 종목, 과거 {HISTORY_DAYS}일...\n")
    for i, entry in enumerate(entries, 1):
        try:
            ours, turtle, gc = collect_all_algo_samples(entry)
            all_ours.extend(ours)
            all_turtle.extend(turtle)
            all_gc.extend(gc)
            print(f"[{i}/{len(entries)}] {entry['name']} ({entry['code']}): "
                  f"ours={len(ours)} turtle={len(turtle)} gc={len(gc)}")
        except Exception as e:
            print(f"[{i}/{len(entries)}] {entry['name']} ({entry['code']}): 실패 - {type(e).__name__}: {e}")

    summary_rows = []
    for name, records in [("① 우리 시스템 (계층형 복합 스코어링)", all_ours),
                           ("② 터틀 트레이딩 (Donchian 55/20)", all_turtle),
                           ("③ 골든/데드크로스 (50/200 SMA)", all_gc)]:
        summary_rows.append((name, report_algorithm(name, records)))

    print("\n" + "=" * 78)
    print(" 최종 비교 요약 (1개월 기준)")
    print("=" * 78)
    print(f"{'알고리즘':38}{'ADD n':>8}{'ADD수익률':>12}{'baseline':>11}{'PASS':>8}")
    for name, r in summary_rows:
        add_ret_str = f"{r['add_ret']:+.2f}%" if r["add_ret"] is not None else "-"
        pass_str = f"{r['n_pass']}/5"
        print(f"{name:38}{r['add_n']:>8}{add_ret_str:>12}{r['baseline']:>+10.2f}%{pass_str:>8}")


if __name__ == "__main__":
    main()
