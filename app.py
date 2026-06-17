import io
from pathlib import Path

import pdfplumber
import streamlit as st

from datetime import date, datetime

from modules.analyzer import analyze_match, extract_text_from_image
from modules.crawler import fetch_images_from_url, fetch_jd_from_url
# sheets_api: Task 4에서 app.py 전면 재작성 시 연결 예정

st.set_page_config(page_title="JD 매칭 분석기", page_icon="🎯", layout="wide")
st.title("🎯 이력서 × JD 매칭 분석기")


def load_default_resume() -> str:
    path = Path(__file__).parent / "resume.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


for key, val in {
    "resume_text": load_default_resume(),
    "resume_version": 0,
    "jd_text": "",
    "jd_url": "",
    "url_fetch_failed": False,
    "analysis_result": None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = val


tab1, tab2, tab3, tab4 = st.tabs(["📄 내 이력서", "🔍 JD 분석", "📋 내 공고 목록", "⚙️ 설정"])


# ── Tab 1: 내 이력서 ─────────────────────────────────────────
with tab1:
    st.subheader("내 이력서")
    st.caption("아래는 예시 이력서예요. PDF를 업로드하거나 직접 수정한 뒤 저장 버튼을 눌러주세요.")

    uploaded_pdf = st.file_uploader(
        "PDF 이력서 업로드 (선택)",
        type=["pdf"],
        help="업로드하면 텍스트를 자동으로 추출해 아래 편집창에 채워드려요",
    )

    if uploaded_pdf is not None:
        file_id = f"{uploaded_pdf.name}_{uploaded_pdf.size}"
        if st.session_state.get("last_pdf_id") != file_id:
            with pdfplumber.open(io.BytesIO(uploaded_pdf.read())) as pdf:
                extracted = "\n".join(
                    page.extract_text() or "" for page in pdf.pages
                ).strip()
            if extracted:
                st.session_state.resume_text = extracted
                st.session_state.last_pdf_id = file_id
                st.session_state.resume_version += 1
                st.success("✅ PDF 텍스트 추출 완료! 아래에서 확인 후 저장하세요.")
                st.rerun()
            else:
                st.warning("⚠️ 이 PDF에서는 텍스트를 읽지 못했어요. 아래에 직접 붙여넣어 주세요.")

    edited = st.text_area(
        "이력서 내용 (수정 후 저장 버튼을 눌러주세요)",
        value=st.session_state.resume_text,
        height=450,
        key=f"resume_editor_{st.session_state.resume_version}",
    )

    if st.button("💾 저장", type="primary"):
        st.session_state.resume_text = edited
        st.success("저장 완료! JD 분석 탭에서 이 이력서로 분석해요.")


# ── Tab 2: JD 분석 ──────────────────────────────────────────
with tab2:
    st.subheader("JD 분석")

    if not st.session_state.resume_text.strip():
        st.warning("⚠️ 먼저 '내 이력서' 탭에서 이력서를 저장해주세요.")
    else:
        input_method = st.radio(
            "JD 입력 방식을 선택하세요",
            ["🔗 URL 입력", "📝 텍스트 직접 입력", "🖼️ 이미지 업로드"],
            horizontal=True,
        )

        # ── URL 입력
        if input_method == "🔗 URL 입력":
            url_input = st.text_input("채용공고 URL을 붙여넣으세요")

            if st.button("JD 불러오기", disabled=not url_input):
                with st.spinner("채용공고를 불러오는 중..."):
                    success, result_text = fetch_jd_from_url(url_input)
                if success:
                    st.session_state.jd_text = result_text
                    st.session_state.jd_url = url_input
                    st.session_state.url_fetch_failed = False
                    st.success("✅ 크롤링 성공!")
                elif "이미지형 JD" in result_text:
                    # 사이트가 이미지형임을 알고 있는 경우 → 이미지 재시도 없이 바로 안내
                    st.warning("📸 이미지형 공고라 URL에서 자동으로 읽어올 수 없어요.")
                    st.info("공고 페이지를 **스크린샷** 찍은 뒤, 위에서 **'이미지 업로드'** 방식을 선택해 업로드해보세요.")
                else:
                    st.info(f"텍스트 추출 실패 ({result_text}). 페이지 이미지에서 JD를 읽어볼게요...")
                    with st.spinner("이미지 분석 중... (30초 이상 걸릴 수 있어요)"):
                        images = fetch_images_from_url(url_input)
                        extracted = []
                        for img_bytes in images:
                            try:
                                text = extract_text_from_image(img_bytes)
                                if text.strip():
                                    extracted.append(text)
                            except Exception:
                                continue
                    if extracted:
                        st.session_state.jd_text = "\n\n".join(extracted)
                        st.session_state.jd_url = url_input
                        st.session_state.url_fetch_failed = False
                        st.success(f"✅ 이미지 {len(extracted)}개에서 텍스트 추출 완료!")
                    else:
                        st.session_state.url_fetch_failed = True
                        st.warning(f"자동 추출 실패: {result_text}")

            if st.session_state.url_fetch_failed:
                st.info("아래에 JD 텍스트를 직접 붙여넣어 주세요.")
                fallback = st.text_area("JD 텍스트 직접 입력", height=200, key="url_fallback")
                if st.button("직접 입력으로 등록"):
                    if fallback.strip():
                        st.session_state.jd_text = fallback
                        st.session_state.url_fetch_failed = False
                        st.success("✅ 등록됐어요!")
                        st.rerun()

        # ── 텍스트 직접 입력
        elif input_method == "📝 텍스트 직접 입력":
            manual = st.text_area("채용공고 텍스트를 붙여넣으세요", height=300, key="manual_jd")
            if st.button("JD 등록"):
                if manual.strip():
                    st.session_state.jd_text = manual
                    st.session_state.jd_url = ""
                    st.success("✅ 등록됐어요!")
                else:
                    st.warning("텍스트를 입력해주세요.")

        # ── 이미지 업로드
        else:
            uploaded_img = st.file_uploader(
                "채용공고 이미지 업로드",
                type=["png", "jpg", "jpeg", "webp"],
                key="jd_image",
            )
            if uploaded_img:
                st.image(uploaded_img, use_container_width=True)
                if st.button("이미지에서 텍스트 추출"):
                    with st.spinner("이미지를 읽는 중..."):
                        text_from_img = extract_text_from_image(uploaded_img.read())
                    st.session_state.jd_text = text_from_img
                    st.session_state.jd_url = ""
                    st.success("✅ 텍스트 추출 완료!")

        # ── 등록된 JD 미리보기
        if st.session_state.jd_text:
            with st.expander("📄 현재 등록된 JD 확인"):
                st.text(st.session_state.jd_text)

            st.divider()
            if st.button("🚀 분석 시작", type="primary", use_container_width=True):
                with st.spinner("분석 중이에요... (10~20초 소요)"):
                    try:
                        st.session_state.analysis_result = analyze_match(
                            st.session_state.resume_text,
                            st.session_state.jd_text,
                        )
                    except Exception as e:
                        st.error(f"분석 중 오류가 발생했어요: {e}")

        # ── 분석 결과
        if st.session_state.analysis_result:
            result = st.session_state.analysis_result
            score = result.get("score", 0)
            deadline = result.get("deadline")

            st.divider()
            st.subheader("📊 분석 결과")

            col_score, col_info = st.columns([1, 2])
            with col_score:
                color = "🟢" if score >= 70 else ("🟡" if score >= 50 else "🔴")
                st.metric("매칭 스코어", f"{color} {score}점")
                st.progress(score / 100)
            with col_info:
                st.write(f"🏢 **회사:** {result.get('company', '미확인')}")
                st.write(f"💼 **포지션:** {result.get('position', '미확인')}")
                st.write(f"⏰ **마감일:** {deadline or '미확인'}")

            st.subheader("📋 필수요건")
            for req in result.get("required_matches", []):
                status = req.get("status", "unmatched")
                icon = "✅" if status == "matched" else ("🔍" if status == "partial" else "❌")
                st.write(f"{icon} **{req.get('requirement', '')}**")
                if req.get("evidence"):
                    st.caption(f"└ {req.get('evidence')}")
                if status == "partial" and req.get("tip"):
                    st.info(f"💡 {req.get('tip')}")

            if result.get("preferred_matches"):
                st.subheader("⭐ 강점")
                for pref in result.get("preferred_matches", []):
                    st.write(f"⭐ **{pref.get('requirement', '')}**")
                    st.caption(f"└ {pref.get('evidence', '')}")

            st.subheader("📝 총평")
            st.info(result.get("summary", ""))

            st.divider()
            col_save, col_cal = st.columns(2)
            with col_save:
                if st.button("📊 Google Sheets에 저장", type="primary", use_container_width=True):
                    try:
                        save_result(result, st.session_state.get("jd_url", ""))
                        st.session_state.jobs_cache = None  # Tab 3 캐시 무효화
                        st.success("✅ Google Sheets에 저장됐어요!")
                    except Exception as e:
                        import traceback
                        st.error(f"저장 실패: {type(e).__name__}: {e}")
                        with st.expander("오류 상세"):
                            st.code(traceback.format_exc())
            with col_cal:
                if deadline:
                    deadline_fmt = deadline.replace("-", "")
                    title = f"{result.get('company', '')} {result.get('position', '')} 지원마감".strip()
                    cal_url = (
                        "https://calendar.google.com/calendar/r/eventedit"
                        f"?text={title.replace(' ', '+')}"
                        f"&dates={deadline_fmt}/{deadline_fmt}"
                        f"&details=매칭+스코어:+{score}점"
                    )
                    st.link_button("📅 구글 캘린더에 마감일 추가", cal_url, use_container_width=True)
                else:
                    st.button("📅 마감일 미확인", disabled=True, use_container_width=True)


# ── Tab 3: 내 공고 목록 ──────────────────────────────────────
with tab3:
    st.subheader("내 공고 목록")

    alert_score = st.session_state.get("alert_score", 70)
    alert_days = st.session_state.get("alert_days", 7)

    # jobs를 session_state에 캐시 — 체크박스 변경 시 재호출 방지
    if "jobs_cache" not in st.session_state:
        st.session_state.jobs_cache = None

    col_refresh, _ = st.columns([1, 5])
    with col_refresh:
        if st.button("🔄 새로고침", use_container_width=True):
            st.session_state.jobs_cache = None

    if st.session_state.jobs_cache is None:
        try:
            st.session_state.jobs_cache = fetch_jobs()
        except Exception as e:
            st.error(f"Google Sheets 연동 오류: {e}")
            st.session_state.jobs_cache = []

    jobs = st.session_state.jobs_cache

    if jobs:


        today = date.today()

        # 마감 임박 알림 배너
        urgent = [
            j for j in jobs
            if j["deadline"] and not j["applied"] and j["score"] >= alert_score
            and 0 <= (datetime.strptime(j["deadline"], "%Y-%m-%d").date() - today).days <= alert_days
        ]
        for j in urgent:
            days_left = (datetime.strptime(j["deadline"], "%Y-%m-%d").date() - today).days
            label = "오늘 마감" if days_left == 0 else f"D-{days_left}"
            st.warning(
                f"⏰ **{j['company']}** {j['position']} — {label} 마감! (매칭 {j['score']}점)"
            )

        st.divider()

        # 공고 목록 테이블
        for j in jobs:
            with st.container(border=True):
                col_info, col_score, col_status = st.columns([3, 1, 1])
                with col_info:
                    st.markdown(f"**{j['company']}** · {j['position']}")
                    if j["deadline"]:
                        days_left = (datetime.strptime(j["deadline"], "%Y-%m-%d").date() - today).days
                        if days_left < 0:
                            st.caption(f"마감 {abs(days_left)}일 지남")
                        elif days_left == 0:
                            st.caption("🔴 오늘 마감")
                        else:
                            st.caption(f"마감 D-{days_left} ({j['deadline']})")
                    else:
                        st.caption("마감일 미확인")
                with col_score:
                    color = "🟢" if j["score"] >= 70 else ("🟡" if j["score"] >= 50 else "🔴")
                    st.metric("스코어", f"{color} {j['score']}")
                with col_status:
                    def _on_toggle(row=j["row"]):
                        new_val = st.session_state[f"applied_{row}"]
                        update_applied(row, new_val)
                        for cached in st.session_state.jobs_cache:
                            if cached["row"] == row:
                                cached["applied"] = new_val
                                break
                    st.checkbox(
                        "지원완료",
                        value=j["applied"],
                        key=f"applied_{j['row']}",
                        on_change=_on_toggle,
                    )
                    if j["url"]:
                        st.link_button("공고 보기", j["url"])
                    # 삭제 버튼 — 실수 방지용 2단계
                    if st.session_state.get(f"confirm_delete_{j['row']}"):
                        st.caption("정말 삭제할까요?")
                        col_yes, col_no = st.columns(2)
                        with col_yes:
                            if st.button("삭제", key=f"del_yes_{j['row']}", type="primary"):
                                delete_job(j["row"])
                                st.session_state.jobs_cache = [
                                    c for c in st.session_state.jobs_cache
                                    if c["row"] != j["row"]
                                ]
                                st.session_state.pop(f"confirm_delete_{j['row']}", None)
                                st.rerun()
                        with col_no:
                            if st.button("취소", key=f"del_no_{j['row']}"):
                                st.session_state.pop(f"confirm_delete_{j['row']}", None)
                                st.rerun()
                    else:
                        if st.button("🗑️", key=f"del_{j['row']}", help="공고 삭제"):
                            st.session_state[f"confirm_delete_{j['row']}"] = True
                            st.rerun()
    else:
        st.info("아직 저장된 공고가 없어요. JD 분석 후 Google Sheets에 저장해보세요!")


# ── Tab 4: 설정 ─────────────────────────────────────────────
with tab4:
    st.subheader("설정")

    st.markdown("#### 마감 임박 알림 기준")
    alert_score_val = st.slider(
        "알림 기준 매칭 스코어 (이 점수 이상인 공고만 알림)",
        min_value=0, max_value=100,
        value=st.session_state.get("alert_score", 70),
        step=5,
    )
    alert_days_val = st.slider(
        "알림 기준 D-day (마감 며칠 전부터 알림)",
        min_value=1, max_value=30,
        value=st.session_state.get("alert_days", 7),
        step=1,
    )
    if st.button("💾 설정 저장", type="primary"):
        st.session_state.alert_score = alert_score_val
        st.session_state.alert_days = alert_days_val
        st.success(f"저장 완료! 스코어 {alert_score_val}점 이상 · D-{alert_days_val} 이내 공고 알림")
