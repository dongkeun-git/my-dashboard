"""캔들패턴 + 크로스 시그널 (밴드 상단 돌파 후 반전 확인, RSI 70/30 돌파, 20MA 돌파).

일봉 기준 함수는 add_*(df) 형태로 컬럼을 추가한다. 주봉/월봉은 동일 함수를
resample된 데이터프레임에 그대로 재사용한다(suffix로 구분).
"""
import numpy as np
import pandas as pd


def resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    agg = df.resample(rule).agg({
        "Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum",
    })
    return agg.dropna(subset=["Open", "High", "Low", "Close"])


def add_candle_features(df: pd.DataFrame) -> pd.DataFrame:
    """장대음봉 / 긴 윗꼬리(양봉·음봉 무관) 반전캔들 판정."""
    data = df
    body = (data["Close"] - data["Open"]).abs()
    upper_wick = data["High"] - data[["Open", "Close"]].max(axis=1)
    lower_wick = data[["Open", "Close"]].min(axis=1) - data["Low"]
    rng = (data["High"] - data["Low"]).clip(lower=1e-9)
    atr = data["ATR14"] if "ATR14" in data.columns else rng.rolling(14).mean()

    is_long_bearish = (data["Close"] < data["Open"]) & (body >= 1.2 * atr) & (body >= 0.6 * rng)
    is_long_upper_wick = (upper_wick >= 0.4 * rng) & (lower_wick <= 0.15 * rng)

    data["ReversalCandle"] = is_long_bearish | is_long_upper_wick
    return data


def add_daily_trim_signal(df: pd.DataFrame) -> pd.DataFrame:
    """밴드 상단 돌파(고점권) 후 1~2일 내 5일선 이탈 또는 반전캔들이 나오면 확정."""
    data = df
    band_breakout = data["High"] > data["BB_Upper"]
    recent_breakout = band_breakout.rolling(2, min_periods=1).max().astype(bool)
    break_5ma = (data["Close"] < data["SMA5"]) & (data["Close"].shift(1) >= data["SMA5"].shift(1))

    data["BandBreakout"] = band_breakout
    data["TrimConfirmed"] = recent_breakout & (break_5ma | data["ReversalCandle"])
    return data


def add_trim_persistence(df: pd.DataFrame, window: int = 3) -> pd.DataFrame:
    """TrimConfirmed는 확정된 그날 하루만 True라 액션이 바로 다음날 원복되기 쉽다.
    확정 후 window거래일 동안은 계속 "과열 반전 관찰중" 상태로 유지되도록 지속성을 부여."""
    df["TrimConfirmedPersist"] = df["TrimConfirmed"].rolling(window, min_periods=1).max().astype(bool)
    return df


def add_rsi_cross(df: pd.DataFrame, suffix: str = "") -> pd.DataFrame:
    data = df
    prev = data["RSI14"].shift(1)
    data[f"RSI_CrossDown70{suffix}"] = (prev >= 70) & (data["RSI14"] < 70)
    data[f"RSI_CrossUp30{suffix}"] = (prev <= 30) & (data["RSI14"] > 30)
    return data


def add_ma20_cross(df: pd.DataFrame, suffix: str = "") -> pd.DataFrame:
    data = df
    prev_close = data["Close"].shift(1)
    prev_sma20 = data["SMA20"].shift(1)
    data[f"MA20_CrossUp{suffix}"] = (prev_close < prev_sma20) & (data["Close"] > data["SMA20"])
    data[f"MA20_CrossDown{suffix}"] = (prev_close > prev_sma20) & (data["Close"] < data["SMA20"])
    return data


def add_ma_cross(df: pd.DataFrame, fast_col: str, slow_col: str, out_prefix: str) -> pd.DataFrame:
    """이평선끼리의 골든/데드크로스 (예: SMA5 vs SMA20, SMA60 vs SMA200)."""
    data = df
    fast, slow = data[fast_col], data[slow_col]
    prev_fast, prev_slow = fast.shift(1), slow.shift(1)
    data[f"{out_prefix}_Golden"] = (prev_fast < prev_slow) & (fast > slow)
    data[f"{out_prefix}_Dead"] = (prev_fast > prev_slow) & (fast < slow)
    return data


def bool_at(row_or_none, key: str) -> bool:
    """row가 None이거나 컬럼/값이 NaN이면 False."""
    if row_or_none is None:
        return False
    val = row_or_none.get(key)
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return False
    return bool(val)
