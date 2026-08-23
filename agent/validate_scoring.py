"""과거 시점 신호(액션) 사후 검증 백테스트.

대시보드와 무관하게 콘솔 출력 전용. 각 종목의 과거 데이터를 약 1주일 간격으로
훑으며 그 시점 기준 액션(ADD/HOLD/TRIM/SELL)을 재계산하고, 이후 1개월/3개월
수익률로 그 액션이 맞았는지 채점한다.

한계:
- 목표가는 현재 시점 값을 과거 시점에도 동일하게 적용한 근사치 (과거 컨센서스
  데이터는 확보하지 않음). 총점 중 목표가 괴리 팩터(15점)에만 영향을 준다.
- 주간 샘플이라 인접 신호끼리 자기상관이 있어 엄밀한 i.i.d. 표본은 아니다.
- 과열/RSI 크로스 시그널은 일봉 기준만 반영한다 (주봉은 특정 과거 시점 기준
  룩어헤드 없는 정렬이 번거로워 백테스트에서는 제외 - 라이브 대시보드는 주봉도 반영).
"""
import statistics
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from stock_list import load_stock_list
from data_fetcher import fetch_ohlcv, get_target_price
from indicators import calculate_indicators
from scoring_smooth import score_latest_smooth_v2 as score_latest
from signal_engine import decide_action, classify_long_trend, classify_mid_trend
from events import add_candle_features, add_daily_trim_signal, add_rsi_cross, bool_at

ROOT = Path(__file__).resolve().parent.parent
STOCK_LIST_PATH = ROOT / "Stock_List.txt"

# horizon 이름 -> (거래일수, 유의미한 변동으로 볼 임계값 %)
HORIZONS = {"1M": (21, 6.0), "3M": (63, 10.0)}
PRIMARY_HORIZON = "1M"
SAMPLE_STEP = 5          # 약 1주 간격 샘플링
HISTORY_DAYS = 760       # 약 2년치: 200일선 warmup + 3개월 forward 확보용
ACTIONS = ["ADD", "HOLD", "TRIM", "SELL"]


def score_action_point(action: str, ret: float, theta: float) -> int:
    if action == "ADD":
        if ret >= theta:
            return 2
        if ret <= -theta:
            return -2
        return 0
    if action == "SELL":
        if ret <= -theta:
            return 2
        if ret >= theta:
            return -2
        return 0
    if action == "TRIM":
        return -1 if ret >= theta else 1
    if action == "HOLD":
        if ret <= -theta:
            return -2
        if ret >= theta:
            return 1
        return 0
    return 0


def collect_samples(entry: dict) -> list[dict]:
    """종목별 과거 표본의 원재료(점수/추세/신호/구간수익률)를 액션 결정 없이 수집한다.

    액션(ADD/HOLD/TRIM/SELL)은 여기서 확정하지 않는다 - 파라미터 튜닝 실험에서
    동일 표본에 서로 다른 add_threshold/sell_threshold를 대입해 재사용하기 위함.
    """
    df = fetch_ohlcv(entry, days=HISTORY_DAYS)
    data = calculate_indicators(df)
    data = add_candle_features(data)
    data = add_daily_trim_signal(data)
    data = add_rsi_cross(data, "_D")
    clean = data.dropna(subset=["SMA20", "SMA200", "RSI14", "Band_Pct"])
    target_price, _, _ = get_target_price(entry, data)

    n = len(clean)
    max_horizon_days = max(h for h, _ in HORIZONS.values())
    samples = []
    for i in range(0, n - max_horizon_days, SAMPLE_STEP):
        row = clean.iloc[i]
        score = score_latest(row, target_price)
        long_t = classify_long_trend(row)
        mid_t = classify_mid_trend(row)
        extra = {
            "trim_confirmed_d": bool_at(row, "TrimConfirmed"),
            "rsi_crossdown70_d": bool_at(row, "RSI_CrossDown70_D"),
            "rsi_crossup30_d": bool_at(row, "RSI_CrossUp30_D"),
        }
        entry_price = row["Close"]
        sample = {
            "ticker": entry["name"], "code": entry["code"], "date": row.name,
            "row": row, "score": score, "long_trend": long_t, "mid_trend": mid_t, "extra": extra,
        }
        for hname, (hdays, _theta) in HORIZONS.items():
            fwd_price = clean.iloc[i + hdays]["Close"]
            sample[f"ret_{hname}"] = (fwd_price - entry_price) / entry_price * 100
        samples.append(sample)
    return samples


