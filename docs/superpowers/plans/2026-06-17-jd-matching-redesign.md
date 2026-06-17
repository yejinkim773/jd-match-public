# JD 매칭 분석기 퍼블릭 서비스 리디자인 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Google Sheets 사용자 연동을 제거하고, 누구나 이력서 + JD를 입력해 바로 분석할 수 있는 멀티스텝 위자드 서비스로 재구성한다. PostHog 퍼널 추적, 피드백 수집(Yes/No + 이유), 결과 공유(텍스트 복사/이미지 저장)를 포함한다.

**Architecture:** `app.py`를 멀티스텝 위자드(Step 1~4)로 전면 재작성. `st.session_state.step`으로 현재 스텝을 관리하고, 각 스텝을 독립 함수로 분리. 이벤트 추적은 `modules/events.py`에서 PostHog Python SDK로 서버사이드 캡처. 피드백은 백엔드에서만 Google Sheets에 기록 (사용자 노출 없음). `modules/analyzer.py`, `modules/crawler.py`는 변경 없이 재사용.

**Tech Stack:** Streamlit, PostHog Python SDK (`posthog>=3.0.0`), Pillow, pdfplumber, gspread, google-auth, google-generativeai

---

## File Map

| 파일 | 처리 | 역할 |
|------|------|------|
| `app.py` | 전면 재작성 | 멀티스텝 위자드 UI 및 라우팅 |
| `modules/events.py` | 신규 생성 | PostHog 이벤트 캡처 |
| `modules/result_image.py` | 신규 생성 | Pillow 결과 카드 이미지 생성 |
| `modules/sheets_api.py` | 대폭 축소 | 피드백 저장 전용 (`save_feedback`) |
| `modules/analyzer.py` | 변경 없음 | AI 매칭 분석 |
| `modules/crawler.py` | 변경 없음 | JD 크롤링 |
| `requirements.txt` | `posthog>=3.0.0` 추가 | - |
| `requirements-dev.txt` | 신규 생성 | pytest (개발 전용) |
| `tests/__init__.py` | 신규 생성 | - |
| `tests/test_events.py` | 신규 생성 | 이벤트 모듈 단위 테스트 |
| `tests/test_result_image.py` | 신규 생성 | 이미지 생성 단위 테스트 |
| `tests/test_feedback.py` | 신규 생성 | 피드백 저장 단위 테스트 |

---

## Task 1: 의존성 추가 + events 모듈

**Files:**
- Modify: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `modules/events.py`
- Create: `tests/__init__.py`
- Create: `tests/test_events.py`

- [ ] **Step 1: requirements.txt에 posthog 추가**

`requirements.txt` 마지막 줄에 추가:
```
posthog>=3.0.0
```

- [ ] **Step 2: requirements-dev.txt 생성**

```
pytest>=8.0.0
pytest-mock>=3.14.0
```

- [ ] **Step 3: 개발 의존성 설치**

Run: `pip install posthog pytest pytest-mock`
Expected: Successfully installed 메시지, 오류 없음

- [ ] **Step 4: tests/__init__.py 생성** (빈 파일)

- [ ] **Step 5: 실패하는 테스트 작성**

`tests/test_events.py`:
```python
from unittest.mock import MagicMock, patch
import modules.events as events


def test_capture_calls_posthog_client():
    mock_client = MagicMock()
    events._client = mock_client
    with patch.object(events, "_session_id", return_value="sess-abc"):
        events.capture("analysis_started", {"score": 82})
    mock_client.capture.assert_called_once_with(
        "sess-abc", "analysis_started", {"score": 82}
    )
    events._client = None


def test_capture_noop_when_not_initialized():
    events._client = None
    events.capture("analysis_started")  # 예외 없이 종료


def test_capture_uses_empty_dict_when_no_properties():
    mock_client = MagicMock()
    events._client = mock_client
    with patch.object(events, "_session_id", return_value="sess-xyz"):
        events.capture("app_loaded")
    mock_client.capture.assert_called_once_with("sess-xyz", "app_loaded", {})
    events._client = None
```

- [ ] **Step 6: 테스트 실행 — 실패 확인**

Run: `pytest tests/test_events.py -v`
Expected: `ImportError: No module named 'modules.events'`

- [ ] **Step 7: events.py 구현**

