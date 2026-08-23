"""S&P500 시총상위 30 + KOSPI 시총상위 30 종목 대시보드.

기존 파이프라인(main.py의 process_entry/run)을 그대로 재사용하고 입출력 경로만
Stock_List_Top30.txt / dashboard_top30.html 로 바꾼 것. 실행할 때마다 먼저
update_top30_list로 시총 순위 변동(편입/이탈)을 점검해 리스트를 최신화한 뒤
대시보드를 생성한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from main import run
from update_top30_list import update_top30_list

ROOT = Path(__file__).resolve().parent.parent
STOCK_LIST_PATH = ROOT / "Stock_List_Top30.txt"
DASHBOARD_PATH = ROOT / "dashboard_top30.html"

if __name__ == "__main__":
    try:
        update_top30_list(STOCK_LIST_PATH)
    except Exception as e:
        print(f"Top30 리스트 최신화 중 오류 - 기존 리스트로 계속 진행: {type(e).__name__}: {e}")
    run(STOCK_LIST_PATH, DASHBOARD_PATH, title="KOSPI 및 S&P 500 시총 상위 Top 30 주식 매매 신호 대시보드")
