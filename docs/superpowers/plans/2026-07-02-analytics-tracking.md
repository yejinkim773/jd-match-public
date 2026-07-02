# Analytics Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** localStorage 기반 영구 익명 ID, UTM 채널 추적, 테스트 트래픽 분리(`is_internal`)를 PostHog 이벤트에 적용한다.

**Architecture:** `modules/events.py`의 `capture()`가 `st.session_state`에서 uid/is_internal/utm_source를 읽어 모든 이벤트에 자동 첨부한다. `app.py` 시작부에서 `st_javascript`로 localStorage를 읽고 그 값을 `st.session_state`에 저장한다. 모듈 레벨 전역변수는 사용하지 않는다 (Streamlit 멀티세션 환경에서 유저 간 데이터 오염 방지).

**Tech Stack:** Streamlit, streamlit-javascript, PostHog Python SDK, pytest

---

## 파일 구조

| 파일 | 변경 내용 |
|------|----------|
| `modules/events.py` | `_session_id()` 제거 → `_tracking_context()` 추가, `capture()` 업데이트 |
| `tests/test_events.py` | 기존 3개 테스트 수정 + 2개 신규 |
| `app.py` | 시작부(32~55줄) — localStorage JS 읽기, session_state 저장, PostHog init 조건 변경 |

---

## Task 1: tests/test_events.py 업데이트

**Files:**
- Modify: `tests/test_events.py`

기존 테스트는 `_session_id`를 패치하고 `capture()` 호출을 위치인수로 검증한다. 새 API는 `_tracking_context()`를 패치하고 키워드 인수로 검증한다. 기존 테스트를 모두 교체한다.

- [ ] **Step 1: 테스트 파일 전체 교체**

`tests/test_events.py`를 아래 내용으로 교체한다:

```python
from unittest.mock import MagicMock, patch
import modules.events as events


def test_capture_calls_posthog_client():
    mock_client = MagicMock()
    events._client = mock_client
    with patch.object(events, "_tracking_context", return_value=("sess-abc", False, "")):
        events.capture("analysis_started", {"score": 82})
    mock_client.capture.assert_called_once_with(
        distinct_id="sess-abc",
        event="analysis_started",
        properties={"score": 82, "is_internal": False, "utm_source": ""},
    )
    events._client = None


def test_capture_noop_when_not_initialized():
    events._client = None
    events.capture("analysis_started")  # 예외 없이 종료


def test_capture_uses_empty_dict_when_no_properties():
    mock_client = MagicMock()
    events._client = mock_client
    with patch.object(events, "_tracking_context", return_value=("sess-xyz", False, "")):
        events.capture("app_loaded")
    mock_client.capture.assert_called_once_with(
        distinct_id="sess-xyz",
        event="app_loaded",
        properties={"is_internal": False, "utm_source": ""},
    )
    events._client = None


def test_capture_attaches_is_internal_true():
    mock_client = MagicMock()
    events._client = mock_client
    with patch.object(events, "_tracking_context", return_value=("uid-123", True, "ev")):
        events.capture("app_loaded")
    props = mock_client.capture.call_args.kwargs["properties"]
    assert props["is_internal"] is True
    assert props["utm_source"] == "ev"
    events._client = None


def test_capture_utm_source_preserved_with_other_properties():
    mock_client = MagicMock()
    events._client = mock_client
    with patch.object(events, "_tracking_context", return_value=("uid-456", False, "lk")):
        events.capture("jd_registered", {"method": "url"})
    props = mock_client.capture.call_args.kwargs["properties"]
    assert props["utm_source"] == "lk"
    assert props["method"] == "url"
    events._client = None
```

- [ ] **Step 2: 테스트 실행 — FAIL 확인**

```
pytest tests/test_events.py -v
```

기대 결과: `test_capture_calls_posthog_client`, `test_capture_uses_empty_dict_when_no_properties` 등 FAIL. `_tracking_context` 없음 에러.

---

## Task 2: modules/events.py 리팩토링

**Files:**
- Modify: `modules/events.py`

- [ ] **Step 1: events.py 전체 교체**

```python
import streamlit as st

_client = None


def init(api_key: str) -> None:
    from posthog import Posthog
    global _client
    if _client is not None:
        return
    _client = Posthog(
        project_api_key=api_key,
        host="https://us.i.posthog.com",
        flush_at=1,
    )


def _tracking_context() -> tuple[str, bool, str]:
    return (
        st.session_state.get("_uid", ""),
        st.session_state.get("_is_internal", False),
        st.session_state.get("_utm_source", ""),
    )


def capture(event: str, properties: dict | None = None) -> None:
    if _client is None:
        return
    uid, is_internal, utm_source = _tracking_context()
    props = {
        "is_internal": is_internal,
        "utm_source": utm_source,
        **(properties or {}),
    }
    _client.capture(
        distinct_id=uid,
        event=event,
        properties=props,
    )
```

- [ ] **Step 2: 테스트 실행 — PASS 확인**

```
pytest tests/test_events.py -v
```

기대 결과: 5개 모두 PASS.

- [ ] **Step 3: 커밋**

```bash
git add modules/events.py tests/test_events.py
git commit -m "refactor: events.py — session_state 기반 tracking context로 교체"
```

---

## Task 3: app.py 시작부 업데이트

**Files:**
- Modify: `app.py:32-55`

Streamlit은 매 인터랙션마다 전체 스크립트를 재실행한다. `st_javascript`는 첫 실행 시 `0`(int)을 반환하고, 다음 실행부터 실제 값을 반환한다. `isinstance(..., str)` 가드로 유효한 값이 들어왔을 때만 session_state를 업데이트한다.

