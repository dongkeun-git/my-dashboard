"""비교 실험용 벤치마크 알고리즘 (일봉 OHLCV만으로 재현).

우리 시스템의 ADD/HOLD/TRIM/SELL 액션과 비교 가능하도록 ADD(강한 매수 신호)/
HOLD(유지)/SELL(회피·청산) 3단계로 라벨링한다 (TRIM 개념은 없음).

단순화: 원문의 Turtle Trading은 장중 스탑 주문 체결을 가정하지만, 일봉만 있으므로
"종가가 직전 N일 고가/저가를 넘는지"로 근사한다(대부분의 정량 백테스트가 쓰는 방식).
포지션 사이징/피라미딩/ATR 스탑 등 자금관리 규칙은 "이 날 어떤 방향에 서야 하는가"
라는 신호 자체와는 무관하므로 이 비교에서는 제외했다.
"""
import pandas as pd


def turtle_actions(data: pd.DataFrame, entry_window: int = 55, exit_window: int = 20) -> pd.Series:
    """터틀 트레이딩 System 2 (55일 돌파 진입 / 20일 이탈 청산, 항상 신호를 취함)."""
    entry_level = data["High"].rolling(entry_window).max().shift(1)
    exit_level = data["Low"].rolling(exit_window).min().shift(1)

    actions = [None] * len(data)
    in_position = False
    for i in range(len(data)):
        hi, lo, close = entry_level.iloc[i], exit_level.iloc[i], data["Close"].iloc[i]
        if pd.isna(hi) or pd.isna(lo):
            continue
        if not in_position and close > hi:
            actions[i] = "ADD"
            in_position = True
        elif in_position and close < lo:
            actions[i] = "SELL"
            in_position = False
        else:
            actions[i] = "HOLD"  # 보유 중 유지 또는 무포지션 관망 모두 중립으로 취급
    return pd.Series(actions, index=data.index)


def golden_cross_actions(data: pd.DataFrame, fast: int = 50, slow: int = 200) -> pd.Series:
    """골든크로스/데드크로스 (50일선-200일선 교차, 상시 롱/현금 이진 상태)."""
    sma_fast = data["Close"].rolling(fast).mean()
    sma_slow = data["Close"].rolling(slow).mean()
    bullish = sma_fast > sma_slow
    prev_bullish = bullish.shift(1, fill_value=False)
    cross_up = bullish & ~prev_bullish
    cross_down = (~bullish) & prev_bullish

    actions = [None] * len(data)
    for i in range(len(data)):
        if pd.isna(sma_fast.iloc[i]) or pd.isna(sma_slow.iloc[i]):
            continue
        if cross_up.iloc[i]:
            actions[i] = "ADD"
        elif cross_down.iloc[i]:
            actions[i] = "SELL"
        elif bullish.iloc[i]:
            actions[i] = "HOLD"
        else:
            actions[i] = "SELL"  # 데드크로스 이후 구간 전체는 "현금 보유(회피)" 상태
    return pd.Series(actions, index=data.index)
