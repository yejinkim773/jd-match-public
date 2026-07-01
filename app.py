import io
from pathlib import Path

import pdfplumber
import streamlit as st
import streamlit.components.v1 as components

import modules.events as events
from modules.analyzer import analyze_match, extract_text_from_image, extract_texts_from_images
from modules.crawler import fetch_jd_from_url
from modules.result_image import generate_result_image

try:
    from modules.sheets_api import save_feedback as _save_feedback
    _FEEDBACK_ENABLED = True
except Exception:
    _FEEDBACK_ENABLED = False

try:
    from streamlit_paste_button import paste_image_button as _paste_image_button
    _PASTE_ENABLED = True
except ImportError:
    _PASTE_ENABLED = False

try:
    from streamlit_javascript import st_javascript
    _JS_ENABLED = True
except ImportError:
    _JS_ENABLED = False


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


# ── 스텝 인디케이터 ───────────────────────────────────────────
def render_step_indicator(current: int) -> None:
    # Change 1: 모든 스텝을 클릭 가능한 버튼으로 변경
    # Change 4: current를 min(...,3) 없이 그대로 받아 step=4시 ③도 ✅로 표시
    labels = ["① 이력서", "② JD 입력", "③ 결과"]
    targets = [1, 2, 4]
    cols = st.columns(3)
    for i, (col, label, target) in enumerate(zip(cols, labels, targets), start=1):
        with col:
            if i < current:
                if st.button(f"✅ {label}", key=f"_nav_{i}", use_container_width=True):
                    st.session_state.step = target
                    st.rerun()
            elif i == current:
                st.markdown(
                    f"<p style='text-align:center;font-weight:700;padding:6px 0'>{label}</p>",
                    unsafe_allow_html=True,
                )
            else:
                if st.button(label, key=f"_nav_{i}", use_container_width=True):
                    st.session_state.step = target
                    st.rerun()
    st.divider()


_MAX_CHARS = 10_000
_MAX_DAILY_ANALYSES = 5

_GRADE_COLORS = {
    "적합도 높음":      "#10B981",
    "대체로 적합":      "#34D399",
    "보완 후 지원 권장": "#F59E0B",
    "추가 준비 필요":   "#F97316",
}

_NEGATIVE_OPTIONS = [
    "필수요건 판정이 맞지 않아요",
    "등급/적합도가 납득이 안 돼요",
    "분석 항목이 빠지거나 너무 많아요",
    "근거가 부정확해요",
    "보완 방향 팁이 도움이 안 됐어요",
    "분석 자체가 진행되지 않았어요",
    "기타",
]

_ERROR_OPTIONS = [
    "파일이 업로드되지 않아요",
    "채용공고 URL 크롤링이 안 돼요",
    "이미지 인식이 안 돼요",
    "페이지가 멈춰요",
    "기타",
]

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


# Change 5: on_change로 text_area 편집 시 즉시 resume_text에 반영
def _save_pdf_preview() -> None:
    st.session_state.resume_text = st.session_state.get("_pdf_preview", "")
    st.session_state["_resume_method"] = "pdf"


def _save_text_resume() -> None:
    text = st.session_state.get("_text_resume", "")
    # 예시 템플릿 그대로인 경우 빈값으로 처리 (템플릿이 실제 이력서로 오인되지 않도록)
    if text.strip() == _RESUME_TEMPLATE.strip():
        text = ""
    st.session_state.resume_text = text
    if text:
        st.session_state["_resume_method"] = "text"


def _char_counter(text: str) -> bool:
    n = len(text)
    if n > _MAX_CHARS:
        st.warning(
            f"{n:,} / {_MAX_CHARS:,}자 — 입력하신 내용이 조금 길어요. "
            "핵심적인 경력/공고 내용만 남겨주시면 더 정확하게 분석해드릴 수 있어요!"
        )
        return False
    st.caption(f"{n:,} / {_MAX_CHARS:,}자")
    return True


