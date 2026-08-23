"""시세/목표가 데이터 수집 모듈. KR은 pykrx, US는 yfinance."""
import datetime as dt
import json
import re
import urllib.request

import pandas as pd

KR_ETF_PREFIXES = (
    "TIGER", "KODEX", "ACE", "HANARO", "RISE", "SOL", "PLUS", "KoAct",
    "KBSTAR", "ARIRANG", "SMART", "HK", "KIWOOM", "마이티", "신한", "WON",
    "TIMEFOLIO",
)

_COL_MAP = {
    "시가": "Open", "고가": "High", "저가": "Low", "종가": "Close",
    "거래량": "Volume", "등락률": "ChangePct",
}


def is_kr_etf(name: str) -> bool:
    upper = name.upper()
    return any(upper.startswith(p.upper()) for p in KR_ETF_PREFIXES)


def fetch_ohlcv(entry: dict, days: int = 400) -> pd.DataFrame:
    """entry: {name, code, market}. Returns DataFrame[Open,High,Low,Close,Volume], naive DatetimeIndex, ascending."""
    if entry["market"] == "KR":
        from pykrx import stock
        end = dt.date.today()
        start = end - dt.timedelta(days=days)
        df = stock.get_market_ohlcv(start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), entry["code"])
        if df is None or df.empty:
            raise ValueError(f"pykrx returned no data for {entry['code']}")
        df = df.rename(columns=_COL_MAP)
        df = df[["Open", "High", "Low", "Close", "Volume"]].astype(float)
        df.index = pd.to_datetime(df.index)
        df.index.name = "Date"
        return df.sort_index()
    else:
        import yfinance as yf
        t = yf.Ticker(entry["code"])
        end = dt.date.today()
        start = end - dt.timedelta(days=days)
        df = t.history(start=start.isoformat(), end=(end + dt.timedelta(days=1)).isoformat(), auto_adjust=False)
        if df is None or df.empty:
            raise ValueError(f"yfinance returned no data for {entry['code']}")
        df = df[["Open", "High", "Low", "Close", "Volume"]].astype(float)
        df.index = pd.to_datetime(df.index).tz_localize(None)
        df.index.name = "Date"
        return df.sort_index()


def _kr_consensus_target(code: str) -> float | None:
    try:
        url = f"https://m.stock.naver.com/api/stock/{code}/integration"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        data = json.loads(urllib.request.urlopen(req, timeout=10).read().decode("utf-8"))
        val = (data.get("consensusInfo") or {}).get("priceTargetMean")
        if not val:
            return None
        return float(re.sub(r"[,\s]", "", val))
    except Exception:
        return None


def _us_consensus_target(code: str) -> float | None:
    try:
        import yfinance as yf
        info = yf.Ticker(code).info
        val = info.get("targetMeanPrice")
        return float(val) if val else None
    except Exception:
        return None


def get_target_price(entry: dict, df: pd.DataFrame) -> tuple[float, str, bool]:
    """Returns (target_price, source_label, is_etf)."""
    wk52_high = float(df["Close"].tail(252).max())

    if entry["market"] == "KR":
        is_etf = is_kr_etf(entry["name"])
        if is_etf:
            return wk52_high, "52주 신고가", is_etf
        consensus = _kr_consensus_target(entry["code"])
    else:
        try:
            import yfinance as yf
            quote_type = yf.Ticker(entry["code"]).info.get("quoteType")
        except Exception:
            quote_type = None
        is_etf = quote_type == "ETF"
        if is_etf:
            return wk52_high, "52주 신고가", is_etf
        consensus = _us_consensus_target(entry["code"])

    if consensus and consensus > 0:
        return consensus, "컨센서스", is_etf
    return wk52_high, "52주 신고가", is_etf
