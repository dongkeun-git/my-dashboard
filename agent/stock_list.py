"""Stock_List.txt 파싱 모듈."""
import re
from pathlib import Path

LINE_RE = re.compile(r"^(.*?)\s*\(([^)]+)\)")  # 코드 뒤 "[확인필요*]" 같은 주석은 무시

# US tickers: pure letters, 1-5 chars. KR codes: contain at least one digit, 6 chars.
US_TICKER_RE = re.compile(r"^[A-Z]{1,5}$")
KR_CODE_RE = re.compile(r"^[0-9A-Z]{6}$")


def classify(code: str) -> str:
    code = code.strip()
    if US_TICKER_RE.match(code):
        return "US"
    if KR_CODE_RE.match(code) and any(ch.isdigit() for ch in code):
        return "KR"
    # Fallback: default to KR code shape if 6 chars, else US
    return "KR" if len(code) == 6 else "US"


def load_stock_list(path: str | Path) -> list[dict]:
    path = Path(path)
    entries = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        m = LINE_RE.match(line)
        if not m:
            raise ValueError(f"Cannot parse line: {raw_line!r}")
        name, code = m.group(1).strip(), m.group(2).strip()
        entries.append({"name": name, "code": code, "market": classify(code)})
    return entries


if __name__ == "__main__":
    here = Path(__file__).resolve().parent.parent
    for e in load_stock_list(here / "Stock_List.txt"):
        print(e)