def render_error_report(page: str) -> None:
    key_open = f"_err_open_{page}"
    key_done = f"_err_done_{page}"

    if st.session_state.get(key_done):
        st.caption("✅ 신고가 접수됐어요. 감사해요!")
        return

    if not st.session_state.get(key_open):
        if st.button("오류 신고", key=f"_err_btn_{page}"):
            st.session_state[key_open] = True
            st.rerun()
        return

    st.markdown("**어떤 오류가 발생했나요?** (복수 선택 가능)")
    selected = [opt for i, opt in enumerate(_ERROR_OPTIONS)
                if st.checkbox(opt, key=f"_err_{page}_{i}")]

    crawl_site = ""
    if "채용공고 URL 크롤링이 안 돼요" in selected:
        crawl_site = st.text_input(
            "어떤 채용 사이트인가요? (선택)",
            placeholder="예: 원티드, 사람인, 잡코리아, 링크드인 등",
            key=f"_err_crawl_site_{page}",
        )

    other_text = ""
    if "기타" in selected:
        other_text = st.text_area(
            "기타 내용",
            placeholder="자유롭게 적어주세요",
            key=f"_err_other_{page}",
            height=80,
        )

    col1, col2 = st.columns(2)
    with col1:
        if st.button("신고 제출", key=f"_err_submit_{page}", type="primary", disabled=not selected):
            props: dict = {"page": page}
            props.update({opt: True for opt in selected})
            if crawl_site:
                props["crawl_site"] = crawl_site
            if other_text:
                props["other"] = other_text
            events.capture("error_report", props)
            st.session_state[key_open] = False
            st.session_state[key_done] = True
            st.rerun()
    with col2:
        if st.button("취소", key=f"_err_cancel_{page}"):
            st.session_state[key_open] = False
            st.rerun()


