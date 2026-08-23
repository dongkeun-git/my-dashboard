"""계단식(기존) vs 연속·선형보간(신규) 채점 방식 비교.

두 축으로 비교한다:
① 수익률 - 기존 validate_scoring.py와 동일한 방식(1개월 순방향수익률, PASS 5기준)
② 안정성 - 연속된 주간 샘플 사이 점수 변동폭, 그리고 액션이 HOLD를 건너뛰고
  급변하는 비율(ADD<->TRIM, ADD<->SELL, HOLD<->SELL 등 ACTION_PRIORITY 거리 2 이상)

같은 종목·같은 표본·같은 임계값(70/40)에 채점 방식만 바꿔 대입하므로 공정 비교.
"""
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from stock_list import load_stock_list
from data_fetcher import fetch_ohlcv, get_target_price
from indicators import calculate_indicators
from scoring import score_latest
from scoring_smooth import score_latest_smooth
from signal_engine import decide_action, classify_long_trend, classify_mid_trend
from events import add_candle_features, add_daily_trim_signal, add_rsi_cross, bool_at
from validate_scoring import (
    HORIZONS, PRIMARY_HORIZON, SAMPLE_STEP, HISTORY_DAYS,
    aggregate, print_horizon_report, evaluate_pass_criteria,
)

ROOT = Path(__file__).resolve().parent.parent
STOCK_LIST_PATH = ROOT / "Stock_List.txt"
ACTION_PRIORITY = {"ADD": 0, "HOLD": 1, "TRIM": 2, "SELL": 3}


def collect_both(entry: dict):
    df = fetch_ohlcv(entry, days=HISTORY_DAYS)
    data = calculate_indicators(df)
    data = add_candle_features(data)
    data = add_daily_trim_signal(data)
    data = add_rsi_cross(data, "_D")
    clean = data.dropna(subset=["SMA20", "SMA200", "RSI14", "Band_Pct"])
    target_price, _, _ = get_target_price(entry, data)

    n = len(clean)
    max_horizon_days = max(h for h, _ in HORIZONS.values())
    d_records, s_records = [], []
    d_scores, s_scores = [], []
    d_actions, s_actions = [], []

    for i in range(0, n - max_horizon_days, SAMPLE_STEP):
        row = clean.iloc[i]
        entry_price = row["Close"]
        rets = {}
        for hname, (hdays, _theta) in HORIZONS.items():
            fwd_price = clean.iloc[i + hdays]["Close"]
            rets[hname] = (fwd_price - entry_price) / entry_price * 100

        long_t = classify_long_trend(row)
        mid_t = classify_mid_trend(row)
        extra = {
            "trim_confirmed_d": bool_at(row, "TrimConfirmed"),
            "rsi_crossdown70_d": bool_at(row, "RSI_CrossDown70_D"),
            "rsi_crossup30_d": bool_at(row, "RSI_CrossUp30_D"),
        }

        d_score = score_latest(row, target_price)
        d_action = decide_action(row, d_score, long_t, mid_t, extra)["action"]
        d_records.append({"action": d_action, **{f"ret_{h}": rets[h] for h in HORIZONS}})
        d_scores.append(d_score["adjusted_score"])
        d_actions.append(d_action)

        s_score = score_latest_smooth(row, target_price)
        s_action = decide_action(row, s_score, long_t, mid_t, extra)["action"]
        s_records.append({"action": s_action, **{f"ret_{h}": rets[h] for h in HORIZONS}})
        s_scores.append(s_score["adjusted_score"])
        s_actions.append(s_action)

    return d_records, s_records, d_scores, s_scores, d_actions, s_actions


def stability_stats(scores_seq: list[float], actions_seq: list[str]) -> dict:
    """종목 하나의 시계열 안에서 연속 샘플(약 1주 간격) 사이의 변동폭/급변 비율."""
    score_diffs = [abs(scores_seq[i] - scores_seq[i - 1]) for i in range(1, len(scores_seq))]
    flip_dists = [abs(ACTION_PRIORITY[actions_seq[i]] - ACTION_PRIORITY[actions_seq[i - 1]])
                  for i in range(1, len(actions_seq))]
    severe = sum(1 for d in flip_dists if d >= 2)
    return {
        "score_diffs": score_diffs,
        "n_transitions": len(flip_dists),
        "severe_flips": severe,
    }


