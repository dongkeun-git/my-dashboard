"""추세 판정 매트릭스 + 매매 액션 의사결정 트리."""
import pandas as pd


def classify_long_trend(row: pd.Series) -> str:
    if pd.isna(row.get("SMA200")) or pd.isna(row.get("SMA200_slope")):
        return "Neutral"
    if row["Close"] > row["SMA200"] and row["SMA200_slope"] > 0:
        return "Bullish"
    if row["Close"] < row["SMA200"] and row["SMA200_slope"] < 0:
        return "Bearish"
    return "Neutral"


def classify_mid_trend(row: pd.Series) -> str:
    disp60 = row.get("Disparity60")
    if pd.notna(disp60) and 98 <= disp60 <= 102:
        return "Neutral"
    if pd.isna(row.get("SMA60_slope")) or pd.isna(row.get("OBV_SMA20")):
        return "Neutral"
    if row["SMA60_slope"] > 0 and row["OBV"] > row["OBV_SMA20"]:
        return "Bullish"
    if row["SMA60_slope"] < 0 and row["OBV"] < row["OBV_SMA20"]:
        return "Bearish"
    return "Neutral"


def classify_short_trend(row: pd.Series) -> str:
    disp20 = row.get("Disparity20")
    if pd.isna(row.get("SMA5")) or pd.isna(row.get("SMA20")) or pd.isna(disp20):
        return "Neutral"
    if row["SMA5"] > row["SMA20"] and disp20 > 100:
        return "Bullish"
    if row["SMA5"] < row["SMA20"] and disp20 < 100:
        return "Bearish"
    return "Neutral"


def decide_action(row: pd.Series, score: dict, long_trend: str, mid_trend: str, extra: dict | None = None,
                   add_threshold: float = 70.0, sell_threshold: float = 40.0) -> dict:
    """extra: {trim_confirmed_d, rsi_crossdown70_d, rsi_crossdown70_w, rsi_crossup30_d, rsi_crossup30_w}
    (일봉 밴드상단돌파+반전캔들/5일선이탈 확정, 일봉·주봉 RSI 70/30 크로스). 없으면 전부 False로 간주.
    add_threshold/sell_threshold: ADD/TRIM 및 HOLD/SELL을 가르는 총점 컷오프 (파라미터 튜닝 실험용, 기본 75/45).
    """
    extra = extra or {}
    adj = score["adjusted_score"]
    is_up_day = row["Close"] > row["Open"]

    # 과열 확정: 밴드 상단 돌파 후 반전 패턴 확정, 또는 일봉/주봉 RSI 70 하향 돌파
    overheat_confirmed = bool(
        extra.get("trim_confirmed_d") or extra.get("rsi_crossdown70_d") or extra.get("rsi_crossdown70_w")
    )
    # 저점 확인: 일봉/주봉 RSI 30 상향 돌파
    bottom_confirmed = bool(extra.get("rsi_crossup30_d") or extra.get("rsi_crossup30_w"))

    action, reason = None, None

    if adj >= add_threshold:
        if overheat_confirmed:
            action = "TRIM"
            reason = f"총점 {adj:.0f}점, 과열 후 반전 확정(밴드상단 돌파+5일선 이탈/반전캔들 또는 RSI 70 하향돌파) → 30~50% 분할 익절"
        elif long_trend == "Bullish" and mid_trend == "Bullish":
            action = "ADD"
            reason = f"총점 {adj:.0f}점, 장·중기 상승추세 & 반전 신호 없음 → 추가 매수"
        else:
            action = "HOLD"
            reason = f"총점 {adj:.0f}점({add_threshold:.0f}점 이상)이나 장·중기 추세 미확정 → 보유 관망"
    elif adj >= sell_threshold:
        if overheat_confirmed:
            action = "TRIM"
            reason = f"총점 {adj:.0f}점, 과열 후 반전 확정 → 30~50% 분할 익절"
        else:
            action = "HOLD"
            reason = f"총점 {adj:.0f}점, 중기 추세 훼손 없음 → 보유"
    else:
        if bottom_confirmed:
            action = "HOLD"
            reason = f"총점 {adj:.0f}점({sell_threshold:.0f}점 미만)이나 RSI 저점확인 신호(30 상향돌파) 포착 → 매도 보류, 반등 관찰"
        else:
            action = "SELL"
            reason = f"총점 {adj:.0f}점({sell_threshold:.0f}점 미만) → 비중 축소/손절 검토"

    # 하드 오버라이드 (점수 구간과 무관하게 강제 SELL, 저점확인 신호로도 완화하지 않음)
    if row["Close"] < row.get("SMA200", float("-inf")):
        if action != "SELL":
            reason = f"[오버라이드] 총점 {adj:.0f}점이나 200일선 이탈(종가 {row['Close']:.0f} < SMA200 {row['SMA200']:.0f}) → 매도/비중 축소"
        action = "SELL"
    elif (not is_up_day) and row["Vol_Ratio"] >= 1.5 and row["OBV"] < row["OBV_SMA20"]:
        if action != "SELL":
            reason = f"[오버라이드] 총점 {adj:.0f}점이나 대량 거래 하락 + OBV 20MA 붕괴 → 매도/비중 축소"
        action = "SELL"

    return {"action": action, "reason": reason}


def build_signal(row: pd.Series, score: dict, extra: dict | None = None,
                  add_threshold: float = 70.0, sell_threshold: float = 40.0) -> dict:
    long_t = classify_long_trend(row)
    mid_t = classify_mid_trend(row)
    short_t = classify_short_trend(row)
    decision = decide_action(row, score, long_t, mid_t, extra, add_threshold, sell_threshold)
    return {
        "long_trend": long_t,
        "mid_trend": mid_t,
        "short_trend": short_t,
        **decision,
    }