def render_step1() -> None:
    print(f"[DEBUG] render_step1 called, _step1_entered={st.session_state.get('_step1_entered')}")
    if not st.session_state.get("_step1_entered"):
        print("[DEBUG] Firing resume_upload_started")
        events.capture("resume_upload_started")
        st.session_state["_step1_entered"] = True
        print(f"[DEBUG] After capture, _step1_entered={st.session_state.get('_step1_entered')}")

    # tab_img_r은 tab_text보다 나중에 렌더링되어 _text_resume를 직접 set 불가.
    # 이전 렌더에서 예약된 값이 있으면 위젯 렌더 전에 미리 적용.
    if "_resume_text_pending" in st.session_state:
        st.session_state["_text_resume"] = st.session_state.pop("_resume_text_pending")

    st.subheader("이력서를 입력해주세요")
    st.info("🔒 입력하신 내용은 분석 목적으로만 사용되며, 수집 및 저장되지 않습니다.")
    st.caption("💡 이름, 전화번호, 주소 등 민감한 개인정보는 텍스트 탭에서 삭제하거나 수정한 뒤 등록하시는 걸 권장드려요.")

    tab_img_r, tab_pdf, tab_text = st.tabs(["🖼️ 이미지", "📄 PDF 업로드", "✏️ 직접 입력"])

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
                    st.session_state["_text_resume"] = extracted
                    st.success("✅ 텍스트 추출 완료! 아래에서 내용을 확인하고 수정할 수 있어요.")
                else:
                    st.warning("⚠️ 이 PDF에서 텍스트를 읽지 못했어요. '직접 입력' 탭을 이용해주세요.")
            if st.session_state.resume_text:
                st.text_area(
                    "추출된 이력서",
                    value=st.session_state.resume_text,
                    height=300,
                    key="_pdf_preview",
                    on_change=_save_pdf_preview,
                )
                st.caption("수정하면 자동으로 반영돼요.")
                _char_counter(st.session_state.get("_pdf_preview", st.session_state.resume_text))

    with tab_text:
        st.text_area(
            "이력서 내용 입력",
            value=st.session_state.resume_text or "",
            height=400,
            placeholder=_RESUME_TEMPLATE,
            key="_text_resume",
            on_change=_save_text_resume,
        )
        st.caption("수정하면 자동으로 반영돼요.")
        _char_counter(st.session_state.get("_text_resume", ""))

    with tab_img_r:
        uploaded_resume_imgs = st.file_uploader(
            "이력서 이미지 업로드 (여러 장 가능)",
            type=["png", "jpg", "jpeg", "webp"],
            key="_resume_imgs",
            help="이력서 사진이나 스캔본을 올려주세요",
            accept_multiple_files=True,
        )
        # 업로드 파일이 바뀌면 OCR 결과 초기화 (파일 유실로 인한 "" 변경은 무시)
        r_fp = "|".join(f"{f.name}:{f.size}" for f in uploaded_resume_imgs) if uploaded_resume_imgs else ""
        if r_fp and r_fp != st.session_state.get("_resume_img_fp", ""):
            st.session_state["_resume_img_fp"] = r_fp
            st.session_state.pop("_resume_img_preview_text", None)
            st.session_state.pop("_resume_img_edit", None)

        if uploaded_resume_imgs:
            if len(uploaded_resume_imgs) == 1:
                st.image(uploaded_resume_imgs[0].getvalue(), use_container_width=True)
            else:
                img_cols = st.columns(min(len(uploaded_resume_imgs), 3))
                for i, f in enumerate(uploaded_resume_imgs):
                    with img_cols[i % 3]:
                        st.image(f.getvalue(), caption=f"{i + 1}번", use_container_width=True)

            btn_label = f"이미지 {len(uploaded_resume_imgs)}장에서 텍스트 추출" if len(uploaded_resume_imgs) > 1 else "이미지에서 텍스트 추출"
            if st.button(btn_label, key="_extract_resume_img"):
                with st.spinner("이미지를 읽는 중..."):
                    try:
                        combined = extract_texts_from_images([f.getvalue() for f in uploaded_resume_imgs])
                        if combined.strip():
                            st.session_state["_resume_img_preview_text"] = combined
                            st.session_state.pop("_resume_img_edit", None)
                        else:
                            st.warning("이미지에서 텍스트를 읽지 못했어요. PDF 업로드나 직접 입력을 이용해주세요.")
                    except Exception:
                        st.warning("이미지 읽기 중 오류가 발생했어요. PDF 업로드나 직접 입력을 이용해주세요.")

        if st.session_state.get("_resume_img_preview_text"):
            _cap_c, _rst_c = st.columns([4, 1])
            with _cap_c:
                st.caption("추출된 내용을 확인하고 수정한 뒤 '이력서 등록'을 눌러주세요.")
            with _rst_c:
                if st.button("↩ 되돌리기", key="_restore_resume_img", use_container_width=True):
                    st.session_state.pop("_resume_img_edit", None)
                    st.rerun()
            st.text_area(
                "추출된 이력서 내용 (수정 가능)",
                value=st.session_state["_resume_img_preview_text"],
                height=300,
                key="_resume_img_edit",
            )
            resume_img_edit = st.session_state.get("_resume_img_edit", st.session_state["_resume_img_preview_text"])
            resume_img_within = _char_counter(resume_img_edit)
            if st.button("이력서 등록", key="_register_resume_img",
                         disabled=not resume_img_within or not resume_img_edit.strip()):
                st.session_state.resume_text = resume_img_edit
                st.session_state["_resume_method"] = "image"
                # _last_pdf_id는 유지 (pop하면 다음 렌더에서 PDF 재추출 → resume_text 덮어씀)
                # _text_resume는 tab_text가 이미 렌더링돼 직접 set 불가 → pending으로 다음 렌더에 적용
                st.session_state["_resume_text_pending"] = resume_img_edit
                st.session_state.pop("_pdf_preview", None)
                # 등록 후 OCR 편집 영역 숨김 (되돌리기가 등록 철회처럼 보이는 문제 방지)
                st.session_state.pop("_resume_img_preview_text", None)
                st.session_state.pop("_resume_img_edit", None)
                st.rerun()

    st.divider()
    if st.session_state.resume_text:
        st.caption(f"✅ 이력서 등록됨 ({len(st.session_state.resume_text):,}자)")
        with st.expander("📄 등록된 이력서 확인 (선택)"):
            st.text(st.session_state.resume_text)
    st.caption(
        "📌 PDF 이력서는 레이아웃에 따라 텍스트가 일부 뒤섞일 수 있어요. "
        "더 정확한 분석을 원하시면 텍스트를 직접 붙여넣기 해주세요."
    )
    _resume_ok = bool(st.session_state.resume_text.strip()) and len(st.session_state.resume_text) <= _MAX_CHARS
    if st.button("다음 →", type="primary", disabled=not _resume_ok):
        events.capture("resume_uploaded",
                       {"input_method": st.session_state.get("_resume_method", "text")})
        st.session_state.step = 2
        st.rerun()

    render_error_report("resume")


