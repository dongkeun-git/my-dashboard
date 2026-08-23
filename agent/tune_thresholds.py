"""ADD/SELL 액션 컷오프(총점 임계값) 파라미터 튜닝 실험.

가설: 100점 배점표의 세부 항목(RSI 구간, Band% 구간 등)보다, 총점을 액션으로
변환하는 두 컷오프(ADD 임계값=기본 75, SELL 임계값=기본 45)가 수익률에 훨씬
민감하다 - 총점 몇 점 차이로 표본이 통째로 다른 액션 버킷에 재분류되기 때문.
세부 배점 항목 하나를 조정하면 총점이 몇 점 흔들리는 정도지만, 컷오프 자체를
옮기면 그 근방의 모든 표본이 한번에 액션을 바꾼다.

이 스크립트는 이미 수집한 과거 표본(점수/추세/신호/구간수익률)에 서로 다른
(add_threshold, sell_threshold) 조합을 대입해 액션만 재계산하는 방식이라
데이터 재수집 없이 빠르게 그리드 서치를 수행한다.
"""
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from stock_list import load_stock_list
from validate_scoring import (
    collect_samples, records_from_samples, aggregate, evaluate_pass_criteria,
    HORIZONS, PRIMARY_HORIZON, HISTORY_DAYS,
)

ROOT = Path(__file__).resolve().parent.parent
STOCK_LIST_PATH = ROOT / "Stock_List.txt"

ADD_CANDIDATES = [70.0, 75.0, 80.0]
SELL_CANDIDATES = [40.0, 45.0, 50.0]
MIN_SAMPLE = 30  # 이보다 표본이 적은 조합은 우연성이 커서 최적으로 채택하지 않음


def print_sensitivity_evidence(all_samples: list[dict]):
    scores = [s["score"]["adjusted_score"] for s in all_samples]
    near_75 = sum(1 for v in scores if 70 <= v <= 80)
    near_45 = sum(1 for v in scores if 40 <= v <= 50)
    rsi_vals = [s["row"]["RSI14"] for s in all_samples]
    near_rsi75 = sum(1 for v in rsi_vals if 70 <= v <= 80)
    band_vals = [s["row"]["Band_Pct"] for s in all_samples]
    near_band08 = sum(1 for v in band_vals if 0.75 <= v <= 0.85)

    print("\n" + "=" * 78)
    print(" 파라미터 민감도 근거 (컷오프 근접 표본 밀집도)")
    print("=" * 78)
    print(f"  총점 70~80 구간(ADD 임계값=75 근방) 표본: {near_75}개 / 전체 {len(scores)}개")
    print(f"  총점 40~50 구간(SELL 임계값=45 근방) 표본: {near_45}개 / 전체 {len(scores)}개")
    print(f"  (비교) RSI 70~80 구간(모멘텀 세부 구간 경계) 표본: {near_rsi75}개")
    print(f"  (비교) Band% 0.75~0.85 구간(밴드 세부 구간 경계) 표본: {near_band08}개")
    print("  -> ADD/SELL 컷오프 근방에 표본이 더 밀집 -> 작은 이동에도 더 많은 표본이 액션을 바꿔 수익률에 민감함")


def run_grid(all_samples: list[dict]):
    theta = HORIZONS[PRIMARY_HORIZON][1]
    results = []
    print("\n" + "=" * 78)
    print(f" 그리드 서치 결과 ({PRIMARY_HORIZON} 기준, θ=±{theta:.0f}%)")
    print("=" * 78)
    header = f"{'ADD임계':>7}{'SELL임계':>8}{'ADD n':>7}{'ADD수익률':>11}{'ADD승률':>8}{'SELL n':>8}{'SELL수익률':>12}{'SELL승률':>9}{'스프레드':>10}{'PASS':>6}"
    print(header)
    for add_th in ADD_CANDIDATES:
        for sell_th in SELL_CANDIDATES:
            records = records_from_samples(all_samples, add_th, sell_th)
            summary, baseline = aggregate(records, PRIMARY_HORIZON, theta)
            add_s, sell_s = summary.get("ADD"), summary.get("SELL")
            checks, _ = evaluate_pass_criteria(summary, baseline)
            n_pass = sum(1 for _, ok, _ in checks if ok)

            add_n = add_s["n"] if add_s else 0
            sell_n = sell_s["n"] if sell_s else 0
            add_ret = add_s["avg_ret"] if add_s else None
            sell_ret = sell_s["avg_ret"] if sell_s else None
            add_wr = add_s["win_rate"] if add_s else None
            sell_wr = sell_s["win_rate"] if sell_s else None
            spread = (add_ret - sell_ret) if (add_ret is not None and sell_ret is not None) else None

            results.append({
                "add_th": add_th, "sell_th": sell_th, "add_n": add_n, "sell_n": sell_n,
                "add_ret": add_ret, "sell_ret": sell_ret, "add_wr": add_wr, "sell_wr": sell_wr,
                "spread": spread, "baseline": baseline, "n_pass": n_pass,
            })

            fmt_signed = lambda v: (f"{v:+.2f}%" if v is not None else "-")
            fmt_rate = lambda v: (f"{v:.0f}%" if v is not None else "-")
            print(f"{add_th:>7.0f}{sell_th:>8.0f}{add_n:>7}{fmt_signed(add_ret):>11}"
                  f"{fmt_rate(add_wr):>8}{sell_n:>8}{fmt_signed(sell_ret):>12}"
                  f"{fmt_rate(sell_wr):>9}{fmt_signed(spread):>10}{n_pass:>6}")
    return results


