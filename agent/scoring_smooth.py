"""연속(선형보간) 채점 버전 - 기존 scoring.py의 계단식 버킷을 부드러운 램프로 대체.

원본 계단식 규칙의 각 구간 경계값에서의 점수를 그대로 anchor(고정점)로 삼고,
경계 사이는 직선 보간한다 - 모델의 "의도"(어느 구간이 몇 점인가)는 보존하면서
경계선 바로 옆에서 발생하는 급격한 점프만 제거하는 목적.

이평선 정배열(범주형), OBV 크로스(이분법), 거래량배수(상승/하락일 분기)는 구조적으로
연속값이 아니라 스무딩 대상에서 제외 - 기존 scoring.py와 동일한 로직을 그대로 재사용.
"""
import pandas as pd

from scoring import _volume_score  # 거래량 팩터는 원본 그대로 재사용


def piecewise_linear(x: float, points: list[tuple[float, float]]) -> float:
    """points: (x, y) 오름차순 정렬된 anchor 목록. 양 끝을 벗어나면 flat 외삽."""
    if x <= points[0][0]:
        return points[0][1]
    if x >= points[-1][0]:
        return points[-1][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 <= x <= x1:
            if x1 == x0:
                return y0
            t = (x - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return points[-1][1]


DISPARITY20_ANCHORS = [(85, 0), (95, 3), (100, 10), (106, 10), (112, 5), (115, 3), (125, 0)]
RSI_ANCHORS = [(30, 5), (40, 8), (50, 15), (65, 15), (75, 10), (80, 0)]
BAND_PCT_ANCHORS = [(0.4, 0), (0.5, 10), (0.8, 10), (1.0, 2)]
UPSIDE_ANCHORS = [(0, 0), (5, 5), (15, 10), (25, 15)]
# OBV z-score(20일 표준편차 기준) 램프: 크로스 지점(z=0)에서 절반 점수, ±1표준편차에서 양끝값.
OBV_Z_ANCHORS = [(-1.0, 0), (0.0, 7.5), (1.0, 15)]


def _volume_score_smooth(row) -> float:
    """OBV 이분법(0/15점)을 OBV-OBV20일선 격차의 z-score 램프로 대체. Vol_Ratio 부분은 원본과 동일."""
    obv, obv_sma, obv_std = row["OBV"], row["OBV_SMA20"], row.get("OBV_STD20")
    if obv_std is None or pd.isna(obv_std) or obv_std == 0:
        pts = 15 if obv > obv_sma else 0
    else:
        z = (obv - obv_sma) / obv_std
        pts = piecewise_linear(z, OBV_Z_ANCHORS)

    is_up = row["Close"] > row["Open"]
    vr = row["Vol_Ratio"]
    if is_up and vr >= 1.5:
        pts += 10
    elif is_up and vr >= 0.8:
        pts += 6
    elif (not is_up) and vr >= 1.5:
        pts -= 5
    return pts


def _trend_strength_score_smooth(row) -> float:
    full_aligned = row["SMA5"] > row["SMA20"] > row["SMA60"] > row["SMA200"]
    short_aligned = row["SMA5"] > row["SMA20"] > row["SMA60"]
    pts = 15 if full_aligned else (10 if short_aligned else 0)  # 정배열은 범주형 그대로

    pts += piecewise_linear(row["Disparity20"], DISPARITY20_ANCHORS)
    pts += 10 if row["Close"] > row["SMA200"] else 0
    return pts


def _momentum_score_smooth(row) -> float:
    pts = piecewise_linear(row["RSI14"], RSI_ANCHORS)
    pts += piecewise_linear(row["Band_Pct"], BAND_PCT_ANCHORS)
    return pts


def _target_score_smooth(upside_pct: float) -> float:
    return piecewise_linear(upside_pct, UPSIDE_ANCHORS)


def _finalize_score(trend: float, momentum: float, volume: float, target: float, row: pd.Series) -> dict:
    """추세/모멘텀/수급/목표가 하위점수가 정해진 뒤의 공통 처리(ADX 동적가중치 + 합산)."""
    base_score = max(0.0, min(100.0, trend + momentum + volume + target))

    adx = row.get("ADX14", float("nan"))
    shift = 0.0
    if pd.notna(adx):
        if adx < 20:
            shift = min(5.0, trend * (5.0 / 35.0))
            trend_adj, momentum_adj, volume_adj = trend - shift, momentum + shift, volume
        elif adx > 25:
            shift = min(5.0, (momentum + volume) * (5.0 / 50.0))
            trend_adj = trend + shift
            take = min(shift, momentum)
            momentum_adj = momentum - take
            volume_adj = volume - (shift - take)
        else:
            trend_adj, momentum_adj, volume_adj = trend, momentum, volume
    else:
        trend_adj, momentum_adj, volume_adj = trend, momentum, volume

    adjusted_score = max(0.0, min(100.0, trend_adj + momentum_adj + volume_adj + target))

    return {
        "trend_score": trend,
        "momentum_score": momentum,
        "volume_score": volume,
        "target_score": target,
        "base_score": round(base_score, 1),
        "adjusted_score": round(adjusted_score, 1),
        "adx_shift": round(shift, 1),
    }


def score_latest_smooth(row: pd.Series, target_price: float) -> dict:
    """숫자형 지표(RSI/Band%/이격도/목표가 괴리율)만 연속화한 버전. OBV/Vol比는 원본 그대로."""
    trend = _trend_strength_score_smooth(row)
    momentum = _momentum_score_smooth(row)
    volume = _volume_score(row)
    upside_pct = (target_price - row["Close"]) / row["Close"] * 100
    target = _target_score_smooth(upside_pct)
    return {**_finalize_score(trend, momentum, volume, target, row), "upside_pct": upside_pct}


def score_latest_smooth_v2(row: pd.Series, target_price: float) -> dict:
    """v1 + OBV 이분법을 z-score 램프로 추가 연속화한 버전."""
    trend = _trend_strength_score_smooth(row)
    momentum = _momentum_score_smooth(row)
    volume = _volume_score_smooth(row)
    upside_pct = (target_price - row["Close"]) / row["Close"] * 100
    target = _target_score_smooth(upside_pct)
    return {**_finalize_score(trend, momentum, volume, target, row), "upside_pct": upside_pct}