def _detect_jd_method() -> str:
    if st.session_state.jd_url:
        return "url"
    if st.session_state.get("_jd_imgs") or st.session_state.get("_jd_pasted_img"):
        return "image"
    return "text"


def render_step2() -> None:
    if not st.session_state.get("_step2_entered"):
        events.capture("jd_input_started")
        st.session_state["_step2_entered"] = True

    st.subheader("채용공고를 입력해주세요")

    if st.session_state.get("_jd_tab_override") == "text":
        st.info("📝 이미지에서 텍스트를 읽지 못했어요. 공고 내용을 직접 붙여넣기 해주세요.")

    tab_img, tab_text, tab_url = st.tabs(["🖼️ 이미지", "📝 텍스트", "🔗 URL"])

    # ── URL 탭 ──────────────────────────────────────────────
    with tab_url:
        st.caption("💡 채용 사이트나 공고 형식에 따라 불러오기가 안 될 수 있어요. 이 경우 공고 화면을 캡처해 이미지로 올리거나, 내용을 직접 복사해 텍스트로 붙여넣기 해주세요.")
        url_input = st.text_input("채용공고 URL 붙여넣기", key="_jd_url_input")
        if st.button("공고 불러오기", disabled=not url_input, key="_fetch_url"):
            with st.spinner("공고를 불러오는 중..."):
                success, result_text = fetch_jd_from_url(url_input)
            if success:
                st.session_state["_jd_url_preview_text"] = result_text
                st.session_state.pop("_jd_url_edit", None)
                st.session_state.pop("_jd_tab_override", None)
                st.session_state.pop("_jd_url_fetch_failed", None)
            else:
                st.session_state["_jd_url_fetch_failed"] = True
                st.rerun()

        if st.session_state.get("_jd_url_fetch_failed"):
            st.warning(
                "해당 공고를 자동으로 불러오지 못했어요.  \n"
                "**이미지 탭**에서 공고 스크린샷을 업로드하거나, "
                "**텍스트 탭**에서 내용을 직접 붙여넣기 해주세요."
            )

        if st.session_state.get("_jd_url_preview_text"):
            _cap_c, _rst_c = st.columns([4, 1])
            with _cap_c:
                st.caption(
                    "불러온 내용을 확인하고 수정한 뒤 'JD 등록'을 눌러주세요. "
                    "광고·네비게이션 등 불필요한 내용을 삭제하면 분석 정확도가 높아져요."
                )
            with _rst_c:
                if st.button("↩ 되돌리기", key="_restore_jd_url", use_container_width=True):
                    st.session_state.pop("_jd_url_edit", None)
                    st.rerun()
            st.text_area(
                "불러온 공고 내용 (수정 가능)",
                value=st.session_state["_jd_url_preview_text"],
                height=300,
                key="_jd_url_edit",
            )
            url_edit_text = st.session_state.get("_jd_url_edit", st.session_state["_jd_url_preview_text"])
            url_within = _char_counter(url_edit_text)
            if st.button("JD 등록", key="_register_url",
                         disabled=not url_within or not url_edit_text.strip()):
                st.session_state.jd_text = url_edit_text
                st.session_state.jd_url = st.session_state.get("_jd_url_input", "")
                st.session_state.pop("_jd_url_preview_text", None)
                st.session_state.pop("_jd_url_edit", None)
                st.rerun()

    # ── 이미지 탭 ────────────────────────────────────────────
    with tab_img:
        uploaded_imgs = st.file_uploader(
            "공고 스크린샷 업로드 (여러 장 가능)",
            type=["png", "jpg", "jpeg", "webp"],
            key="_jd_imgs",
            accept_multiple_files=True,
        )
        # 업로드 파일이 바뀌면 OCR 결과 초기화 (파일 유실로 인한 "" 변경은 무시)
        new_imgs_fp = "|".join(f"{f.name}:{f.size}" for f in uploaded_imgs) if uploaded_imgs else ""
        if new_imgs_fp and new_imgs_fp != st.session_state.get("_jd_imgs_fp", ""):
            st.session_state["_jd_imgs_fp"] = new_imgs_fp
            st.session_state.pop("_jd_img_preview_text", None)
            st.session_state.pop("_jd_img_edit", None)

        if _PASTE_ENABLED:
            st.caption("또는 이미지를 Ctrl+C로 복사한 뒤 아래 버튼 클릭")
            paste_result = _paste_image_button("📋 클립보드 이미지 붙여넣기 (이미지 복사 후 클릭)")
            if paste_result.image_data is not None:
                buf = io.BytesIO()
                paste_result.image_data.save(buf, format="PNG")
                new_bytes = buf.getvalue()
                if new_bytes != st.session_state.get("_jd_pasted_img"):
                    st.session_state["_jd_pasted_img"] = new_bytes
                    st.session_state.pop("_jd_img_preview_text", None)
                    st.session_state.pop("_jd_img_edit", None)

        # 활성 이미지 목록: 파일 업로드 우선, 없으면 붙여넣기
        if uploaded_imgs:
            active_imgs_bytes = [f.getvalue() for f in uploaded_imgs]
        elif st.session_state.get("_jd_pasted_img"):
            active_imgs_bytes = [st.session_state["_jd_pasted_img"]]
        else:
            active_imgs_bytes = []

        if active_imgs_bytes:
            if len(active_imgs_bytes) == 1:
                st.image(active_imgs_bytes[0], use_container_width=True)
            else:
                img_cols = st.columns(min(len(active_imgs_bytes), 3))
                for i, b in enumerate(active_imgs_bytes):
                    with img_cols[i % 3]:
                        st.image(b, caption=f"{i + 1}번", use_container_width=True)

            btn_label = f"이미지 {len(active_imgs_bytes)}장에서 텍스트 추출" if len(active_imgs_bytes) > 1 else "이미지에서 텍스트 추출"
            if st.button(btn_label, key="_extract_imgs"):
                with st.spinner("이미지를 읽는 중..."):
                    try:
                        combined = extract_texts_from_images(active_imgs_bytes)
                    except Exception:
                        combined = ""
                    if combined.strip():
                        st.session_state["_jd_img_preview_text"] = combined
                        st.session_state.pop("_jd_img_edit", None)
                        st.session_state.pop("_jd_tab_override", None)
                    else:
                        st.session_state.pop("_jd_img_preview_text", None)
                        st.session_state["_jd_tab_override"] = "text"
                        st.rerun()

        if st.session_state.get("_jd_img_preview_text"):
            _cap_c, _rst_c = st.columns([4, 1])
            with _cap_c:
                st.caption("추출된 내용을 확인하고 수정한 뒤 'JD 등록'을 눌러주세요.")
            with _rst_c:
                if st.button("↩ 되돌리기", key="_restore_jd_img", use_container_width=True):
                    st.session_state.pop("_jd_img_edit", None)
                    st.rerun()
            st.text_area(
                "추출된 공고 내용 (수정 가능)",
                value=st.session_state["_jd_img_preview_text"],
                height=300,
                key="_jd_img_edit",
            )
            img_edit_text = st.session_state.get("_jd_img_edit", st.session_state["_jd_img_preview_text"])
            img_within = _char_counter(img_edit_text)
            if st.button("JD 등록", key="_register_img",
                         disabled=not img_within or not img_edit_text.strip()):
                st.session_state.jd_text = img_edit_text
                st.session_state.jd_url = ""
                st.session_state.pop("_jd_img_preview_text", None)
                st.session_state.pop("_jd_img_edit", None)
                st.rerun()

    # ── 텍스트 탭 ────────────────────────────────────────────
    with tab_text:
        manual = st.text_area("채용공고 내용 붙여넣기", height=300, key="_jd_manual")
        text_within = _char_counter(manual)
        if st.button("JD 등록", key="_register_text", disabled=not text_within):
            if manual.strip():
                st.session_state.jd_text = manual
                st.session_state.jd_url = ""
                st.session_state.pop("_jd_tab_override", None)
                st.success("✅ 등록됐어요!")
            else:
                st.warning("내용을 입력해주세요.")

    # ── 등록 상태 ────────────────────────────────────────────
    if st.session_state.jd_text:
        st.caption(f"✅ 공고 등록됨 ({len(st.session_state.jd_text):,}자)")
        with st.expander("📄 등록된 공고 확인 (선택)"):
            st.text(st.session_state.jd_text)

    if not st.session_state.resume_text.strip():
        st.warning("⚠️ 이력서가 아직 등록되지 않았어요. '① 이력서' 탭으로 돌아가 이력서를 등록해주세요.")

    st.divider()
    col_prev, col_next = st.columns(2)
    with col_prev:
        if st.button("← 이전", use_container_width=True):
            st.session_state.step = 1
            st.rerun()
    with col_next:
        _count_ok = st.session_state.get("_daily_count", 0) < _MAX_DAILY_ANALYSES
        _resume_registered = bool(st.session_state.resume_text.strip())
        _jd_ok = _resume_registered and bool(st.session_state.jd_text.strip()) and len(st.session_state.jd_text) <= _MAX_CHARS and _count_ok
        if st.button("🚀 분석 시작", type="primary", use_container_width=True, disabled=not _jd_ok):
            events.capture("jd_registered", {"method": _detect_jd_method()})
            events.capture("analysis_started")
            st.session_state.step = 3
            st.rerun()

    _remaining = max(0, _MAX_DAILY_ANALYSES - st.session_state.get("_daily_count", 0))
    if _remaining == 0:
        st.warning("오늘 사용 가능한 분석 횟수(5회)를 모두 사용했어요. 내일 다시 이용해 주세요! 😊")
    else:
        st.caption(f"오늘 남은 분석 횟수: {_remaining} / {_MAX_DAILY_ANALYSES}")

    render_error_report("jd")


