"""3-way 비교: ① 계단식(기존) vs ② 연속-v1(숫자형 지표만 연속화) vs ③ 연속-v2(v1 + OBV 램프 + TRIM 3일 지속성).

지난 실험(compare_scoring_smoothness.py)에서 v1은 수익률 손해 없이 변동성을 소폭
낮췄지만, 실제 급변 사례(삼성생명의 OBV 크로스, PLUS글로벌방산의 TRIM 단발성)는
그대로 남아있었다. 이번 실험은 그 두 원인을 직접 손본 v2가 추가로 개선되는지 확인.
"""
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from stock_list import load_stock_list
from data_fetcher import fetch_ohlcv, get_target_price
from indicators import calculate_indicators
from scoring import score_latest
from scoring_smooth import score_latest_smooth, score_latest_smooth_v2
from signal_engine import decide_action, classify_long_trend, classify_mid_trend
from events import (
    add_candle_features, add_daily_trim_signal, add_rsi_cross, add_trim_persistence, bool_at,
)
from validate_scoring import (
    HORIZONS, PRIMARY_HORIZON, SAMPLE_STEP, HISTORY_DAYS,
    aggregate, print_horizon_report, evaluate_pass_criteria,
)

ROOT = Path(__file__).resolve().parent.parent
STOCK_LIST_PATH = ROOT / "Stock_List.txt"
ACTION_PRIORITY = {"ADD": 0, "HOLD": 1, "TRIM": 2, "SELL": 3}

VARIANTS = ["discrete", "smooth_v1", "smooth_v2"]
VARIANT_LABELS = {
    "discrete": "① 계단식 (기존)",
    "smooth_v1": "② 연속-v1 (숫자형 지표만)",
    "smooth_v2": "③ 연속-v2 (+OBV램프 +TRIM 3일 지속)",
}


def collect_all(entry: dict) -> dict:
    df = fetch_ohlcv(entry, days=HISTORY_DAYS)
    data = calculate_indicators(df)
    data = add_candle_features(data)
    data = add_daily_trim_signal(data)
    data = add_rsi_cross(data, "_D")
    data = add_trim_persistence(data, window=3)
    clean = data.dropna(subset=["SMA20", "SMA200", "RSI14", "Band_Pct"])
    target_price, _, _ = get_target_price(entry, data)

    n = len(clean)
    max_horizon_days = max(h for h, _ in HORIZONS.values())
    out = {v: {"records": [], "scores": [], "actions": []} for v in VARIANTS}

    for i in range(0, n - max_horizon_days, SAMPLE_STEP):
        row = clean.iloc[i]
        entry_price = row["Close"]
        rets = {}
        for hname, (hdays, _theta) in HORIZONS.items():
            fwd_price = clean.iloc[i + hdays]["Close"]
            rets[hname] = (fwd_price - entry_price) / entry_price * 100

        long_t = classify_long_trend(row)
        mid_t = classify_mid_trend(row)
        extra_base = {
            "rsi_crossdown70_d": bool_at(row, "RSI_CrossDown70_D"),
            "rsi_crossup30_d": bool_at(row, "RSI_CrossUp30_D"),
        }

        for variant in VARIANTS:
            if variant == "discrete":
                score = score_latest(row, target_price)
                extra = {**extra_base, "trim_confirmed_d": bool_at(row, "TrimConfirmed")}
            elif variant == "smooth_v1":
                score = score_latest_smooth(row, target_price)
                extra = {**extra_base, "trim_confirmed_d": bool_at(row, "TrimConfirmed")}
            else:
                score = score_latest_smooth_v2(row, target_price)
                extra = {**extra_base, "trim_confirmed_d": bool_at(row, "TrimConfirmedPersist")}

            action = decide_action(row, score, long_t, mid_t, extra)["action"]
            out[variant]["records"].append({"action": action, **{f"ret_{h}": rets[h] for h in HORIZONS}})
            out[variant]["scores"].append(score["adjusted_score"])
            out[variant]["actions"].append(action)

    return out


