"""기술적 지표 계산 (Gemini 백테스트 코드 이식 + ATR/ADX 추가)."""
import numpy as np
import pandas as pd


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    data = df.copy()

    # 이동평균선
    data["SMA5"] = data["Close"].rolling(5).mean()
    data["SMA20"] = data["Close"].rolling(20).mean()
    data["SMA60"] = data["Close"].rolling(60).mean()
    data["SMA200"] = data["Close"].rolling(200).mean()
    data["SMA200_slope"] = data["SMA200"].diff(5)
    data["SMA60_slope"] = data["SMA60"].diff(5)

    # 이격도
    data["Disparity20"] = (data["Close"] / data["SMA20"]) * 100
    data["Disparity60"] = (data["Close"] / data["SMA60"]) * 100

    # RSI(14)
    delta = data["Close"].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / (loss + 1e-9)
    data["RSI14"] = 100 - (100 / (1 + rs))

    # 볼린저 밴드 %B
    std20 = data["Close"].rolling(20).std()
    data["BB_Upper"] = data["SMA20"] + std20 * 2
    data["BB_Lower"] = data["SMA20"] - std20 * 2
    data["Band_Pct"] = (data["Close"] - data["BB_Lower"]) / (data["BB_Upper"] - data["BB_Lower"] + 1e-9)

    # OBV
    obv_dir = np.sign(data["Close"].diff()).fillna(0)
    data["OBV"] = (obv_dir * data["Volume"]).cumsum()
    data["OBV_SMA20"] = data["OBV"].rolling(20).mean()
    data["OBV_STD20"] = data["OBV"].rolling(20).std()

    # 거래량 배수
    data["Vol_SMA20"] = data["Volume"].rolling(20).mean()
    data["Vol_Ratio"] = data["Volume"] / (data["Vol_SMA20"] + 1e-9)

    # ATR(14) - Wilder
    prev_close = data["Close"].shift(1)
    tr = pd.concat([
        data["High"] - data["Low"],
        (data["High"] - prev_close).abs(),
        (data["Low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    data["ATR14"] = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()

    # ADX(14) - Wilder
    up_move = data["High"].diff()
    down_move = -data["Low"].diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    atr_for_di = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    plus_di = 100 * pd.Series(plus_dm, index=data.index).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean() / (atr_for_di + 1e-9)
    minus_di = 100 * pd.Series(minus_dm, index=data.index).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean() / (atr_for_di + 1e-9)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-9)
    data["Plus_DI"] = plus_di
    data["Minus_DI"] = minus_di
    data["ADX14"] = dx.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()

    return data