def render_step3() -> None:
    if not st.session_state.resume_text.strip():
        st.error("이력서 내용이 없어요. 이력서를 입력하고 등록한 뒤 다시 시도해주세요.")
        if st.button("← 이력서 입력으로"):
            st.session_state.step = 1
            st.rerun()
        return
    if not st.session_state.jd_text.strip():
        st.error("채용공고 내용이 없어요. 채용공고를 입력하고 등록한 뒤 다시 시도해주세요.")
        if st.button("← 채용공고 입력으로"):
            st.session_state.step = 2
            st.rerun()
        return

    if st.session_state.get("_daily_count", 0) >= _MAX_DAILY_ANALYSES:
        st.warning(
            "오늘 사용 가능한 분석 횟수(5회)를 모두 사용하셨어요. "
            "내일 다시 이용해 주세요! 매일 자정에 횟수가 초기화돼요. 😊"
        )
        if st.button("← 돌아가기"):
            st.session_state.step = 2
            st.rerun()
        return

    _increment_daily_count()

    st.subheader("분석 중이에요...")
    st.caption("이력서와 채용공고를 비교하는 중이에요. 10~20초 소요돼요.")

    with st.spinner("🔍 매칭 결과를 분석하는 중..."):
        try:
            result = analyze_match(
                st.session_state.resume_text,
                st.session_state.jd_text,
            )
        except ValueError as e:
            if str(e) == "too_long":
                st.error("입력하신 내용이 조금 길어요. 핵심적인 경력/공고 내용만 남겨주시면 더 정확하게 분석해드릴 수 있어요!")
            else:
                st.error("분석 중 오류가 발생했어요. 잠시 후 다시 시도해주세요.")
            if st.button("← 돌아가기"):
                st.session_state.step = 2
                st.rerun()
            return
        except Exception:
            st.error("분석 중 오류가 발생했어요. 잠시 후 다시 시도해주세요.")
            if st.button("← 돌아가기"):
                st.session_state.step = 2
                st.rerun()
            return

    events.capture("analysis_completed", {"grade": result.get("grade", "추가 준비 필요")})
    st.session_state.analysis_result = result
    st.session_state.step = 4
    st.rerun()