def stability_stats(scores_seq: list[float], actions_seq: list[str]) -> dict:
    score_diffs = [abs(scores_seq[i] - scores_seq[i - 1]) for i in range(1, len(scores_seq))]
    flip_dists = [abs(ACTION_PRIORITY[actions_seq[i]] - ACTION_PRIORITY[actions_seq[i - 1]])
                  for i in range(1, len(actions_seq))]
    severe = sum(1 for d in flip_dists if d >= 2)
    return {"score_diffs": score_diffs, "n_transitions": len(flip_dists), "severe_flips": severe}


def report_returns(name: str, records: list[dict]) -> dict:
    print("\n" + "=" * 78)
    print(f" {name} - 수익률 ({PRIMARY_HORIZON} 기준, 표본 {len(records)}개)")
    print("=" * 78)
    theta = HORIZONS[PRIMARY_HORIZON][1]
    summary, baseline = aggregate(records, PRIMARY_HORIZON, theta)
    print_horizon_report(PRIMARY_HORIZON, theta, summary, baseline, len(records))
    checks, overall_pass = evaluate_pass_criteria(summary, baseline)
    n_pass = sum(1 for _, ok, _ in checks if ok)
    print(f"  PASS {n_pass}/5 -> {'PASS' if overall_pass else 'FAIL'}")
    add_s = summary.get("ADD")
    return {"n_pass": n_pass, "add_ret": add_s["avg_ret"] if add_s else None, "add_n": add_s["n"] if add_s else 0}


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    entries = load_stock_list(STOCK_LIST_PATH)
    pooled = {v: {"records": [], "score_diffs": [], "n_transitions": 0, "severe_flips": 0} for v in VARIANTS}

    print(f"3-way 채점방식 비교 시작 - {len(entries)}개 종목, 과거 {HISTORY_DAYS}일...\n")
    for i, entry in enumerate(entries, 1):
        try:
            out = collect_all(entry)
            for v in VARIANTS:
                pooled[v]["records"].extend(out[v]["records"])
                stab = stability_stats(out[v]["scores"], out[v]["actions"])
                pooled[v]["score_diffs"].extend(stab["score_diffs"])
                pooled[v]["n_transitions"] += stab["n_transitions"]
                pooled[v]["severe_flips"] += stab["severe_flips"]
            print(f"[{i}/{len(entries)}] {entry['name']} ({entry['code']}): 표본 {len(out['discrete']['records'])}개")
        except Exception as e:
            print(f"[{i}/{len(entries)}] {entry['name']} ({entry['code']}): 실패 - {type(e).__name__}: {e}")

    ret_results = {}
    for v in VARIANTS:
        ret_results[v] = report_returns(VARIANT_LABELS[v], pooled[v]["records"])

    print("\n" + "=" * 78)
    print(" 안정성 비교 (연속된 주간 샘플 사이 변동폭)")
    print("=" * 78)
    for v in VARIANTS:
        diffs = pooled[v]["score_diffs"]
        n_trans = pooled[v]["n_transitions"]
        severe = pooled[v]["severe_flips"]
        avg_d = statistics.mean(diffs) if diffs else 0.0
        p90 = statistics.quantiles(diffs, n=10)[8] if len(diffs) >= 10 else max(diffs, default=0.0)
        severe_rate = severe / n_trans * 100 if n_trans else 0.0
        print(f"  {VARIANT_LABELS[v]}: 평균|Δ점수|={avg_d:.2f}, 상위10%|Δ점수|={p90:.2f}, "
              f"급변비율={severe_rate:.1f}% (n={n_trans})")

    print("\n" + "=" * 78)
    print(" 최종 요약")
    print("=" * 78)
    for v in VARIANTS:
        r = ret_results[v]
        diffs = pooled[v]["score_diffs"]
        n_trans = pooled[v]["n_transitions"]
        severe_rate = pooled[v]["severe_flips"] / n_trans * 100 if n_trans else 0.0
        print(f"  {VARIANT_LABELS[v]:38}: ADD 평균수익률={r['add_ret']:+.2f}% (n={r['add_n']}), "
              f"PASS {r['n_pass']}/5, 평균변동폭={statistics.mean(diffs):.2f}, 급변비율={severe_rate:.1f}%")


if __name__ == "__main__":
    main()
