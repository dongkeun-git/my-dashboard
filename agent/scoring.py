"""100점 만점 팩터별 스코어링 (Gemini 백테스트 코드의 calculate_scores 이식)
+ ADX 기반 동적 가중치 조정.

원본 계단식(threshold bucket) 버전. 실제 운영 파이프라인(main.py)은 백테스트로
검증 후 채택한 연속(선형보간) 버전인 scoring_smooth.score_latest_smooth_v2를
score_latest라는 이름으로 임포트해 사용한다 - 이 파일은 비교실험 기준선(baseline)
으로 남겨둔 것.
"""
import pandas as pd


def _trend_strength_score(row) -> float:
    full_aligned = row["SMA5"] > row["SMA20"] > row["SMA60"] > row["SMA200"]
    short_aligned = row["SMA5"] > row["SMA20"] > row["SMA60"]
    pts = 15 if full_aligned else (10 if short_aligned else 0)

    disp = row["Disparity20"]
    if 100 <= disp <= 106:
        pts += 10
    elif 106 < disp <= 112:
        pts += 5
    elif disp > 115 or disp < 95:
        pts += 0
    else:
        pts += 3

    pts += 10 if row["Close"] > row["SMA200"] else 0
    return pts


def _momentum_score(row) -> float:
    rsi = row["RSI14"]
    if 50 <= rsi <= 65:
        pts = 15
    elif 65 < rsi <= 75:
        pts = 10
    elif 40 <= rsi < 50:
        pts = 8
    elif rsi < 30:
        pts = 5
    else:
        pts = 0

    bp = row["Band_Pct"]
    if 0.5 <= bp <= 0.8:
        pts += 10
    elif 0.8 < bp <= 1.0:
        pts += 6
    elif bp > 1.0:
        pts += 2
    else:
        pts += 0
    return pts


def _volume_score(row) -> float:
    pts = 15 if row["OBV"] > row["OBV_SMA20"] else 0
    is_up = row["Close"] > row["Open"]
    vr = row["Vol_Ratio"]
    if is_up and vr >= 1.5:
        pts += 10
    elif is_up and vr >= 0.8:
        pts += 6
    elif (not is_up) and vr >= 1.5:
        pts -= 5
    return pts


def _target_score(upside_pct: float) -> float:
    if upside_pct >= 25:
        return 15
    if upside_pct >= 15:
        return 10
    if upside_pct >= 5:
        return 5
    return 0


def score_latest(row: pd.Series, target_price: float) -> dict:
    """최신 시점 스냅샷 스코어. base_score(35/25/25/15 원본) + ADX 동적조정 adjusted_score."""
    trend = _trend_strength_score(row)
    momentum = _momentum_score(row)
    volume = _volume_score(row)
    upside_pct = (target_price - row["Close"]) / row["Close"] * 100
    target = _target_score(upside_pct)

    base_score = max(0.0, min(100.0, trend + momentum + volume + target))

    # ADX 동적 가중치: ADX<20(횡보) -> 모멘텀/밴드 비중 강화, trend 비중 축소 (최대 5점 이동)
    # ADX>25(추세장) -> 반대로 trend/OBV 비중 강화. 20<=ADX<=25는 조정 없음.
    adx = row.get("ADX14", float("nan"))
    shift = 0.0
    if pd.notna(adx):
        if adx < 20:
            # trend 팩터(35점 만점) 중 초과분을 momentum으로 재분배
            shift = min(5.0, trend * (5.0 / 35.0))
            trend_adj, momentum_adj, volume_adj = trend - shift, momentum + shift, volume
        elif adx > 25:
            # momentum+volume(각 25점 만점) 중 초과분을 trend로 재분배
            shift = min(5.0, (momentum + volume) * (5.0 / 50.0))
            trend_adj, momentum_adj, volume_adj = trend + shift, momentum, volume
            # momentum/volume 중 큰 쪽에서 shift 차감 (단순화: momentum에서 우선 차감)
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
        "upside_pct": upside_pct,
    }