def report_returns(name: str, records: list[dict]) -> dict:
    print("\n" + "=" * 78)
    print(f" {name} - 수익률 ({PRIMARY_HORIZON} 기준, 표본 {len(records)}개)")
    print("=" * 78)
    theta = HORIZONS[PRIMARY_HORIZON][1]
    summary, baseline = aggregate(records, PRIMARY_HORIZON, theta)
    print_horizon_report(PRIMARY_HORIZON, theta, summary, baseline, len(records))
    checks, overall_pass = evaluate_pass_criteria(summary, baseline)
    n_pass = sum(1 for _, ok, _ in checks if ok)
    n_decidable = sum(1 for _, ok, _ in checks if ok is not None)
    print(f"  PASS {n_pass}/{n_decidable} -> {'PASS' if overall_pass else 'FAIL'}")
    add_s = summary.get("ADD")
    return {"n_pass": n_pass, "add_ret": add_s["avg_ret"] if add_s else None, "add_n": add_s["n"] if add_s else 0}


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    entries = load_stock_list(STOCK_LIST_PATH)
    all_d_records, all_s_records = [], []
    all_score_diffs_d, all_score_diffs_s = [], []
    total_transitions = 0
    total_severe_d, total_severe_s = 0, 0

    print(f"계단식 vs 연속채점 비교 시작 - {len(entries)}개 종목, 과거 {HISTORY_DAYS}일...\n")
    for i, entry in enumerate(entries, 1):
        try:
            d_rec, s_rec, d_sc, s_sc, d_ac, s_ac = collect_both(entry)
            all_d_records.extend(d_rec)
            all_s_records.extend(s_rec)

            d_stab = stability_stats(d_sc, d_ac)
            s_stab = stability_stats(s_sc, s_ac)
            all_score_diffs_d.extend(d_stab["score_diffs"])
            all_score_diffs_s.extend(s_stab["score_diffs"])
            total_transitions += d_stab["n_transitions"]
            total_severe_d += d_stab["severe_flips"]
            total_severe_s += s_stab["severe_flips"]

            print(f"[{i}/{len(entries)}] {entry['name']} ({entry['code']}): 표본 {len(d_rec)}개")
        except Exception as e:
            print(f"[{i}/{len(entries)}] {entry['name']} ({entry['code']}): 실패 - {type(e).__name__}: {e}")

    r_discrete = report_returns("① 계단식 (기존)", all_d_records)
    r_smooth = report_returns("② 연속·선형보간 (신규)", all_s_records)

    print("\n" + "=" * 78)
    print(" 안정성 비교 (연속된 주간 샘플 사이 변동폭)")
    print("=" * 78)
    for name, diffs, severe in [("① 계단식", all_score_diffs_d, total_severe_d),
                                 ("② 연속·선형보간", all_score_diffs_s, total_severe_s)]:
        avg_d = statistics.mean(diffs) if diffs else 0.0
        p90 = statistics.quantiles(diffs, n=10)[8] if len(diffs) >= 10 else max(diffs, default=0.0)
        max_d = max(diffs, default=0.0)
        severe_rate = severe / total_transitions * 100 if total_transitions else 0.0
        print(f"  {name}: 평균 |Δ점수|={avg_d:.2f}, 상위10% |Δ점수|={p90:.2f}, 최대={max_d:.2f}, "
              f"급변(HOLD 건너뛰는 액션전환) 비율={severe_rate:.1f}% (n={total_transitions})")

    print("\n" + "=" * 78)
    print(" 최종 요약")
    print("=" * 78)
    print(f"  ① 계단식        : ADD 평균수익률={r_discrete['add_ret']:+.2f}% (n={r_discrete['add_n']}), "
          f"PASS {r_discrete['n_pass']}/5, 평균변동폭={statistics.mean(all_score_diffs_d):.2f}, "
          f"급변비율={total_severe_d/total_transitions*100:.1f}%")
    print(f"  ② 연속·선형보간 : ADD 평균수익률={r_smooth['add_ret']:+.2f}% (n={r_smooth['add_n']}), "
          f"PASS {r_smooth['n_pass']}/5, 평균변동폭={statistics.mean(all_score_diffs_s):.2f}, "
          f"급변비율={total_severe_s/total_transitions*100:.1f}%")


if __name__ == "__main__":
    main()
