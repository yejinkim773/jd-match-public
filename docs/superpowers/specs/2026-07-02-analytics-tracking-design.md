# FitCheck 애널리틱스 추적 설계

**날짜:** 2026-07-02  
**목적:** PostHog 데이터 신뢰도 향상 — 테스트 트래픽 분리, 채널별 유입 추적, 로그인 없는 재방문 측정

---

## 1. 목표

| 요구사항 | 해결 방식 |
|---------|----------|
| 내 테스트 트래픽이 PostHog 실유저 데이터에 섞이지 않게 | `is_internal` 프로퍼티 + URL 플래그 |
| 채널별 유입 구분 (URL에 채널명 노출 없이) | bit.ly 단축 URL + UTM 파라미터 |
| 새로고침/재방문 시 동일 유저로 인식 | localStorage 기반 영구 익명 ID |

---

## 2. 세션 지속성 — localStorage 익명 ID

### 방식
앱 로드 시 JS로 localStorage에서 `fitcheck_uid`를 읽는다. 없으면 UUID를 생성해 저장한다. 이 값을 PostHog `distinct_id`로 사용한다.

```
첫 방문  → UUID 생성 → localStorage 저장 → PostHog distinct_id
재방문   → localStorage 읽기 → 동일 UUID → 같은 유저로 집계
새로고침 → 동일 흐름
```

### 한계
- 같은 기기/브라우저 내에서만 동작 (카톡 인앱 브라우저 ↔ 크롬 전환 시 다른 ID)
- 다른 기기는 별도 유저로 집계
- 로그인 없는 구조의 근본적 한계이며, GA4·Mixpanel도 동일 제약

### 구현
`streamlit-javascript`(`st_javascript`)로 JS 실행 후 반환값을 `st.session_state.uid`에 저장.

```python
uid_js = """
(function() {
    let uid = localStorage.getItem('fitcheck_uid');
    if (!uid) {
        uid = crypto.randomUUID();
        localStorage.setItem('fitcheck_uid', uid);
    }
    return uid;
})()
"""
uid = st_javascript(uid_js)
```

`st_javascript`는 첫 실행 시 `0`을 반환하는 타이밍 이슈가 있으므로, `uid`가 유효한 문자열일 때만 PostHog를 초기화한다.

---

## 3. 채널 추적 — bit.ly + UTM (first-touch attribution)

### 방식
bit.ly에서 채널별 단축 URL을 생성한다. 각 단축 URL은 UTM 파라미터가 붙은 앱 URL로 리다이렉트된다.

```
bit.ly/fc-a1  →  yourapp.streamlit.app/?utm_source=ev&utm_medium=community
```

앱에서 `st.query_params`로 UTM을 읽어 localStorage `fitcheck_utm_source`에 저장한다. 재방문 시 URL에 UTM이 없어도 localStorage에서 최초 유입 채널을 유지한다 (first-touch).

### bit.ly 링크 설계 (예시)

| 채널 | bit.ly 슬러그 | utm_source |
|------|-------------|-----------|
| 에브리타임 | `fc-a1` | `ev` |
| 링커리어 | `fc-b2` | `lk` |
| 지인 카톡 | `fc-c3` | `kt` |
| 링크드인 | `fc-d4` | `li` |

- bit.ly 슬러그는 채널명을 유추할 수 없음
- `utm_source` 값은 짧은 코드로 유지 (URL에 노출돼도 의미 불명확)
- 채널↔코드 매핑은 별도 개인 문서로 관리

### 구현
```python
# st.query_params로 UTM 읽기
utm_source_from_url = st.query_params.get("utm_source", "")

# localStorage에 저장 (없을 때만 덮어쓰기 — first-touch 유지)
utm_js = f"""
(function() {{
    const source = "{utm_source_from_url}";
    if (source && !localStorage.getItem('fitcheck_utm_source')) {{
        localStorage.setItem('fitcheck_utm_source', source);
    }}
    return localStorage.getItem('fitcheck_utm_source') || '';
}})()
"""
utm_source = st_javascript(utm_js)
```

---

## 4. 테스트 트래픽 분리 — is_internal 플래그

### 방식
URL 파라미터 `?_i=1`로 내부 모드를 활성화한다. 활성화되면 localStorage `fitcheck_internal=true`를 저장하고, 이후 모든 PostHog 이벤트에 `is_internal: true`를 자동 첨부한다.

```
yourapp.streamlit.app/?_i=1   →  내부 모드 ON (localStorage에 저장)
yourapp.streamlit.app/?_i=0   →  내부 모드 OFF (localStorage에서 제거)
yourapp.streamlit.app/        →  localStorage 기존 상태 유지
```

### PostHog 대시보드 사용법
- **실유저 분석:** `is_internal is not set` 또는 `is_internal = false` 필터 적용
- **QA 확인:** 필터 제거 후 내 데이터 포함해서 확인

### 구현
```python
i_flag = st.query_params.get("_i", "")

internal_js = f"""
(function() {{
    const flag = "{i_flag}";
    if (flag === '1') localStorage.setItem('fitcheck_internal', 'true');
    else if (flag === '0') localStorage.removeItem('fitcheck_internal');
    return localStorage.getItem('fitcheck_internal') === 'true';
}})()
"""
is_internal = st_javascript(internal_js)
```

---

## 5. PostHog 공통 프로퍼티 자동 첨부

`events.py`의 `capture()`가 모든 이벤트에 자동으로 공통 프로퍼티를 붙인다.

```python
# modules/events.py
_is_internal: bool = False
_utm_source: str = ""

def init(api_key: str, uid: str, is_internal: bool = False, utm_source: str = "") -> None:
    global _uid, _is_internal, _utm_source
    _uid = uid
    _is_internal = is_internal
    _utm_source = utm_source
    # ... Posthog 초기화

def capture(event: str, properties: dict | None = None) -> None:
    props = {
        "is_internal": _is_internal,
        "utm_source": _utm_source,
        **(properties or {}),
    }
    _client.capture(distinct_id=_uid, event=event, properties=props)
```

---

## 6. 앱 로드 순서 (app.py)

```
1. JS 실행: uid, utm_source, is_internal 읽기 (st_javascript)
2. uid가 유효한 문자열이면 → events.init(uid, is_internal, utm_source)
3. app_loaded 이벤트 capture (is_internal, utm_source 자동 첨부)
4. 이후 모든 이벤트는 기존과 동일하게 capture()
```

---

## 7. 변경 파일 요약

| 파일 | 변경 내용 |
|------|----------|
| `modules/events.py` | `init()`에 `uid`, `is_internal`, `utm_source` 파라미터 추가; `capture()`에 공통 프로퍼티 자동 첨부; `_session_id()` → `uid` 직접 사용으로 교체 |
| `app.py` | 앱 로드 시 `st_javascript` 3개 실행; uid 유효성 체크 후 PostHog 초기화; `?_i` 및 `utm_*` 쿼리 파라미터 처리 |

---

## 8. 범위 외

- fingerprinting (크로스 브라우저 추적): 구현 복잡도 대비 효과 미미, 제외
- 서버사이드 세션 저장: 로그인 없는 구조에서 불필요
- bit.ly 클릭 데이터 자동 연동: 수동 비교로 충분
