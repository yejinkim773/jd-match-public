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


def _detect_jd_method() -> str:
    if st.session_state.jd_url:
        return "url"
    if st.session_state.get("_jd_img"):
        return "image"
    return "text"


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