def backtest_ticker(entry: dict, add_threshold: float = 70.0, sell_threshold: float = 40.0) -> list[dict]:
    samples = collect_samples(entry)
    records = []
    for s in samples:
        decision = decide_action(s["row"], s["score"], s["long_trend"], s["mid_trend"], s["extra"],
                                  add_threshold=add_threshold, sell_threshold=sell_threshold)
        rec = {"ticker": s["ticker"], "code": s["code"], "date": s["date"], "action": decision["action"]}
        for hname in HORIZONS:
            rec[f"ret_{hname}"] = s[f"ret_{hname}"]
        records.append(rec)
    return records


def records_from_samples(samples: list[dict], add_threshold: float, sell_threshold: float) -> list[dict]:
    """이미 수집된 samples에 다른 임계값을 대입해 액션만 재계산 (튜닝 실험용, 재수집 없음)."""
    records = []
    for s in samples:
        decision = decide_action(s["row"], s["score"], s["long_trend"], s["mid_trend"], s["extra"],
                                  add_threshold=add_threshold, sell_threshold=sell_threshold)
        rec = {"action": decision["action"]}
        for hname in HORIZONS:
            rec[f"ret_{hname}"] = s[f"ret_{hname}"]
        records.append(rec)
    return records


def aggregate(records: list[dict], hname: str, theta: float) -> tuple[dict, float]:
    baseline_rets = [r[f"ret_{hname}"] for r in records]
    baseline = statistics.mean(baseline_rets) if baseline_rets else 0.0

    by_action = {a: [] for a in ACTIONS}
    for r in records:
        ret = r[f"ret_{hname}"]
        pt = score_action_point(r["action"], ret, theta)
        by_action[r["action"]].append((ret, pt))

    summary = {}
    for action, vals in by_action.items():
        if not vals:
            summary[action] = None
            continue
        rets = [v[0] for v in vals]
        pts = [v[1] for v in vals]
        wins = sum(1 for p in pts if p > 0)
        losses = sum(1 for p in pts if p < 0)
        neutral = sum(1 for p in pts if p == 0)
        decided = wins + losses
        summary[action] = {
            "n": len(vals),
            "avg_ret": statistics.mean(rets),
            "avg_pt": statistics.mean(pts),
            "wins": wins, "losses": losses, "neutral": neutral,
            "win_rate": (wins / decided * 100) if decided else None,
        }
    return summary, baseline


def print_horizon_report(hname: str, theta: float, summary: dict, baseline: float, total_n: int):
    print(f"\n--- {hname} 수익률 기준 (임계값 θ=±{theta:.0f}%, 전체 표본 baseline 평균수익률={baseline:+.2f}%, n={total_n}) ---")
    header = f"{'액션':6}{'표본수':>7}{'평균수익률':>12}{'평균점수':>10}{'승':>5}{'중립':>6}{'패':>5}{'승률':>8}"
    print(header)
    for action in ACTIONS:
        s = summary.get(action)
        if not s:
            print(f"{action:6}{'0':>7}{'-':>12}{'-':>10}{'-':>5}{'-':>6}{'-':>5}{'-':>8}")
            continue
        win_rate_str = f"{s['win_rate']:.0f}%" if s["win_rate"] is not None else "-"
        print(f"{action:6}{s['n']:>7}{s['avg_ret']:>+11.2f}%{s['avg_pt']:>+9.2f}{s['wins']:>5}{s['neutral']:>6}{s['losses']:>5}{win_rate_str:>8}")


