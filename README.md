# 주식/ETF 매매 신호 대시보드

보유 종목과 시총 상위 종목의 기술적 지표를 계층형 복합 스코어링으로 채점해
ADD/HOLD/TRIM/SELL 액션을 계산하고, 정적 HTML 대시보드로 보여주는 개인용 도구.

## 실행 방법

`run.bat`을 더블클릭하면 순서대로:
1. `agent/main.py` — `Stock_List.txt`(보유 종목) 기준 → `dashboard.html`
2. `agent/main_top30.py` — S&P500·KOSPI 시총 상위 30 기준 → `dashboard_top30.html`

두 스크립트 모두 실행할 때마다 종목 리스트를 새로 읽으므로, `Stock_List.txt`에
종목을 추가/삭제하면 다음 실행부터 바로 반영된다.

## 파일 구조

- `Stock_List.txt` — 보유 종목 리스트 (직접 관리, "종목명 (코드/티커)" 형식)
- `Stock_List_Top30.txt` — S&P500/KOSPI 시총 상위 30 리스트 (아래 "Top30 자동 갱신" 참고, 자동 관리)
- `dashboard.html`, `dashboard_top30.html` — 최신 대시보드 (매 실행 시 덮어씀)
- `data/dashboard_backup/` — 일자별 백업, `dashboard_YYMMDD.html` / `dashboard_top30_YYMMDD.html` (하루 최대 1개, 그날 마지막 실행 내용으로 덮어씀)
- `agent/` — 파이프라인 모듈 (아래 참고)

### agent/ 모듈

| 파일 | 역할 |
|---|---|
| `stock_list.py` | 리스트 파일 파싱, KR/US 시장 분류 |
| `data_fetcher.py` | 시세 수집(KR: pykrx, US: yfinance) + 목표가(컨센서스/52주신고가) |
| `indicators.py` | SMA/RSI/Band%/OBV/ATR/ADX 등 지표 계산 |
| `scoring.py` | **원본 계단식 채점** (실험 기준선으로 보존, 운영에는 미사용) |
| `scoring_smooth.py` | **운영 중인 연속(선형보간) 채점** — `score_latest_smooth_v2`를 `main.py`가 `score_latest`라는 이름으로 가져다 씀 |
| `events.py` | 캔들패턴/RSI 크로스/골든·데드크로스/TRIM 확정 신호 |
| `signal_engine.py` | 추세 판정 + 액션(ADD/HOLD/TRIM/SELL) 결정 트리 |
| `dashboard_generator.py` | HTML 렌더링, 일자별 백업, 전일 대비 변화 화살표 계산 |
| `main.py` | 오케스트레이터 (`run(stock_list_path, dashboard_path, title)`) |
| `main_top30.py` | Top30용 진입점 (Top30 자동갱신 → `run()` 재사용) |
| `update_top30_list.py` | Top30 리스트 자동 갱신 (아래 참고) |
| `validate_scoring.py`, `tune_thresholds.py`, `compare_algorithms.py`, `compare_scoring_smoothness.py`, `compare_scoring_v2.py` | 백테스트 검증/파라미터 튜닝/타 알고리즘·채점방식 비교 실험 스크립트 (수동 실행) |

## Top30 자동 갱신

`main_top30.py`를 실행할 때마다 `update_top30_list.py`가 먼저 S&P500/KOSPI
시가총액 상위 30을 다시 계산해서, 편입/이탈이 있으면 `Stock_List_Top30.txt`를
자동으로 갱신한 뒤 대시보드를 생성한다. 변경이 없으면 파일을 건드리지 않는다.

**한계**: 500개 S&P500 전종목·전체 KOSPI 종목의 시가총액을 무료로 한 번에
조회하는 API가 없어(pykrx의 시가총액 일괄조회 엔드포인트가 이 환경에서
응답하지 않음), `update_top30_list.py`의 `CANDIDATE_US`/`CANDIDATE_KR`
후보군(현재 30위 + 근접권 대형주 버퍼) 안에서만 순위를 재산정하는 근사
방식이다. 후보군에 없는 종목이 갑자기 30위 안에 진입하는 극단적 상황은
감지하지 못하므로, 주기적으로 이 후보군 목록 자체를 점검·보강해야 한다.
조회가 네트워크 문제 등으로 전부 실패하면 기존 리스트를 그대로 사용한다.

## 전일 대비 변화 화살표

대시보드의 단기/중기/장기 추세와 현재 액션 옆에 표시되는 ▲/▼는 **"어제 또는
그 이전 마지막 백업"** 대비 개선/악화 여부다 (`dashboard_generator.py`의
`_load_previous_results`). 오늘 같은 파일을 여러 번 생성해도 오늘자 백업끼리는
비교하지 않고 항상 전날 이전 백업을 찾아 비교하므로, 하루에 여러 번 실행해도
"변화 없음"으로 착시되지 않는다. 전날 이전 백업이 아직 없으면(첫 실행 등)
화살표는 표시되지 않는다.

- 추세: 하락 < 횡보 < 상승 순으로 개선되면 ▲, 악화되면 ▼
- 액션: 매도/축소 < 분할매도 < 보유 < 추가매수 순으로 좋아지면 ▲, 나빠지면 ▼
  (대시보드 기본 정렬·Ranking과 동일한 우선순위 기준)
- RSI14: 30/50/70선 중 하나라도 그 시점 대비 상향 돌파했으면 ▲, 하향 돌파했으면 ▼
  (단순 등락은 표시 안 함 — 세 선 중 하나를 실제로 넘나든 경우만)
- Band%: 그 시점 대비 값이 올랐으면 ▲, 내렸으면 ▼ (임계값 없이 단순 방향)

## 채점 방식 (연속 스코어링)

운영 중인 스코어링은 `scoring_smooth.py`의 v2 버전이다:
- 추세(35) / 모멘텀·밴드(25) / 수급·거래량(25) / 목표가 괴리(15) 배점 구조는
  원본 계단식과 동일 (팩터별 상한선 불변)
- RSI, Band%, 20일 이격도, 목표가 괴리율은 구간 경계값을 anchor로 삼아
  선형보간(계단식 점프 제거)
- OBV는 OBV-OBV20일선 격차를 20일 표준편차로 정규화한 z-score 램프
  (이분법 0/15점 대신 연속 배분)
- ADX 기반 동적 가중치(±5점, ADX<20 추세→모멘텀 이동 / ADX>25 반대)는 원본과 동일
- TRIM(과열 반전 확정) 신호는 여전히 단발성 이벤트로 유지 (3일 지속성은
  백테스트에서 역효과가 확인되어 채택하지 않음 — `compare_scoring_v2.py` 참고)

이 채택 결정은 69개 종목·2년 데이터 백테스트로 계단식/연속-v1/연속-v2 세
버전의 수익률(PASS 5기준)과 안정성(연속 샘플 간 점수변동폭·급변비율)을 비교한
뒤 내려졌다. 재검증하려면 `python agent/compare_scoring_v2.py` 실행.