def render_step4() -> None:
    if not st.session_state.get("_step4_entered"):
        events.capture("result_viewed")
        st.session_state["_step4_entered"] = True

    result = st.session_state.analysis_result
    if not result:
        st.error("분석 결과가 없어요.")
        if st.button("처음으로"):
            _reset()
        return

    grade = result.get("grade", "추가 준비 필요")

    # ── 헤더 ──────────────────────────────────────────────
    st.markdown(
        f"**{result.get('company', '미확인')}**  ·  {result.get('position', '미확인')}"
    )

    # ── 적합도 레이블 ─────────────────────────────────────
    _grade_color = _GRADE_COLORS.get(grade, "#6B7280")
    st.markdown(
        f'<p style="font-size:22px;font-weight:700;color:{_grade_color};margin:4px 0 12px">'
        f"{grade}</p>",
        unsafe_allow_html=True,
    )

    # ── 필수요건 ──────────────────────────────────────────
    st.subheader("📋 필수요건")

    all_reqs = result.get("required_matches", [])
    skill_reqs  = [r for r in all_reqs if isinstance(r, dict) and str(r.get("category", "skill_based")).strip().lower() == "skill_based"]
    trait_reqs  = [r for r in all_reqs if isinstance(r, dict) and str(r.get("category", "")).strip().lower() == "trait_based"]
    scope_reqs  = [r for r in all_reqs if isinstance(r, dict) and str(r.get("category", "")).strip().lower() == "out_of_scope"]

    for req in skill_reqs:
        status = str(req.get("status", "unmatched")).strip().lower()
        icon = "✅" if status == "matched" else ("🔍" if status == "partial" else "❌")
        st.write(f"{icon} **{req.get('requirement', '')}**")
        if req.get("evidence"):
            st.caption(f"└ {req.get('evidence')}")
        if req.get("tip"):
            st.info(f"💡 {req.get('tip')}")

    if trait_reqs:
        st.caption("**성향/가치관 요건** (점수 미반영)")
        for req in trait_reqs:
            st.write(f"💬 **{req.get('requirement', '')}**")

    if scope_reqs:
        st.caption("**별도 확인 필요** (점수 미반영)")
        for req in scope_reqs:
            st.write(f"📋 **{req.get('requirement', '')}**")
            if req.get("note"):
                st.caption(f"└ {req.get('note')}")

    # ── 강점 ──────────────────────────────────────────────
    if result.get("preferred_matches"):
        st.subheader("⭐ 강점")
        for pref in result.get("preferred_matches", []):
            st.write(f"⭐ **{pref.get('requirement', '')}**")
            st.caption(f"└ {pref.get('evidence', '')}")

    unmatched_prefs = result.get("preferred_unmatched", [])
    if unmatched_prefs:
        with st.expander(f"다른 우대사항 보기 ({len(unmatched_prefs)}개)"):
            for pref in unmatched_prefs:
                st.write(f"• {pref.get('requirement', '')}")

    # ── 총평 ──────────────────────────────────────────────
    st.subheader("📝 총평")
    summary = result.get("summary", {})
    if isinstance(summary, dict):
        strengths = summary.get("strengths") or []
        gaps = summary.get("gaps") or []
        comment = summary.get("comment", "")
        col_s, col_g = st.columns(2)
        with col_s:
            st.markdown("**✅ 어필 포인트**")
            if strengths:
                for s in strengths:
                    st.markdown(f"• {s}")
            else:
                st.caption("해당 없음")
        with col_g:
            st.markdown("**🔧 보완 포인트**")
            if gaps:
                for g in gaps:
                    st.markdown(f"• {g}")
            else:
                st.caption("해당 없음")
        if comment:
            st.info(comment)
    else:
        st.info(summary)

    st.divider()

    # ── 피드백 ────────────────────────────────────────────
    if not st.session_state.feedback_submitted:
        st.markdown("##### 💬 이 분석이 도움이 됐나요?")
        col_yes, col_no = st.columns(2)
        with col_yes:
            if st.button("👍 도움됐어요", use_container_width=True):
                _submit_feedback(helpful=True, grade=grade)
        with col_no:
            if st.button("👎 아쉬웠어요", use_container_width=True):
                st.session_state["_show_reason"] = True

        if st.session_state.get("_show_reason"):
            st.markdown("**어떤 점이 아쉬웠나요?** (복수 선택 가능)")
            selected = [opt for i, opt in enumerate(_NEGATIVE_OPTIONS)
                        if st.checkbox(opt, key=f"_fb_{i}")]
            other_text = ""
            if "기타" in selected:
                other_text = st.text_area(
                    "기타 내용",
                    placeholder="자유롭게 적어주세요",
                    key="_feedback_other",
                    height=80,
                )
            if st.button("제출", type="primary", disabled=not selected):
                _submit_feedback(helpful=False, grade=grade, reasons=selected, other=other_text)
    else:
        st.success("피드백 감사해요! 🙏")

    st.divider()

    # ── 공유 / 재분석 ──────────────────────────────────────
    components.html("""
    <button onclick="
      var url = window.parent.location.href;
      navigator.clipboard.writeText(url).then(() => {
        this.textContent = '✅ 링크가 복사되었어요!';
        setTimeout(() => this.textContent = '🔗 공유하기', 2500);
      }).catch(() => {
        var ta = document.createElement('textarea');
        ta.value = url;
        document.body.appendChild(ta); ta.select();
        document.execCommand('copy'); document.body.removeChild(ta);
        this.textContent = '✅ 링크가 복사되었어요!';
        setTimeout(() => this.textContent = '🔗 공유하기', 2500);
      });" style="background:#10B981;color:white;border:none;
      padding:8px 0;border-radius:6px;font-size:14px;cursor:pointer;width:100%;">
      🔗 공유하기</button>
    """, height=45)

    st.divider()
    st.markdown(
        "💬 FitCheck 개선에 의견을 남겨주세요 &nbsp;→&nbsp; "
        "[**설문 참여하기**](https://forms.gle/y8x8xDCvqT5j61ae6)",
        unsafe_allow_html=True,
    )

    st.divider()
    if st.button("🔄 다시 분석하기", use_container_width=True):
        _reset()