def evaluate_pass_criteria(summary: dict, baseline: float) -> tuple[list[tuple[str, bool, str]], bool]:
    add_s, sell_s, hold_s = summary.get("ADD"), summary.get("SELL"), summary.get("HOLD")
    checks = []

    add_ret = add_s["avg_ret"] if add_s else None
    sell_ret = sell_s["avg_ret"] if sell_s else None

    if add_ret is None or sell_ret is None:
        checks.append(("① ADD 평균수익률 > SELL 평균수익률 (방향성 분별력)", None, "표본 부족"))
    else:
        checks.append(("① ADD 평균수익률 > SELL 평균수익률 (방향성 분별력)",
                        add_ret > sell_ret, f"ADD={add_ret:+.2f}% vs SELL={sell_ret:+.2f}%"))

    if add_ret is None:
        checks.append(("② ADD 평균수익률 > baseline", None, "표본 부족"))
    else:
        checks.append(("② ADD 평균수익률 > baseline", add_ret > baseline, f"ADD={add_ret:+.2f}% vs baseline={baseline:+.2f}%"))

    if sell_ret is None:
        checks.append(("③ SELL 평균수익률 < baseline", None, "표본 부족"))
    else:
        checks.append(("③ SELL 평균수익률 < baseline", sell_ret < baseline, f"SELL={sell_ret:+.2f}% vs baseline={baseline:+.2f}%"))

    if hold_s and hold_s["n"] > 0:
        collapse_rate = hold_s["losses"] / hold_s["n"] * 100
        checks.append(("④ HOLD 중 '붕괴 방치' 비율 < 20%", collapse_rate < 20.0, f"{collapse_rate:.0f}%"))
    else:
        checks.append(("④ HOLD 중 '붕괴 방치' 비율 < 20%", None, "표본 부족"))

    add_wl = (add_s["wins"] + add_s["losses"]) if add_s else 0
    sell_wl = (sell_s["wins"] + sell_s["losses"]) if sell_s else 0
    combined_wins = (add_s["wins"] if add_s else 0) + (sell_s["wins"] if sell_s else 0)
    combined_decided = add_wl + sell_wl
    if combined_decided > 0:
        combined_win_rate = combined_wins / combined_decided * 100
        c5 = combined_win_rate >= 55.0
        checks.append(("⑤ ADD+SELL 통합 승률(중립 제외) ≥ 55%", c5, f"{combined_win_rate:.0f}% (n={combined_decided})"))
    else:
        checks.append(("⑤ ADD+SELL 통합 승률(중립 제외) ≥ 55%", None, "표본 부족"))

    passed = sum(1 for _, ok, _ in checks if ok)
    decidable = sum(1 for _, ok, _ in checks if ok is not None)
    overall_pass = decidable > 0 and passed >= 4
    return checks, overall_pass


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    entries = load_stock_list(STOCK_LIST_PATH)
    all_records = []
    failures = []

    print(f"과거 {HISTORY_DAYS}일 데이터로 {len(entries)}개 종목 롤링 백테스트 시작 (약 {SAMPLE_STEP}거래일 간격 샘플링)...\n")
    for i, entry in enumerate(entries, 1):
        try:
            recs = backtest_ticker(entry)
            all_records.extend(recs)
            print(f"[{i}/{len(entries)}] {entry['name']} ({entry['code']}): 표본 {len(recs)}개")
        except Exception as e:
            failures.append((entry, e))
            print(f"[{i}/{len(entries)}] {entry['name']} ({entry['code']}): 실패 - {type(e).__name__}: {e}")
            traceback.print_exc(limit=1)

    if failures:
        print(f"\n{len(failures)}개 종목 데이터 수집 실패, {len(entries) - len(failures)}개 종목으로 검증 진행")

    print("\n" + "=" * 78)
    print(" 종목 통합 결과 (24개 종목의 모든 과거 신호를 합산)")
    print("=" * 78)

    horizon_summaries = {}
    for hname, (_hdays, theta) in HORIZONS.items():
        summary, baseline = aggregate(all_records, hname, theta)
        horizon_summaries[hname] = (summary, baseline)
        print_horizon_report(hname, theta, summary, baseline, len(all_records))

    print("\n" + "=" * 78)
    print(f" PASS/FAIL 판정 (주 horizon: {PRIMARY_HORIZON})")
    print("=" * 78)
    primary_summary, primary_baseline = horizon_summaries[PRIMARY_HORIZON]
    checks, overall_pass = evaluate_pass_criteria(primary_summary, primary_baseline)
    for name, ok, detail in checks:
        mark = "N/A " if ok is None else ("PASS" if ok else "FAIL")
        print(f"  [{mark}] {name}  ({detail})")
    n_pass = sum(1 for _, ok, _ in checks if ok)
    n_decidable = sum(1 for _, ok, _ in checks if ok is not None)
    print(f"\n  총 {n_pass}/{n_decidable}(판정 가능한 항목 중) 충족 -> 종합 판정: {'PASS' if overall_pass else 'FAIL'}")

    print("\n[참고] 3개월(3M) horizon 결과는 위 표를 참고만 하고 최종 판정에는 반영하지 않음.")
    print("[한계] 목표가는 현재 시점 값을 과거 시점에도 동일 적용한 근사치이며, 주간 샘플 간 자기상관이 존재함.")


if __name__ == "__main__":
    main()
