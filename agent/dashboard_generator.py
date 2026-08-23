"""결과를 단일 정적 HTML 대시보드로 렌더링."""
import json
import re
from pathlib import Path

ACTION_LABEL = {"ADD": "추가매수", "HOLD": "보유", "TRIM": "분할매도", "SELL": "매도/축소"}
TREND_LABEL = {"Bullish": "상승", "Bearish": "하락", "Neutral": "횡보"}
TREND_ORDER = {"Bearish": 0, "Neutral": 1, "Bullish": 2}
ACTION_PRIORITY = {"ADD": 0, "HOLD": 1, "TRIM": 2, "SELL": 3}
RSI_LINES = (30, 50, 70)


def _load_previous_results(out_path: Path) -> dict:
    """data/dashboard_backup/의 "어제 또는 그 이전" 백업 중 가장 최근 것을 비교 기준으로 삼는다.
    (오늘 이미 여러 번 생성한 경우에도 "변화 없음"으로 착시되지 않도록, 오늘자 백업/현재
    파일 자체가 아니라 반드시 전날 이전 백업을 찾는다. 없으면 빈 dict - 화살표 표시 없음.)
    """
    import datetime as dt

    out_path = Path(out_path)
    backup_dir = out_path.parent / "data" / "dashboard_backup"
    if not backup_dir.exists():
        return {}

    today_str = dt.date.today().strftime("%y%m%d")
    pattern = re.compile(rf"^{re.escape(out_path.stem)}_(\d{{6}}){re.escape(out_path.suffix)}$")
    candidates = [m.group(1) for f in backup_dir.iterdir() if (m := pattern.match(f.name)) and m.group(1) < today_str]
    if not candidates:
        return {}
    latest_date = max(candidates)
    latest_file = backup_dir / f"{out_path.stem}_{latest_date}{out_path.suffix}"

    try:
        html = latest_file.read_text(encoding="utf-8")
        m = re.search(r"const RESULTS = (\[.*?\]);", html, re.S)
        if not m:
            return {}
        return {r["code"]: r for r in json.loads(m.group(1))}
    except Exception:
        return {}


def _annotate_changes(results: list[dict], previous: dict) -> None:
    """직전 대비 단기/중기/장기 추세, 현재 액션의 개선(up)/악화(down) 여부를 채운다."""
    for r in results:
        prev = previous.get(r["code"])
        for key in ("short_trend", "mid_trend", "long_trend"):
            r[f"{key}_change"] = None
            if prev and prev.get(key) in TREND_ORDER and r.get(key) in TREND_ORDER:
                diff = TREND_ORDER[r[key]] - TREND_ORDER[prev[key]]
                if diff > 0:
                    r[f"{key}_change"] = "up"
                elif diff < 0:
                    r[f"{key}_change"] = "down"

        r["action_change"] = None
        if prev and prev.get("action") in ACTION_PRIORITY and r.get("action") in ACTION_PRIORITY:
            diff = ACTION_PRIORITY[r["action"]] - ACTION_PRIORITY[prev["action"]]
            if diff < 0:
                r["action_change"] = "up"
            elif diff > 0:
                r["action_change"] = "down"

        r["rsi_change"] = None
        if prev and prev.get("rsi") is not None and r.get("rsi") is not None:
            prev_rsi, curr_rsi = prev["rsi"], r["rsi"]
            if any(prev_rsi <= line < curr_rsi for line in RSI_LINES):
                r["rsi_change"] = "up"
            elif any(prev_rsi >= line > curr_rsi for line in RSI_LINES):
                r["rsi_change"] = "down"

        r["band_pct_change"] = None
        if prev and prev.get("band_pct") is not None and r.get("band_pct") is not None:
            if r["band_pct"] > prev["band_pct"]:
                r["band_pct_change"] = "up"
            elif r["band_pct"] < prev["band_pct"]:
                r["band_pct_change"] = "down"

TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>__TITLE__</title>
<style>
  :root {
    color-scheme: light;
    --surface-1: #fcfcfb;
    --surface-2: #f2f1ee;
    --border: #e2e0da;
    --text-primary: #0b0b0b;
    --text-secondary: #52514e;
    --text-muted: #8a8a86;
    --good: #0ca30c;
    --good-bg: #e4f7e4;
    --warning: #b8790a;
    --warning-bg: #fdf1d9;
    --critical: #d03b3b;
    --critical-bg: #fbe6e6;
    --neutral: #3a3a38;
    --neutral-bg: #eceae4;
    --accent: #2a78d6;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 32px;
    background: var(--surface-1); color: var(--text-primary);
    font-family: -apple-system, "Segoe UI", "Malgun Gothic", sans-serif;
    font-size: 14px;
  }
  h1 { font-size: 20px; margin: 0 0 4px; }
  .subtitle { color: var(--text-secondary); margin: 0 0 20px; font-size: 13px; }
  .summary { display: flex; gap: 12px; margin-bottom: 20px; flex-wrap: wrap; }
  .stat-tile {
    background: var(--surface-2); border: 1px solid var(--border); border-radius: 8px;
    padding: 12px 18px; min-width: 100px;
  }
  .stat-tile .n { font-size: 22px; font-weight: 700; }
  .stat-tile .l { font-size: 12px; color: var(--text-secondary); }
  .controls { display: flex; gap: 8px; margin-bottom: 14px; flex-wrap: wrap; align-items: center; }
  .controls button {
    border: 1px solid var(--border); background: var(--surface-2); color: var(--text-primary);
    border-radius: 999px; padding: 6px 14px; font-size: 12px; cursor: pointer;
  }
  .controls button.active { background: var(--accent); color: #fff; border-color: var(--accent); }
  table { border-collapse: collapse; width: 100%; background: var(--surface-1); }
  thead th {
    position: sticky; top: 0; background: var(--surface-2); text-align: left;
    padding: 6px 7px; font-size: 11px; color: var(--text-secondary);
    border-bottom: 1px solid var(--border); cursor: pointer; white-space: nowrap;
  }
  thead th:hover { color: var(--text-primary); }
  thead tr:first-child th { top: 0; }
  thead tr:last-child th { top: 27px; }
  thead th.group-header { text-align: center; cursor: default; border-bottom: 1px solid var(--border); }
  thead th.group-header:hover { color: var(--text-secondary); }
  thead th.sub-header { text-align: right; font-size: 10px; }
  thead th.sub-header[data-key="long_trend"],
  thead th.sub-header[data-key="mid_trend"],
  thead th.sub-header[data-key="short_trend"],
  thead th.sub-header[data-key="action_1m"],
  thead th.sub-header[data-key="action"] { text-align: left; }
  thead th.alerts-col { max-width: 110px; }
  tbody td { padding: 6px 7px; border-bottom: 1px solid var(--border); white-space: nowrap; font-size: 12px; }
  tbody tr:hover { background: var(--surface-2); }
  .badge {
    display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 12px; font-weight: 600;
  }
  .badge-ADD { background: var(--good-bg); color: var(--good); }
  .badge-HOLD { background: var(--neutral-bg); color: var(--neutral); }
  .badge-TRIM { background: var(--warning-bg); color: var(--warning); }
  .badge-SELL { background: var(--critical-bg); color: var(--critical); }
  .trend { font-size: 12px; padding: 1px 7px; border-radius: 5px; }
  .trend-Bullish { background: var(--good-bg); color: var(--good); }
  .trend-Bearish { background: var(--critical-bg); color: var(--critical); }
  .trend-Neutral { background: var(--neutral-bg); color: var(--text-secondary); }
  .change-arrow { font-size: 14px; font-weight: 900; margin-left: 3px; vertical-align: -1px; }
  .change-up { color: #067d06; }
  .change-down { color: #b31414; }
  .alerts-cell { white-space: normal; max-width: 110px; width: 110px; }
  .alert-badge {
    display: block; padding: 1px 5px; margin-bottom: 2px; border-radius: 4px; font-size: 10px;
    background: var(--surface-2); color: var(--text-secondary); border: 1px solid var(--border);
    white-space: normal; line-height: 1.3; width: fit-content;
  }
  .alert-badge:last-child { margin-bottom: 0; }
  .num { text-align: right; font-variant-numeric: tabular-nums; }
  .name-cell { font-weight: 600; max-width: 150px; white-space: normal; word-break: keep-all; line-height: 1.25; }
  .code-cell { color: var(--text-muted); font-size: 12px; }
  .legend { display: flex; gap: 16px; margin: 14px 0; font-size: 12px; color: var(--text-secondary); flex-wrap: wrap; }
  .legend span { display: inline-flex; align-items: center; gap: 5px; }
  .dot { width: 9px; height: 9px; border-radius: 50%; display: inline-block; }
  .trend-def { font-size: 12px; color: var(--text-secondary); margin: 0 0 14px; padding: 8px 12px; background: var(--surface-2); border-radius: 6px; }
  .trend-def b { color: var(--text-primary); }
  .failures { margin-top: 24px; font-size: 12px; color: var(--text-secondary); }
  .failures summary { cursor: pointer; color: var(--critical); }
  footer { margin-top: 20px; font-size: 11px; color: var(--text-muted); }

  /* ===== 모바일 반응형 (좁은 화면: 카드형 1열 레이아웃) ===== */
  @media (max-width: 700px) {
    body { padding: 14px; font-size: 15px; }
    h1 { font-size: 18px; }
    .subtitle { font-size: 12px; }

    .summary { flex-direction: column; }
    .stat-tile { width: 100%; padding: 14px 18px; }
    .stat-tile .n { font-size: 24px; }

    .legend { flex-direction: column; gap: 8px; font-size: 13px; }
    .trend-def { font-size: 13px; line-height: 1.5; }

    .controls { gap: 10px; }
    .controls button {
      padding: 10px 16px; font-size: 14px; min-height: 40px;
    }

    /* 테이블을 헤더 없는 카드 목록으로 재구성 - 각 행이 1개 카드, 각 셀은 라벨:값 한 줄 */
    table, thead, tbody, tr, th, td { display: block; }
    thead { display: none; }
    tbody tr {
      margin-bottom: 14px; border: 1px solid var(--border); border-radius: 10px;
      padding: 4px 12px; background: var(--surface-1);
    }
    tbody td {
      text-align: right; padding: 9px 0; border-bottom: 1px dashed var(--border);
      white-space: normal; font-size: 14px; overflow: hidden;
    }
    tbody td:last-child { border-bottom: none; }
    tbody td::before {
      content: attr(data-label); float: left; font-weight: 600; color: var(--text-secondary);
      margin-right: 10px; font-size: 12px;
    }
    .name-cell, .alerts-cell, .code-cell { max-width: none; width: auto; }
    .badge, .trend { font-size: 13px; padding: 4px 12px; }
    .change-arrow { font-size: 17px; }
    .alert-badge { margin: 3px 0 3px 8px; }
  }
</style>
</head>
<body>
  <h1>__TITLE__</h1>
  <p class="subtitle">생성 시각: __GENERATED_AT__ · 총 __N_RESULTS__개 종목 · 계층형 복합 스코어링 모델 (추세 35 / 모멘텀·밴드 25 / 수급·거래량 25 / 목표가 괴리 15, ADX 동적가중치 반영)</p>

  <div class="summary" id="summary"></div>

  <div class="legend">
    <span><span class="dot" style="background:var(--good)"></span> ADD 추가매수 — 총점 70+, 장·중기 상승, 반전 신호 없음</span>
    <span><span class="dot" style="background:var(--neutral)"></span> HOLD 보유 — 총점 40~69 또는 추세 미확정</span>
    <span><span class="dot" style="background:var(--warning)"></span> TRIM 분할매도 — 총점 40+ 이면서 과열 후 반전 확정(밴드상단 돌파+5일선 이탈/반전캔들, 또는 RSI 70 하향돌파)</span>
    <span><span class="dot" style="background:var(--critical)"></span> SELL 매도/축소 — 총점 40 미만(단 RSI 30 상향돌파 시 보류), 200일선 이탈, 또는 수급 붕괴</span>
  </div>

  <div class="trend-def">
    <b>추세 판정 기준</b> ·
    단기: 5일선 vs 20일선 &amp; 20일 이격도 vs 100% ·
    중기: 60일선 기울기 &amp; OBV vs OBV 20일선 (60일 이격도 98~102%는 횡보) ·
    장기: 주가 vs 200일선 &amp; 200일선 기울기 ·
    <b>Vol比</b>: 당일 거래량 ÷ 20일 평균거래량 (1.0 초과면 평소보다 거래 활발, 상승일+1.5배 이상이면 수급 유입으로 가점)
  </div>

  <div class="trend-def">
    <b>신호 배지</b> · 밴드 상단 돌파 후 5일선 이탈/장대음봉·긴 윗꼬리로 반전 확정, RSI 70/30 일봉·주봉 돌파,
    20일/20주/20개월선(중심선) 상향·하향 돌파, 5일선-20일선 및 60일선-200일선 골든·데드크로스가 최근 발생한
    종목에 표시됩니다. 액션(추가매수/보유/분할매도/매도)과는 별개로 참고용 알림입니다.
  </div>

  <div class="trend-def">
    <b><span class="change-arrow change-up">▲</span>/<span class="change-arrow change-down">▼</span> 변화 표시</b> ·
어제(또는 그 이전 마지막 백업) 대비 단기·중기·장기 추세가 개선(하락→횡보→상승 방향)되었으면 ▲,
    악화(상승→횡보→하락 방향)되었으면 ▼로 표시합니다. 현재 액션도 그 시점 대비 추가매수 쪽으로
    좋아졌으면 ▲, 매도/축소 쪽으로 나빠졌으면 ▼로 표시합니다. RSI14는 30/50/70선을 그 시점 대비
    상향 돌파했으면 ▲, 하향 돌파했으면 ▼ (세 선 중 하나라도 돌파 시 표시, 단순 등락은 표시 안 함).
    Band%는 그 시점 대비 값이 올랐으면 ▲, 내렸으면 ▼로 표시합니다. (같은 날 여러 번 생성해도
    오늘자끼리는 비교하지 않고 항상 전날 이전 백업과 비교합니다.)
  </div>

  <div class="controls" id="controls"></div>

  <table id="tbl">
    <thead>
      <tr>
        <th colspan="2" class="group-header">Ranking</th>
        <th rowspan="2" data-key="name">종목명</th>
        <th rowspan="2" data-key="code">코드/티커</th>
        <th colspan="3" class="group-header">주가</th>
        <th rowspan="2" data-key="target_price" class="num">목표가</th>
        <th rowspan="2" data-key="upside_pct" class="num">상승여력%</th>
        <th colspan="3" class="group-header">점수</th>
        <th colspan="3" class="group-header">추세</th>
        <th rowspan="2" data-key="rsi" class="num">RSI14</th>
        <th rowspan="2" data-key="band_pct" class="num">Band%</th>
        <th rowspan="2" data-key="vol_ratio" class="num">Vol比</th>
        <th colspan="2" class="group-header">액션</th>
        <th rowspan="2" data-key="alert_count" class="alerts-col">신호</th>
      </tr>
      <tr>
        <th data-key="rank_1m" class="num sub-header" title="1개월(약 21거래일) 전 데이터 기준 순위">1개월전</th>
        <th data-key="rank_now" class="num sub-header" title="현재 순위 (액션 우선순위 -> 현재 점수 내림차순)">현재</th>
        <th data-key="price_1m" class="num sub-header" title="1개월(약 21거래일) 전 종가">1개월전</th>
        <th data-key="price_1w" class="num sub-header" title="1주일(약 5거래일) 전 종가">1주일전</th>
        <th data-key="price_now" class="num sub-header" title="현재가">현재</th>
        <th data-key="score_1m" class="num sub-header" title="1개월(약 21거래일) 전 조정점수">1개월전</th>
        <th data-key="score_1w" class="num sub-header" title="1주일(약 5거래일) 전 조정점수">1주일전</th>
        <th data-key="score_now" class="num sub-header" title="현재 조정점수 (ADX 동적가중치 반영)">현재</th>
        <th data-key="short_trend" class="sub-header">단기</th>
        <th data-key="mid_trend" class="sub-header">중기</th>
        <th data-key="long_trend" class="sub-header">장기</th>
        <th data-key="action_1m" class="sub-header" title="1개월(약 21거래일) 전 기준으로 재계산한 액션">1개월전</th>
        <th data-key="action" class="sub-header" title="현재 액션">현재</th>
      </tr>
    </thead>
    <tbody id="tbody"></tbody>
  </table>

  <div class="failures" id="failures"></div>
  <footer>목표가: 개별주는 애널리스트 컨센서스, ETF는 52주 신고가 근사. 데이터: 한국(pykrx) / 미국(yfinance). 본 대시보드는 참고용이며 투자 판단의 최종 책임은 사용자 본인에게 있습니다.</footer>

<script>
const RESULTS = __RESULTS_JSON__;
const FAILURES = __FAILURES_JSON__;
const ACTION_LABEL = __ACTION_LABEL_JSON__;
const TREND_LABEL = __TREND_LABEL_JSON__;
const ACTION_PRIORITY = {ADD: 0, HOLD: 1, TRIM: 2, SELL: 3};

let sortKey = "action_priority", sortDir = 1;
let marketFilter = "ALL", actionFilter = "ALL";

function fmt(n, d=1) { return (n === null || n === undefined || Number.isNaN(n)) ? "-" : Number(n).toLocaleString(undefined, {minimumFractionDigits:d, maximumFractionDigits:d}); }
function fmtPct(fraction, d=1) { return (fraction === null || fraction === undefined || Number.isNaN(fraction)) ? "-" : fmt(fraction*100, d) + "%"; }
function changeArrow(change) {
  if (change === "up") return '<span class="change-arrow change-up" title="직전 대비 개선">▲</span>';
  if (change === "down") return '<span class="change-arrow change-down" title="직전 대비 악화">▼</span>';
  return "";
}

function renderSummary() {
  const counts = {ADD:0, HOLD:0, TRIM:0, SELL:0};
  RESULTS.forEach(r => counts[r.action] = (counts[r.action]||0) + 1);
  const el = document.getElementById("summary");
  el.innerHTML = ["ADD","HOLD","TRIM","SELL"].map(a =>
    `<div class="stat-tile"><div class="n">${counts[a]}</div><div class="l">${ACTION_LABEL[a]}</div></div>`
  ).join("") + `<div class="stat-tile"><div class="n">${RESULTS.length}</div><div class="l">전체 종목</div></div>`;
}

function renderControls() {
  const markets = ["ALL", "KR", "US"];
  const actions = ["ALL", "ADD", "HOLD", "TRIM", "SELL"];
  const el = document.getElementById("controls");
  el.innerHTML =
    markets.map(m => `<button data-kind="market" data-val="${m}" class="${m===marketFilter?'active':''}">${m==='ALL'?'전체 시장':m}</button>`).join("") +
    '<span style="width:8px"></span>' +
    actions.map(a => `<button data-kind="action" data-val="${a}" class="${a===actionFilter?'active':''}">${a==='ALL'?'전체 액션':ACTION_LABEL[a]}</button>`).join("");
  el.querySelectorAll("button").forEach(btn => btn.addEventListener("click", () => {
    if (btn.dataset.kind === "market") marketFilter = btn.dataset.val; else actionFilter = btn.dataset.val;
    renderControls(); renderTable();
  }));
}

function renderTable() {
  let rows = RESULTS.filter(r => (marketFilter==="ALL"||r.market===marketFilter) && (actionFilter==="ALL"||r.action===actionFilter));
  rows.sort((a,b) => {
    if (sortKey === "action_priority") {
      const diff = ACTION_PRIORITY[a.action] - ACTION_PRIORITY[b.action];
      if (diff !== 0) return diff;
      return (b.score_now ?? -Infinity) - (a.score_now ?? -Infinity);
    }
    if (sortKey === "action" || sortKey === "action_1m") {
      const av = ACTION_PRIORITY[a[sortKey]] ?? 99, bv = ACTION_PRIORITY[b[sortKey]] ?? 99;
      return sortDir * (av - bv);
    }
    const av = a[sortKey], bv = b[sortKey];
    if (typeof av === "string") return sortDir * String(av).localeCompare(String(bv));
    return sortDir * ((av ?? -Infinity) - (bv ?? -Infinity));
  });
  const tbody = document.getElementById("tbody");
  tbody.innerHTML = rows.map(r => `
    <tr title="${r.reason.replace(/"/g,'&quot;')}">
      <td class="num" data-label="Ranking 1개월전">${fmt(r.rank_1m,0)}</td>
      <td class="num" data-label="Ranking 현재"><b>${fmt(r.rank_now,0)}</b></td>
      <td class="name-cell" data-label="종목명">${r.name}${r.is_etf ? ' <span class="code-cell">ETF</span>' : ''}</td>
      <td class="code-cell" data-label="코드/티커">${r.code}</td>
      <td class="num" data-label="주가 1개월전">${fmt(r.price_1m,0)}</td>
      <td class="num" data-label="주가 1주일전">${fmt(r.price_1w,0)}</td>
      <td class="num" data-label="주가 현재"><b>${fmt(r.price_now,0)}</b></td>
      <td class="num" data-label="목표가">${fmt(r.target_price,0)}<br><span class="code-cell">${r.target_source}</span></td>
      <td class="num" data-label="상승여력%">${fmt(r.upside_pct,1)}%</td>
      <td class="num" data-label="점수 1개월전">${fmt(r.score_1m,0)}</td>
      <td class="num" data-label="점수 1주일전">${fmt(r.score_1w,0)}</td>
      <td class="num" data-label="점수 현재"><b>${fmt(r.score_now,0)}</b></td>
      <td data-label="추세 단기"><span class="trend trend-${r.short_trend}">${TREND_LABEL[r.short_trend]}</span>${changeArrow(r.short_trend_change)}</td>
      <td data-label="추세 중기"><span class="trend trend-${r.mid_trend}">${TREND_LABEL[r.mid_trend]}</span>${changeArrow(r.mid_trend_change)}</td>
      <td data-label="추세 장기"><span class="trend trend-${r.long_trend}">${TREND_LABEL[r.long_trend]}</span>${changeArrow(r.long_trend_change)}</td>
      <td class="num" data-label="RSI14">${fmt(r.rsi,0)}${changeArrow(r.rsi_change)}</td>
      <td class="num" data-label="Band%">${fmtPct(r.band_pct,1)}${changeArrow(r.band_pct_change)}</td>
      <td class="num" data-label="Vol比">${fmt(r.vol_ratio,2)}</td>
      <td data-label="액션 1개월전">${r.action_1m ? `<span class="badge badge-${r.action_1m}">${ACTION_LABEL[r.action_1m]}</span>` : "-"}</td>
      <td data-label="액션 현재"><span class="badge badge-${r.action}">${ACTION_LABEL[r.action]}</span>${changeArrow(r.action_change)}</td>
      <td class="alerts-cell" data-label="신호" title="${(r.alerts||[]).join(', ').replace(/"/g,'&quot;')}">${
        (r.alerts && r.alerts.length) ? r.alerts.slice(0,2).map(a => `<span class="alert-badge">${a}</span>`).join("") : ""
      }</td>
    </tr>`).join("");
}

document.querySelectorAll("thead th[data-key]").forEach(th => th.addEventListener("click", () => {
  const key = th.dataset.key;
  if (sortKey === key) sortDir *= -1; else { sortKey = key; sortDir = -1; }
  renderTable();
}));

function renderFailures() {
  const el = document.getElementById("failures");
  if (!FAILURES.length) { el.innerHTML = ""; return; }
  el.innerHTML = `<details><summary>데이터 수집 실패 ${FAILURES.length}건</summary><ul>` +
    FAILURES.map(f => `<li>${f.name} (${f.code}): ${f.error}</li>`).join("") + `</ul></details>`;
}

renderSummary(); renderControls(); renderTable(); renderFailures();
</script>
</body>
</html>
"""


def generate_dashboard(results: list[dict], failures: list[dict], out_path: Path,
                        title: str = "보유 주식/ETF 매매 신호 대시보드") -> None:
    import datetime as dt

    out_path = Path(out_path)
    previous = _load_previous_results(out_path)
    _annotate_changes(results, previous)

    html = TEMPLATE
    html = html.replace("__TITLE__", title)
    html = html.replace("__GENERATED_AT__", dt.datetime.now().strftime("%Y-%m-%d %H:%M"))
    html = html.replace("__N_RESULTS__", str(len(results)))
    html = html.replace("__RESULTS_JSON__", json.dumps(results, ensure_ascii=False))
    html = html.replace("__FAILURES_JSON__", json.dumps(failures, ensure_ascii=False))
    html = html.replace("__ACTION_LABEL_JSON__", json.dumps(ACTION_LABEL, ensure_ascii=False))
    html = html.replace("__TREND_LABEL_JSON__", json.dumps(TREND_LABEL, ensure_ascii=False))

    out_path.write_text(html, encoding="utf-8")

    # 일자별 백업: 같은 날 여러 번 생성해도 그날 파일 하나만 최신 내용으로 덮어쓴다.
    backup_dir = out_path.parent / "data" / "dashboard_backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_name = f"{out_path.stem}_{dt.date.today().strftime('%y%m%d')}{out_path.suffix}"
    (backup_dir / backup_name).write_text(html, encoding="utf-8")

    _git_commit_and_push(out_path.parent, f"Update {out_path.name} ({dt.datetime.now().strftime('%Y-%m-%d %H:%M')})")


def _git_commit_and_push(repo_root: Path, message: str) -> None:
    """대시보드 생성 후 자동 git add/commit/push. 실패해도 대시보드 생성 자체는 막지 않는다
    (git 미설치, 원격 미설정, 네트워크/인증 문제 등은 경고만 출력하고 넘어간다)."""
    import subprocess

    def run(args):
        return subprocess.run(
            ["git", *args], cwd=repo_root, capture_output=True, text=True, timeout=60,
        )

    try:
        if not (repo_root / ".git").exists():
            return
        status = run(["status", "--porcelain"])
        if status.returncode != 0:
            print(f"  [git] status 확인 실패, 자동 push 건너뜀: {status.stderr.strip()}")
            return
        if not status.stdout.strip():
            return  # 변경사항 없음

        add = run(["add", "-A"])
        if add.returncode != 0:
            print(f"  [git] add 실패: {add.stderr.strip()}")
            return

        commit = run(["commit", "-m", message])
        if commit.returncode != 0:
            print(f"  [git] commit 실패: {commit.stderr.strip()}")
            return

        push = run(["push"])
        if push.returncode != 0:
            print(f"  [git] push 실패(로컬 커밋은 유지됨) - 인증/네트워크 확인 필요: {push.stderr.strip()}")
        else:
            print(f"  [git] GitHub push 완료: {message}")
    except Exception as e:
        print(f"  [git] 자동 push 중 오류(무시하고 계속 진행): {type(e).__name__}: {e}")