def _submit_feedback(helpful: bool, grade: str, reasons: list | None = None, other: str = "") -> None:
    reason_str = ""
    if reasons:
        reason_str = ", ".join(reasons)
        if other:
            reason_str += f" | 기타: {other}"
    if _FEEDBACK_ENABLED:
        try:
            _save_feedback(helpful=helpful, reason=reason_str, grade=grade)
        except Exception:
            pass
    events.capture("feedback_submitted", {"helpful": "yes" if helpful else "no", "grade": grade})
    if not helpful and reasons:
        neg_props: dict = {"grade": grade}
        neg_props.update({r: True for r in reasons})
        if other:
            neg_props["other"] = other
        events.capture("feedback_negative", neg_props)
    st.session_state.feedback_submitted = True
    st.session_state.pop("_show_reason", None)
    st.rerun()


def _sync_daily_count() -> None:
    """localStorage에서 오늘 분석 횟수를 읽어 세션에 반영."""
    if not _JS_ENABLED:
        return
    result = st_javascript("""
    (() => {
        try {
            const today = new Date().toISOString().split('T')[0];
            const raw = localStorage.getItem('jd_daily_count');
            if (!raw) return 0;
            const data = JSON.parse(raw);
            return data.date === today ? (data.count || 0) : 0;
        } catch(e) { return 0; }
    })()
    """)
    if isinstance(result, (int, float)):
        js_val = int(result)
        if js_val > st.session_state.get("_daily_count", 0):
            st.session_state["_daily_count"] = js_val