def pick_best(results: list[dict]) -> dict:
    """PASS 개수(전체적 견고성)를 최우선으로, 동률이면 ADD 평균수익률로 tie-break.
    ADD 평균수익률만 극대화하면 임계값을 올릴수록 표본이 급감하면서(예: n=829->467)
    근소한 수익률 개선과 표본 신뢰도를 맞바꾸는 함정에 빠지기 쉽다 - PASS 개수가
    이 트레이드오프를 반영하는 더 종합적인 지표라 우선순위를 둔다.
    """
    eligible = [r for r in results if r["add_n"] >= MIN_SAMPLE and r["sell_n"] >= MIN_SAMPLE
                and r["add_ret"] is not None and r["sell_ret"] is not None
                and r["sell_ret"] < r["baseline"]]
    pool = eligible if eligible else [r for r in results if r["add_ret"] is not None]
    return max(pool, key=lambda r: (r["n_pass"], r["add_ret"]))


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

    entries = load_stock_list(STOCK_LIST_PATH)
    all_samples = []
    print(f"과거 {HISTORY_DAYS}일 데이터로 {len(entries)}개 종목 표본 수집 중 (임계값 조합마다 재수집하지 않고 1회만 수집)...\n")
    for i, entry in enumerate(entries, 1):
        try:
            samples = collect_samples(entry)
            all_samples.extend(samples)
            print(f"[{i}/{len(entries)}] {entry['name']} ({entry['code']}): 표본 {len(samples)}개")
        except Exception as e:
            print(f"[{i}/{len(entries)}] {entry['name']} ({entry['code']}): 실패 - {type(e).__name__}: {e}")

    print_sensitivity_evidence(all_samples)
    results = run_grid(all_samples)
    best = pick_best(results)

    print("\n" + "=" * 78)
    print(" 최적 조합 (기준: SELL 평균수익률 < baseline 유지 + ADD 평균수익률 최대화, 표본수 >= "
          f"{MIN_SAMPLE})")
    print("=" * 78)
    print(f"  ADD 임계값 = {best['add_th']:.0f}점, SELL 임계값 = {best['sell_th']:.0f}점")
    print(f"  ADD: n={best['add_n']}, 평균수익률={best['add_ret']:+.2f}%, 승률={best['add_wr']:.0f}%" if best['add_wr'] is not None else "")
    print(f"  SELL: n={best['sell_n']}, 평균수익률={best['sell_ret']:+.2f}% (baseline {best['baseline']:+.2f}%)")
    print(f"  방향성 스프레드(ADD-SELL) = {best['spread']:+.2f}%p, PASS 판정 {best['n_pass']}/5")

    default = next((r for r in results if r["add_th"] == 75.0 and r["sell_th"] == 45.0), None)
    if default:
        print(f"\n  [비교] 기존 기본값(75/45): ADD 평균수익률={default['add_ret']:+.2f}%, "
              f"SELL 평균수익률={default['sell_ret']:+.2f}%, 스프레드={default['spread']:+.2f}%p, PASS {default['n_pass']}/5")

    if best["add_th"] == 75.0 and best["sell_th"] == 45.0:
        print("\n  결론: 기존 기본값(75/45)이 후보 중 최선이므로 변경하지 않습니다.")
    else:
        print(f"\n  결론: ({best['add_th']:.0f}/{best['sell_th']:.0f})가 기존 기본값보다 우수하여 signal_engine.py 기본값 교체를 권장합니다.")


if __name__ == "__main__":
    main()
