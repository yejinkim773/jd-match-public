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