- [ ] **Step 1: `_DEFAULTS`에 tracking 키 추가 및 localStorage JS 블록 삽입**

`app.py`의 아래 블록을 찾아 교체한다.

찾을 코드 (`app.py:32-55`):
```python
# ── 초기화 ────────────────────────────────────────────────────
st.set_page_config(page_title="FitCheck", page_icon="✓")

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
    "_daily_count": 0,
}
for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

if not st.session_state.app_loaded_captured:
    events.capture("app_loaded")
    st.session_state.app_loaded_captured = True
```

교체할 코드:
```python
# ── 초기화 ────────────────────────────────────────────────────
st.set_page_config(page_title="FitCheck", page_icon="✓")

_posthog_key = st.secrets.get("POSTHOG_KEY", "")

_DEFAULTS: dict = {
    "step": 1,
    "resume_text": "",
    "jd_text": "",
    "jd_url": "",
    "analysis_result": None,
    "feedback_submitted": False,
    "app_loaded_captured": False,
    "_daily_count": 0,
    "_uid": "",
    "_is_internal": False,
    "_utm_source": "",
}
for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

# ── localStorage 읽기 (JS) ──────────────────────────────────
if _JS_ENABLED:
    _uid_raw = st_javascript("""
    (function() {
        try {
            let uid = localStorage.getItem('fitcheck_uid');
            if (!uid) {
                uid = crypto.randomUUID();
                localStorage.setItem('fitcheck_uid', uid);
            }
            return uid;
        } catch(e) { return crypto.randomUUID(); }
    })()
    """)

    _i_flag = st.query_params.get("_i", "")
    if _i_flag not in ("0", "1"):
        _i_flag = ""
    _internal_raw = st_javascript(f"""
    (function() {{
        const flag = "{_i_flag}";
        if (flag === '1') localStorage.setItem('fitcheck_internal', 'true');
        else if (flag === '0') localStorage.removeItem('fitcheck_internal');
        return localStorage.getItem('fitcheck_internal') === 'true';
    }})()
    """)

    import re as _re
    _utm_from_url = _re.sub(r'[^a-z0-9\-]', '', st.query_params.get("utm_source", "").lower())[:20]
    _utm_raw = st_javascript(f"""
    (function() {{
        const source = "{_utm_from_url}";
        if (source && !localStorage.getItem('fitcheck_utm_source')) {{
            localStorage.setItem('fitcheck_utm_source', source);
        }}
        return localStorage.getItem('fitcheck_utm_source') || '';
    }})()
    """)

    if isinstance(_uid_raw, str) and _uid_raw:
        st.session_state._uid = _uid_raw
        st.session_state._is_internal = _internal_raw is True
        st.session_state._utm_source = _utm_raw if isinstance(_utm_raw, str) else ""

# ── PostHog 초기화 ────────────────────────────────────────────
if _posthog_key and st.session_state._uid:
    events.init(_posthog_key)

if not st.session_state.app_loaded_captured and events._client is not None:
    events.capture("app_loaded")
    st.session_state.app_loaded_captured = True
```

- [ ] **Step 2: 기존 테스트 전체 통과 확인**

```
pytest -v
```

기대 결과: 전체 PASS. (`app.py`는 Streamlit 런타임 없이 import 불가하므로 테스트 대상 아님)

- [ ] **Step 3: 커밋**

```bash
git add app.py
git commit -m "feat: localStorage 기반 영구 UID, UTM 채널 추적, is_internal 플래그 추가"
```

---

## Task 4: 수동 검증

자동화 테스트가 불가능한 Streamlit + JS 동작을 직접 확인한다.

- [ ] **Step 1: 앱 실행**

```
streamlit run app.py
```

- [ ] **Step 2: 영구 UID 확인**

브라우저 개발자도구 → Application → Local Storage → `fitcheck_uid` 키 존재 확인.  
새로고침 후 같은 값인지 확인.

- [ ] **Step 3: is_internal 플래그 확인**

`http://localhost:8501/?_i=1` 접속 → Local Storage에 `fitcheck_internal = true` 확인.  
PostHog 대시보드에서 `app_loaded` 이벤트의 `is_internal: true` 프로퍼티 확인.  
`http://localhost:8501/?_i=0` 접속 → `fitcheck_internal` 제거 확인.

- [ ] **Step 4: UTM 추적 확인**

`http://localhost:8501/?utm_source=ev` 접속 → Local Storage에 `fitcheck_utm_source = ev` 확인.  
URL 파라미터 없이 새로고침 → 기존 값 유지 확인 (first-touch attribution).  
PostHog에서 `app_loaded` 이벤트의 `utm_source: "ev"` 프로퍼티 확인.

- [ ] **Step 5: 재방문 UID 확인**

브라우저 탭 닫기 → 새 탭에서 앱 재접속 → Local Storage에서 동일한 `fitcheck_uid` 확인.  
PostHog에서 같은 `distinct_id`로 두 번의 `app_loaded` 이벤트가 기록됐는지 확인.

---

## 참고: bit.ly 링크 생성 (별도 작업)

코드 외 작업. 구현 완료 후 bit.ly에서 채널별 링크 생성:

```
https://yourapp.streamlit.app/?utm_source=ev&utm_medium=community
https://yourapp.streamlit.app/?utm_source=lk&utm_medium=community
https://yourapp.streamlit.app/?utm_source=kt&utm_medium=dm
```

각 링크를 bit.ly에서 단축 URL로 만들어 채널별로 배포.