def _increment_daily_count() -> None:
    """분석 횟수를 1 증가시키고 localStorage에 저장."""
    new_count = st.session_state.get("_daily_count", 0) + 1
    st.session_state["_daily_count"] = new_count
    if _JS_ENABLED:
        st_javascript(f"""
        (() => {{
            try {{
                const today = new Date().toISOString().split('T')[0];
                localStorage.setItem('jd_daily_count', JSON.stringify({{date: today, count: {new_count}}}));
            }} catch(e) {{}}
        }})()
        """)


def _reset() -> None:
    for k in list(st.session_state.keys()):
        if k not in ("session_id", "app_loaded_captured", "_daily_count"):
            del st.session_state[k]
    st.session_state.step = 1
    st.rerun()


# ── 헤더 ──────────────────────────────────────────────────────
st.markdown(
    """
    <div style="text-align:center; padding:32px 0 20px 0;">
      <div style="font-size:2.4rem; font-weight:800; letter-spacing:-1px; color:#1E293B;">
        Fit<span style="color:#10B981;">✓</span>Check
      </div>
      <div style="margin-top:8px; font-size:1.05rem; color:#64748B;">
        내 이력서, 이 공고에 맞나요?
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ── 라우팅 ────────────────────────────────────────────────────
_sync_daily_count()
render_step_indicator(st.session_state.step)

step = st.session_state.step
print(f"[DEBUG] routing: step={step}, keys={list(st.session_state.keys())[:10]}")
if step == 1:
    render_step1()
elif step == 2:
    render_step2()
elif step == 3:
    render_step3()
else:
    render_step4()
