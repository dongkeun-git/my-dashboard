"""S&P500/KOSPI 시총 상위 30 리스트를 매 실행 시 점검하고, 순위 변동(신규 진입/이탈)이
있으면 Stock_List_Top30.txt를 갱신한다.

한계(중요): 500개 S&P500 전종목·전체 KOSPI 종목의 실시간 시가총액을 무료로 한번에
가져오는 API가 없다(pykrx의 시가총액 일괄조회 엔드포인트는 이 환경에서 응답하지
않음 - KRX_ID/PW 로그인 세션이 필요한 것으로 보임). 따라서 "전체 종목 중 정확한
top 30"이 아니라, 아래 CANDIDATE 풀(현재 30위 + 30위 근처일 가능성이 있는 대형주
버퍼) 안에서 시가총액을 다시 매겨 top 30을 재산정하는 근사 방식이다. 후보 풀에
없는 종목이 갑자기 30위 안에 진입하는 극단적 상황은 감지하지 못한다 - 주기적으로
CANDIDATE_US/CANDIDATE_KR 풀 자체를 점검·보강할 필요가 있다.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parent.parent
TOP30_LIST_PATH = ROOT / "Stock_List_Top30.txt"

# 현재 top30(2026-08 기준) + 다음 순번권 대형주 버퍼. (종목명, 티커)
CANDIDATE_US = [
    ("엔비디아", "NVDA"), ("애플", "AAPL"), ("알파벳", "GOOGL"), ("마이크로소프트", "MSFT"),
    ("아마존", "AMZN"), ("브로드컴", "AVGO"), ("메타", "META"), ("테슬라", "TSLA"),
    ("마이크론테크놀로지", "MU"), ("버크셔해서웨이", "BRK-B"), ("일라이릴리", "LLY"),
    ("JP모건체이스", "JPM"), ("월마트", "WMT"), ("AMD", "AMD"), ("비자", "V"),
    ("엑슨모빌", "XOM"), ("존슨앤드존슨", "JNJ"), ("인텔", "INTC"), ("마스터카드", "MA"),
    ("뱅크오브아메리카", "BAC"), ("애브비", "ABBV"), ("시스코시스템즈", "CSCO"),
    ("오라클", "ORCL"), ("코스트코", "COST"), ("팔란티어", "PLTR"), ("램리서치", "LRCX"),
    ("어플라이드머티어리얼즈", "AMAT"), ("캐터필러", "CAT"), ("셰브런", "CVX"),
    ("GE에어로스페이스", "GE"),
    # 버퍼(현재 top30 밖이지만 근접권으로 보는 대형주)
    ("넷플릭스", "NFLX"), ("어도비", "ADBE"), ("세일즈포스", "CRM"), ("코카콜라", "KO"),
    ("펩시코", "PEP"), ("서모피셔사이언티픽", "TMO"), ("애벗", "ABT"), ("맥도날드", "MCD"),
    ("필립모리스", "PM"), ("린데", "LIN"), ("T모바일US", "TMUS"), ("월트디즈니", "DIS"),
    ("웰스파고", "WFC"), ("버라이즌", "VZ"), ("에이티앤티", "T"), ("컴캐스트", "CMCSA"),
    ("허니웰", "HON"), ("유니언퍼시픽", "UNP"), ("유나이티드헬스", "UNH"), ("머크", "MRK"),
    ("화이자", "PFE"), ("IBM", "IBM"), ("퀄컴", "QCOM"), ("텍사스인스트루먼트", "TXN"),
    ("부킹홀딩스", "BKNG"), ("골드만삭스", "GS"), ("모건스탠리", "MS"),
    ("아메리칸익스프레스", "AXP"), ("블랙스톤", "BX"), ("찰스슈왑", "SCHW"),
]

# (종목명, 6자리 코드) - KOSPI 상장 종목만 (KOSDAQ 종목 제외).
CANDIDATE_KR = [
    ("삼성전자", "005930"), ("SK하이닉스", "000660"), ("SK스퀘어", "402340"),
    ("삼성전기", "009150"), ("현대차", "005380"), ("LG에너지솔루션", "373220"),
    ("삼성바이오로직스", "207940"), ("삼성생명", "032830"), ("삼성물산", "028260"),
    ("한화에어로스페이스", "012450"), ("KB금융", "105560"), ("기아", "000270"),
    ("HD현대중공업", "329180"), ("두산에너빌리티", "034020"), ("신한지주", "055550"),
    ("현대모비스", "012330"), ("셀트리온", "068270"), ("SK", "034730"),
    ("삼성SDI", "006400"), ("하나금융지주", "086790"), ("NAVER", "035420"),
    ("LG전자", "066570"), ("LS ELECTRIC", "010120"), ("한화오션", "042660"),
    ("HD현대일렉트릭", "267260"), ("효성중공업", "298040"), ("삼성화재", "000810"),
    ("HD한국조선해양", "009540"), ("POSCO홀딩스", "005490"), ("고려아연", "010130"),
    # 버퍼
    ("카카오", "035720"), ("크래프톤", "259960"), ("LG화학", "051910"), ("LG", "003550"),
    ("하이브", "352820"), ("SK이노베이션", "096770"), ("두산밥캣", "241560"),
    ("두산", "000150"), ("대한항공", "003490"), ("KT", "030200"),
    ("CJ제일제당", "097950"), ("아모레퍼시픽", "090430"), ("한국전력", "015760"),
    ("우리금융지주", "316140"), ("메리츠금융지주", "138040"), ("DB손해보험", "005830"),
    ("HMM", "011200"), ("카카오뱅크", "323410"), ("LG디스플레이", "034220"),
    ("롯데케미칼", "011170"), ("코웨이", "021240"), ("한국타이어앤테크놀로지", "161390"),
    ("GS", "078930"), ("현대글로비스", "086280"), ("현대건설", "000720"),
]

TOP_N = 30


def _fetch_market_cap(ticker: str) -> float | None:
    import yfinance as yf
    try:
        fi = yf.Ticker(ticker).fast_info
        mc = fi.get("marketCap") if hasattr(fi, "get") else fi["marketCap"]
        return float(mc) if mc else None
    except Exception:
        return None


def _rank_top30(candidates: list[tuple[str, str]], yf_ticker_fn) -> list[tuple[str, str]]:
    """(이름, 코드) 후보 목록 -> 시가총액 내림차순 top 30 [(이름, 코드), ...]. 조회 실패 종목은 제외."""
    ranked = []
    for name, code in candidates:
        mc = _fetch_market_cap(yf_ticker_fn(code))
        if mc is not None:
            ranked.append((mc, name, code))
        time.sleep(0.1)
    ranked.sort(key=lambda x: x[0], reverse=True)
    return [(name, code) for _mc, name, code in ranked[:TOP_N]]


def _parse_existing_top30(path: Path) -> tuple[list[str], list[str]]:
    """기존 파일에서 (US 코드 목록, KR 코드 목록)을 반환. US=대문자/하이픈 티커, KR=6자리."""
    from stock_list import classify
    us, kr = [], []
    if not path.exists():
        return us, kr
    import re
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^(.*?)\s*\(([^)]+)\)", line)
        if not m:
            continue
        code = m.group(2).strip()
        (us if classify(code) == "US" else kr).append(code)
    return us, kr


def update_top30_list(path: Path = TOP30_LIST_PATH) -> bool:
    """변경이 있으면 파일을 갱신하고 True, 없으면(또는 조회 전부 실패) False 반환."""
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    print("Top30 리스트 최신화 확인 중 (S&P500/KOSPI 시가총액 후보군 재조회)...")
    new_us = _rank_top30(CANDIDATE_US, lambda code: code)
    new_kr = _rank_top30(CANDIDATE_KR, lambda code: f"{code}.KS")

    if not new_us or not new_kr:
        print("  시가총액 조회 실패(네트워크/rate-limit) - 기존 Stock_List_Top30.txt 유지")
        return False

    old_us_codes, old_kr_codes = _parse_existing_top30(path)
    new_us_codes = [c for _n, c in new_us]
    new_kr_codes = [c for _n, c in new_kr]

    added_us = set(new_us_codes) - set(old_us_codes)
    removed_us = set(old_us_codes) - set(new_us_codes)
    added_kr = set(new_kr_codes) - set(old_kr_codes)
    removed_kr = set(old_kr_codes) - set(new_kr_codes)

    if not (added_us or removed_us or added_kr or removed_kr):
        print("  변경 없음 - Stock_List_Top30.txt 그대로 사용")
        return False

    print(f"  변경 감지 - S&P500 편입:{sorted(added_us)} 이탈:{sorted(removed_us)} | "
          f"KOSPI 편입:{sorted(added_kr)} 이탈:{sorted(removed_kr)}")
    lines = [f"{name} ({code})" for name, code in new_us] + [f"{name} ({code})" for name, code in new_kr]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  Stock_List_Top30.txt 갱신 완료 ({len(lines)}개 종목)")
    return True


if __name__ == "__main__":
    update_top30_list()