`modules/events.py`:
```python
import uuid
import streamlit as st

_client = None


def init(api_key: str) -> None:
    from posthog import Posthog
    global _client
    _client = Posthog(project_api_key=api_key, host="https://app.posthog.com")


def _session_id() -> str:
    if "session_id" not in st.session_state:
        st.session_state.session_id = str(uuid.uuid4())
    return st.session_state.session_id


def capture(event: str, properties: dict | None = None) -> None:
    if _client is None:
        return
    _client.capture(_session_id(), event, properties or {})
```

- [ ] **Step 8: 테스트 실행 — 통과 확인**

Run: `pytest tests/test_events.py -v`
Expected: `3 passed`

- [ ] **Step 9: 커밋**

```bash
git add requirements.txt requirements-dev.txt modules/events.py tests/
git commit -m "feat: PostHog 이벤트 모듈 추가"
```

---

## Task 2: sheets_api.py 피드백 전용으로 축소

**Files:**
- Modify: `modules/sheets_api.py` (전체 교체)
- Create: `tests/test_feedback.py`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_feedback.py`:
```python
from unittest.mock import MagicMock, patch, call
from datetime import datetime


def test_save_feedback_appends_row():
    mock_ws = MagicMock()
    with patch("modules.sheets_api._feedback_sheet", return_value=mock_ws), \
         patch("modules.sheets_api.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 6, 17, 12, 0, 0)
        from modules.sheets_api import save_feedback
        save_feedback(helpful=True, reason="", score=82)

    mock_ws.append_row.assert_called_once_with(
        ["2026-06-17T12:00:00", "yes", "", 82]
    )


def test_save_feedback_no_when_not_helpful():
    mock_ws = MagicMock()
    with patch("modules.sheets_api._feedback_sheet", return_value=mock_ws), \
         patch("modules.sheets_api.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 6, 17, 12, 0, 0)
        from modules.sheets_api import save_feedback
        save_feedback(helpful=False, reason="결과가 부정확한 것 같아요", score=45)

    mock_ws.append_row.assert_called_once_with(
        ["2026-06-17T12:00:00", "no", "결과가 부정확한 것 같아요", 45]
    )
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

Run: `pytest tests/test_feedback.py -v`
Expected: `ImportError` 또는 `AttributeError` (save_feedback 없음)

- [ ] **Step 3: sheets_api.py 전면 교체**

`modules/sheets_api.py`:
```python
from datetime import datetime

import gspread
import streamlit as st
from google.oauth2.service_account import Credentials

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]
_FEEDBACK_HEADERS = ["타임스탬프", "도움여부", "이유", "스코어"]


def _feedback_sheet() -> gspread.Worksheet:
    creds = Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]), scopes=_SCOPES
    )
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(st.secrets["SPREADSHEET_ID"])
    try:
        ws = spreadsheet.worksheet("피드백")
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title="피드백", rows=1000, cols=4)
        ws.append_row(_FEEDBACK_HEADERS)
    return ws


def save_feedback(helpful: bool, reason: str, score: int) -> None:
    ws = _feedback_sheet()
    ws.append_row([
        datetime.now().isoformat(),
        "yes" if helpful else "no",
        reason,
        score,
    ])
```

- [ ] **Step 4: 테스트 실행 — 통과 확인**

Run: `pytest tests/test_feedback.py -v`
Expected: `2 passed`

- [ ] **Step 5: 커밋**

```bash
git add modules/sheets_api.py tests/test_feedback.py
git commit -m "refactor: sheets_api 피드백 저장 전용으로 축소"
```

---

## Task 3: result_image.py — 결과 카드 이미지 생성

**Files:**
- Create: `modules/result_image.py`
- Create: `tests/test_result_image.py`

결과 카드 레이아웃 (800×480px):
```
┌────────────────────────────────────────┐
│  🎯 JD 매칭 분석기                      │  헤더 (진한 배경)
├────────────────────────────────────────┤
│  카카오 · PM (서비스기획)               │  회사 · 포지션
│                                        │
│  매칭 스코어  82점                      │  스코어
│  ████████████████░░░░                  │  진행바
│                                        │
│  SQL 실무 경험을 보완하면...            │  총평 (2줄 자름)
│                                        │
│  jd-match.streamlit.app               │  워터마크
└────────────────────────────────────────┘
```

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_result_image.py`:
```python
from PIL import Image
import io
from modules.result_image import generate_result_image


_SAMPLE = {
    "company": "카카오",
    "position": "PM (서비스기획)",
    "score": 82,
    "summary": "SQL 실무 경험을 구체적으로 보완하면 지원 경쟁력이 높아질 것 같아요.",
}


def test_returns_bytes():
    result = generate_result_image(_SAMPLE)
    assert isinstance(result, bytes)
    assert len(result) > 0


def test_output_is_valid_png():
    result = generate_result_image(_SAMPLE)
    img = Image.open(io.BytesIO(result))
    assert img.format == "PNG"


def test_image_dimensions():
    result = generate_result_image(_SAMPLE)
    img = Image.open(io.BytesIO(result))
    assert img.width == 800
    assert img.height == 480


def test_handles_missing_fields():
    result = generate_result_image({})
    assert isinstance(result, bytes)
```

- [ ] **Step 2: 테스트 실행 — 실패 확인**

Run: `pytest tests/test_result_image.py -v`
Expected: `ImportError: No module named 'modules.result_image'`

- [ ] **Step 3: result_image.py 구현**

`modules/result_image.py`:
```python
import io
from PIL import Image, ImageDraw, ImageFont

_W, _H = 800, 480
_HEADER_H = 64
_BG = "#FFFFFF"
_HEADER_BG = "#1E293B"
_TEXT_DARK = "#1E293B"
_TEXT_GRAY = "#64748B"
_BAR_FILL = "#3B82F6"
_BAR_BG = "#E2E8F0"


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "C:/Windows/Fonts/malgun.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _wrap(text: str, max_chars: int = 45) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars - 1] + "…"


def generate_result_image(result: dict) -> bytes:
    img = Image.new("RGB", (_W, _H), color=_BG)
    draw = ImageDraw.Draw(img)

    # 헤더 배경
    draw.rectangle([0, 0, _W, _HEADER_H], fill=_HEADER_BG)
    draw.text((24, 18), "🎯 JD 매칭 분석기", fill="#FFFFFF", font=_font(20))

    # 회사 · 포지션
    company = result.get("company", "")
    position = result.get("position", "")
    title = f"{company}  ·  {position}" if company or position else "분석 결과"
    draw.text((32, _HEADER_H + 24), title, fill=_TEXT_DARK, font=_font(22))

    # 스코어
    score = int(result.get("score", 0))
    draw.text((32, _HEADER_H + 72), "매칭 스코어", fill=_TEXT_GRAY, font=_font(14))
    draw.text((32, _HEADER_H + 92), f"{score}점", fill=_TEXT_DARK, font=_font(36))

    # 진행바
    bar_y = _HEADER_H + 144
    bar_w = _W - 64
    bar_h = 12
    draw.rounded_rectangle([32, bar_y, 32 + bar_w, bar_y + bar_h], radius=6, fill=_BAR_BG)
    fill_w = int(bar_w * score / 100)
    if fill_w > 0:
        draw.rounded_rectangle([32, bar_y, 32 + fill_w, bar_y + bar_h], radius=6, fill=_BAR_FILL)

    # 총평
    summary = result.get("summary", "")
    draw.text((32, bar_y + 32), "총평", fill=_TEXT_GRAY, font=_font(14))
    draw.text((32, bar_y + 52), _wrap(summary, 52), fill=_TEXT_DARK, font=_font(16))

    # 워터마크
    draw.text((32, _H - 32), "jd-match.streamlit.app", fill=_TEXT_GRAY, font=_font(13))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
```

- [ ] **Step 4: 테스트 실행 — 통과 확인**

Run: `pytest tests/test_result_image.py -v`
Expected: `4 passed`

- [ ] **Step 5: 커밋**

```bash
git add modules/result_image.py tests/test_result_image.py
git commit -m "feat: 결과 카드 이미지 생성 모듈 추가"
```

---

## Task 4: app.py — 스텝 스캐폴드 (세션 상태 + 인디케이터 + 라우팅)

**Files:**
- Modify: `app.py` (전면 재작성 시작)

- [ ] **Step 1: app.py를 스캐폴드로 교체**

`app.py` 전체를 아래로 교체:
```python
import io
from pathlib import Path

import pdfplumber
import streamlit as st

import modules.events as events
from modules.analyzer import analyze_match, extract_text_from_image
from modules.crawler import fetch_jd_from_url, fetch_images_from_url
from modules.result_image import generate_result_image

try:
    from modules.sheets_api import save_feedback as _save_feedback
    _FEEDBACK_ENABLED = True
except Exception:
    _FEEDBACK_ENABLED = False


# ── 초기화 ────────────────────────────────────────────────────
st.set_page_config(page_title="JD 매칭 분석기", page_icon="🎯")

_posthog_key = st.secrets.get("POSTHOG_KEY", "")
if _posthog_key:
    events.init(_posthog_key)

_DEFAULTS: dict = {
    "step": 1,
    "resume_text": "",
    "jd_text": "",
    "jd_url": "",
    "analysis_result": None,
    "feedback_submitted": False,
    "app_loaded_captured": False,
}
for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

if not st.session_state.app_loaded_captured:
    events.capture("app_loaded")
    st.session_state.app_loaded_captured = True


# ── 스텝 인디케이터 ───────────────────────────────────────────
def render_step_indicator(current: int) -> None:
    labels = ["① 이력서", "② JD 입력", "③ 결과"]
    cols = st.columns(3)
    for i, (col, label) in enumerate(zip(cols, labels), start=1):
        with col:
            if i < current:
                st.markdown(f"<p style='text-align:center;color:#10B981'>✅ {label}</p>",
                            unsafe_allow_html=True)
            elif i == current:
                st.markdown(f"<p style='text-align:center;font-weight:700'>{label}</p>",
                            unsafe_allow_html=True)
            else:
                st.markdown(f"<p style='text-align:center;color:#94A3B8'>{label}</p>",
                            unsafe_allow_html=True)
    st.divider()


# ── 스텝별 렌더 함수 (다음 Task에서 구현) ─────────────────────
def render_step1() -> None:
    st.info("Step 1 — 준비 중")


def render_step2() -> None:
    st.info("Step 2 — 준비 중")


def render_step3() -> None:
    st.info("Step 3 — 준비 중")


def render_step4() -> None:
    st.info("Step 4 — 준비 중")


# ── 라우팅 ────────────────────────────────────────────────────
render_step_indicator(min(st.session_state.step, 3))

step = st.session_state.step
if step == 1:
    render_step1()
elif step == 2:
    render_step2()
elif step == 3:
    render_step3()
else:
    render_step4()
```

- [ ] **Step 2: 앱 실행 — 수동 확인**

Run: `streamlit run app.py`

확인 사항:
- 브라우저에서 상단에 "① 이력서 / ② JD 입력 / ③ 결과" 인디케이터 표시
- "Step 1 — 준비 중" 텍스트 표시
- 콘솔에 오류 없음

- [ ] **Step 3: 커밋**

```bash
git add app.py
git commit -m "refactor: app.py 멀티스텝 위자드 스캐폴드"
```

---

## Task 5: Step 1 — 이력서 입력 UI

**Files:**
- Modify: `app.py` — `render_step1()` 구현

- [ ] **Step 1: render_step1() 교체**

`app.py`의 `render_step1()` 함수 전체를 아래로 교체:
```python
_RESUME_TEMPLATE = """\
📋 학력
예) 한국대학교 컴퓨터공학과 졸업 (2024)

💼 경력 (신입이면 생략 가능)
예) ABC회사 마케팅팀 인턴 (2023.07~12)
[요약] 신규 유저 온보딩 개선 프로젝트 담당, 전환율 12% 향상 기여
[상세]
- 유저 인터뷰 10명 진행 및 페인포인트 분석
- Notion 기반 온보딩 플로우 재설계 및 A/B 테스트 운영
- GA4로 퍼널 이탈 구간 파악 후 개선안 도출

🛠 스킬
예) Python, SQL, Figma, Google Analytics

📁 프로젝트
예) 사용자 행동 분석 대시보드 구축
- Looker Studio + BigQuery 활용하여 주간 리포트 자동화
"""


def render_step1() -> None:
    st.subheader("이력서를 입력해주세요")

    tab_pdf, tab_text = st.tabs(["📄 PDF 업로드", "✏️ 직접 입력"])

    with tab_pdf:
        uploaded = st.file_uploader(
            "PDF 이력서 업로드",
            type=["pdf"],
            help="업로드하면 텍스트를 자동으로 추출해드려요",
        )
        if uploaded:
            file_id = f"{uploaded.name}_{uploaded.size}"
            if st.session_state.get("_last_pdf_id") != file_id:
                with pdfplumber.open(io.BytesIO(uploaded.read())) as pdf:
                    extracted = "\n".join(
                        p.extract_text() or "" for p in pdf.pages
                    ).strip()
                if extracted:
                    st.session_state.resume_text = extracted
                    st.session_state["_last_pdf_id"] = file_id
                    st.success("✅ 텍스트 추출 완료! 아래에서 확인하세요.")
                else:
                    st.warning("⚠️ 이 PDF에서 텍스트를 읽지 못했어요. '직접 입력' 탭을 이용해주세요.")
            if st.session_state.resume_text:
                st.text_area("추출된 이력서 (수정 가능)", value=st.session_state.resume_text,
                             height=300, key="_pdf_preview")

    with tab_text:
        edited = st.text_area(
            "이력서 내용 입력",
            value=st.session_state.resume_text or _RESUME_TEMPLATE,
            height=400,
            placeholder=_RESUME_TEMPLATE,
            key="_text_resume",
        )
        if st.button("✅ 이력서 저장", type="secondary"):
            st.session_state.resume_text = edited
            st.success("저장됐어요!")

    st.divider()
    if st.button("다음 →", type="primary",
                 disabled=not st.session_state.resume_text.strip()):
        events.capture("resume_completed",
                       {"method": "pdf" if st.session_state.get("_last_pdf_id") else "text"})
        st.session_state.step = 2
        st.rerun()
```

- [ ] **Step 2: 앱 실행 — 수동 확인**

Run: `streamlit run app.py`

확인 사항:
- "PDF 업로드" / "직접 입력" 탭 표시
- 직접 입력 탭에 섹션별 예시 템플릿 표시 (학력/경력/스킬/프로젝트)
- 경력 섹션에 [요약] + [상세] 구조 포함
- 이력서 비어 있을 때 "다음 →" 버튼 비활성화
- 내용 입력 후 "다음 →" 클릭 시 Step 2 이동

- [ ] **Step 3: 커밋**

```bash
git add app.py
git commit -m "feat: Step 1 이력서 입력 UI (PDF/텍스트 탭, 예시 템플릿)"
```

---

## Task 6: Step 2 — JD 입력 UI + 폴백 흐름

**Files:**
- Modify: `app.py` — `render_step2()` 구현

- [ ] **Step 1: render_step2() 교체**

`app.py`의 `render_step2()` 함수 전체를 아래로 교체:
```python
def _go_next_tab(target: str) -> None:
    st.session_state["_jd_tab_override"] = target


def render_step2() -> None:
    st.subheader("채용공고를 입력해주세요")

    # 폴백으로 탭 강제 이동 시 안내 메시지 표시
    if st.session_state.get("_jd_tab_override") == "image":
        st.warning("📸 자동으로 읽어오지 못했어요. 공고 스크린샷을 업로드해주세요.")
    elif st.session_state.get("_jd_tab_override") == "text":
        st.info("📝 직접 공고 내용을 붙여넣어 주세요.")

    tab_url, tab_text, tab_img = st.tabs(["🔗 URL", "📝 텍스트", "🖼️ 이미지"])

    # ── URL 탭 ──────────────────────────────────────────────
    with tab_url:
        url_input = st.text_input("채용공고 URL 붙여넣기", key="_jd_url_input")
        if st.button("공고 불러오기", disabled=not url_input, key="_fetch_url"):
            with st.spinner("공고를 불러오는 중..."):
                success, result_text = fetch_jd_from_url(url_input)
            if success:
                st.session_state.jd_text = result_text
                st.session_state.jd_url = url_input
                st.session_state.pop("_jd_tab_override", None)
                st.success("✅ 크롤링 성공!")
            else:
                # 폴백 1: 이미지 탭으로
                st.session_state["_jd_tab_override"] = "image"
                st.rerun()

    # ── 텍스트 탭 ────────────────────────────────────────────
    with tab_text:
        manual = st.text_area("채용공고 내용 붙여넣기", height=300, key="_jd_manual")
        if st.button("JD 등록", key="_register_text"):
            if manual.strip():
                st.session_state.jd_text = manual
                st.session_state.jd_url = ""
                st.session_state.pop("_jd_tab_override", None)
                st.success("✅ 등록됐어요!")
            else:
                st.warning("내용을 입력해주세요.")

    # ── 이미지 탭 ────────────────────────────────────────────
    with tab_img:
        uploaded_img = st.file_uploader(
            "공고 스크린샷 업로드",
            type=["png", "jpg", "jpeg", "webp"],
            key="_jd_img",
        )
        if uploaded_img:
            st.image(uploaded_img, use_container_width=True)
            if st.button("이미지에서 텍스트 추출", key="_extract_img"):
                with st.spinner("이미지를 읽는 중..."):
                    try:
                        text = extract_text_from_image(uploaded_img.read())
                        if text.strip():
                            st.session_state.jd_text = text
                            st.session_state.jd_url = ""
                            st.session_state.pop("_jd_tab_override", None)
                            st.success("✅ 추출 완료!")
                        else:
                            # 폴백 2: 텍스트 탭으로
                            st.session_state["_jd_tab_override"] = "text"
                            st.rerun()
                    except Exception:
                        st.session_state["_jd_tab_override"] = "text"
                        st.rerun()

    # ── JD 미리보기 ─────────────────────────────────────────
    if st.session_state.jd_text:
        with st.expander("📄 등록된 공고 확인"):
            st.text(st.session_state.jd_text[:500] + ("..." if len(st.session_state.jd_text) > 500 else ""))

    st.divider()
    col_prev, col_next = st.columns(2)
    with col_prev:
        if st.button("← 이전", use_container_width=True):
            st.session_state.step = 1
            st.rerun()
    with col_next:
        if st.button("🚀 분석 시작", type="primary", use_container_width=True,
                     disabled=not st.session_state.jd_text.strip()):
            events.capture("jd_registered", {"method": _detect_jd_method()})
            events.capture("analysis_started")
            st.session_state.step = 3
            st.rerun()


def _detect_jd_method() -> str:
    if st.session_state.jd_url:
        return "url"
    if st.session_state.get("_jd_img"):
        return "image"
    return "text"
```

- [ ] **Step 2: 앱 실행 — 수동 확인**

Run: `streamlit run app.py`

확인 사항:
- Step 1에서 이력서 입력 후 Step 2 이동
- URL / 텍스트 / 이미지 탭 3개 표시
- 텍스트 탭에서 내용 입력 후 "JD 등록" → 미리보기 표시
- JD 없을 때 "분석 시작" 버튼 비활성화
- "← 이전" 클릭 시 Step 1 복귀

- [ ] **Step 3: 커밋**

```bash
git add app.py
git commit -m "feat: Step 2 JD 입력 UI (URL/텍스트/이미지, 폴백 흐름)"
```

---

## Task 7: Step 3 — 로딩 + 분석 실행

**Files:**
- Modify: `app.py` — `render_step3()` 구현

- [ ] **Step 1: render_step3() 교체**

`app.py`의 `render_step3()` 함수 전체를 아래로 교체:
```python
def render_step3() -> None:
    st.subheader("분석 중이에요...")
    st.caption("이력서와 채용공고를 비교하는 중이에요. 10~20초 소요돼요.")

    with st.spinner("🔍 매칭 결과를 분석하는 중..."):
        try:
            result = analyze_match(
                st.session_state.resume_text,
                st.session_state.jd_text,
            )
        except Exception as e:
            st.error(f"분석 중 오류가 발생했어요: {e}")
            if st.button("← 돌아가기"):
                st.session_state.step = 2
                st.rerun()
            return

    events.capture("analysis_completed", {"score": result.get("score", 0)})
    st.session_state.analysis_result = result
    st.session_state.step = 4
    st.rerun()
```

- [ ] **Step 2: 앱 실행 — 수동 확인**

Run: `streamlit run app.py`

확인 사항:
- Step 2에서 "분석 시작" 클릭 시 Step 3 진입
- 진행바 + 메시지가 순서대로 변경
- 분석 완료 후 Step 4 자동 이동 (10~30초 소요)
- API 키 없을 경우 에러 메시지 + "다시 시도" 버튼

- [ ] **Step 3: 커밋**

```bash
git add app.py
git commit -m "feat: Step 3 로딩 화면 + 분석 실행"
```

---

## Task 8: Step 4 — 결과 + 피드백 + 공유

**Files:**
- Modify: `app.py` — `render_step4()` 구현

- [ ] **Step 1: render_step4() 교체**

`app.py`의 `render_step4()` 함수 전체를 아래로 교체:
```python
def render_step4() -> None:
    result = st.session_state.analysis_result
    if not result:
        st.error("분석 결과가 없어요.")
        if st.button("처음으로"):
            _reset()
        return

    score = result.get("score", 0)

    # ── 헤더 ──────────────────────────────────────────────
    st.markdown(
        f"**{result.get('company', '미확인')}**  ·  {result.get('position', '미확인')}"
    )

    # ── 스코어 ────────────────────────────────────────────
    color = "🟢" if score >= 70 else ("🟡" if score >= 50 else "🔴")
    col_score, col_bar = st.columns([1, 3])
    with col_score:
        st.metric("매칭 스코어", f"{color} {score}점")
    with col_bar:
        st.progress(score / 100)

    # ── 필수요건 ──────────────────────────────────────────
    st.subheader("📋 필수요건")
    for req in result.get("required_matches", []):
        status = req.get("status", "unmatched")
        icon = "✅" if status == "matched" else ("🔍" if status == "partial" else "❌")
        st.write(f"{icon} **{req.get('requirement', '')}**")
        if req.get("evidence"):
            st.caption(f"└ {req.get('evidence')}")
        if status == "partial" and req.get("tip"):
            st.info(f"💡 {req.get('tip')}")

    # ── 강점 ──────────────────────────────────────────────
    if result.get("preferred_matches"):
        st.subheader("⭐ 강점")
        for pref in result.get("preferred_matches", []):
            st.write(f"⭐ **{pref.get('requirement', '')}**")
            st.caption(f"└ {pref.get('evidence', '')}")

    # ── 총평 ──────────────────────────────────────────────
    st.subheader("📝 총평")
    st.info(result.get("summary", ""))

    st.divider()

    # ── 피드백 ────────────────────────────────────────────
    if not st.session_state.feedback_submitted:
        st.markdown("##### 💬 이 분석이 도움이 됐나요?")
        col_yes, col_no = st.columns(2)
        feedback_choice = None
        with col_yes:
            if st.button("👍 도움됐어요", use_container_width=True):
                feedback_choice = True
        with col_no:
            if st.button("👎 아쉬웠어요", use_container_width=True):
                feedback_choice = False
                st.session_state["_show_reason"] = True

        if st.session_state.get("_show_reason"):
            reason = st.radio(
                "어떤 점이 아쉬웠나요?",
                ["결과가 부정확한 것 같아요", "내용이 너무 추상적이에요",
                 "이력서를 잘 못 읽은 것 같아요", "기타"],
                key="_feedback_reason",
            )
            if st.button("제출", type="primary"):
                _submit_feedback(helpful=False, reason=reason, score=score)

        if feedback_choice is True:
            _submit_feedback(helpful=True, reason="", score=score)
    else:
        st.success("피드백 감사해요! 🙏")

    st.divider()

    # ── 공유 / 재분석 ──────────────────────────────────────
    col_copy, col_img, col_reset = st.columns(3)

    with col_copy:
        copy_text = (
            f"[JD 매칭 분석기]\n"
            f"{result.get('company', '')} · {result.get('position', '')}\n"
            f"매칭 스코어: {score}점\n\n"
            f"{result.get('summary', '')}"
        )
        st.download_button(
            "📋 텍스트 복사",
            data=copy_text,
            file_name="jd_match_result.txt",
            mime="text/plain",
            use_container_width=True,
            on_click=lambda: events.capture("result_copied"),
        )

    with col_img:
        img_bytes = generate_result_image(result)
        st.download_button(
            "🖼️ 이미지 저장",
            data=img_bytes,
            file_name="jd_match_result.png",
            mime="image/png",
            use_container_width=True,
            on_click=lambda: events.capture("result_image_saved"),
        )

    with col_reset:
        if st.button("🔄 다시 분석하기", use_container_width=True):
            _reset()


def _submit_feedback(helpful: bool, reason: str, score: int) -> None:
    if _FEEDBACK_ENABLED:
        try:
            _save_feedback(helpful=helpful, reason=reason, score=score)
        except Exception:
            pass  # 피드백 저장 실패는 사용자에게 노출하지 않음
    events.capture("feedback_submitted", {
        "helpful": "yes" if helpful else "no",
        "reason": reason,
        "score": score,
    })
    st.session_state.feedback_submitted = True
    st.session_state.pop("_show_reason", None)
    st.rerun()


def _reset() -> None:
    for k in list(st.session_state.keys()):
        if k not in ("session_id", "app_loaded_captured"):
            del st.session_state[k]
    st.session_state.step = 1
    st.rerun()
```

- [ ] **Step 2: 앱 전체 흐름 수동 확인**

Run: `streamlit run app.py`

확인 사항 (전체 골든 패스):
1. Step 1: 이력서 텍스트 입력 → "다음 →" 클릭
2. Step 2: 텍스트 탭에서 JD 입력 → "JD 등록" → "분석 시작"
3. Step 3: 로딩 메시지 순서 변경 확인
4. Step 4:
   - 스코어 + 진행바 표시
   - 필수요건 아이콘(✅/🔍/❌) 표시
   - "👍 도움됐어요" 클릭 → "피드백 감사해요!" 표시
   - "📋 텍스트 복사" → .txt 파일 다운로드
   - "🖼️ 이미지 저장" → .png 파일 다운로드, 이미지 정상 렌더링
   - "🔄 다시 분석하기" → Step 1 초기화

- [ ] **Step 3: 커밋**

```bash
git add app.py
git commit -m "feat: Step 4 결과 표시, 피드백, 공유/저장 버튼"
```

---

## Task 9: 전체 테스트 실행

**Files:** 없음 (검증 전용)

- [ ] **Step 1: 전체 단위 테스트 실행**

Run: `pytest tests/ -v`
Expected:
```
tests/test_events.py::test_capture_calls_posthog_client PASSED
tests/test_events.py::test_capture_noop_when_not_initialized PASSED
tests/test_events.py::test_capture_uses_empty_dict_when_no_properties PASSED
tests/test_feedback.py::test_save_feedback_appends_row PASSED
tests/test_feedback.py::test_save_feedback_no_when_not_helpful PASSED
tests/test_result_image.py::test_returns_bytes PASSED
tests/test_result_image.py::test_output_is_valid_png PASSED
tests/test_result_image.py::test_image_dimensions PASSED
tests/test_result_image.py::test_handles_missing_fields PASSED
9 passed
```

- [ ] **Step 2: 폴백 흐름 수동 확인**

Run: `streamlit run app.py`

Step 2에서 URL 탭에 크롤링 불가 URL 입력:
- 이미지 탭으로 자동 이동 + 안내 메시지 확인
- 이미지 탭에서 추출 실패 시뮬레이션 → 텍스트 탭 이동 확인

- [ ] **Step 3: "👎 아쉬웠어요" 피드백 흐름 확인**

Step 4에서 "👎 아쉬웠어요" 클릭:
- 이유 선택지 4개 표시 확인
- "제출" 클릭 → "피드백 감사해요!" 메시지 확인

---

## Task 10: 배포 준비

**Files:**
- Modify: `.streamlit/secrets.toml.example`
- Modify: `.gitignore`

- [ ] **Step 1: secrets.toml.example 업데이트**

`.streamlit/secrets.toml.example`:
```toml
# Gemini API 키 (필수)
GOOGLE_API_KEY = "your-google-api-key"

# PostHog 이벤트 추적 키 (선택 — 없으면 이벤트 비활성화)
POSTHOG_KEY = "phc_your-posthog-project-key"

# 피드백 저장용 Google Sheets (선택 — 없으면 피드백 저장 비활성화)
SPREADSHEET_ID = "your-spreadsheet-id"

[gcp_service_account]
type = "service_account"
project_id = "your-project-id"
private_key_id = "your-key-id"
private_key = "-----BEGIN RSA PRIVATE KEY-----\n..."
client_email = "your-service-account@project.iam.gserviceaccount.com"
client_id = "your-client-id"
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
```

- [ ] **Step 2: .gitignore에 superpowers 추가**

`.gitignore`에 아래 줄 추가:
```
.superpowers/
```

- [ ] **Step 3: Streamlit Community Cloud 배포 확인**

Streamlit Community Cloud (share.streamlit.io) 배포 절차:
1. GitHub에 main 브랜치 push
2. share.streamlit.io → "New app" → 레포 연결
3. Advanced settings → Secrets에 `secrets.toml.example` 내용 실제 값으로 입력
4. `service_account.json`은 업로드하지 않음 — Secrets의 `[gcp_service_account]` 섹션으로 대체됨

- [ ] **Step 4: 최종 커밋**

```bash
git add .streamlit/secrets.toml.example .gitignore
git commit -m "chore: 배포 준비 (secrets 예시 업데이트, .gitignore)"
```
