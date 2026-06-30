import io
import json
from pathlib import Path

import pdfplumber
import streamlit as st
import streamlit.components.v1 as components

import modules.events as events
from modules.analyzer import analyze_match, extract_text_from_image
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


def _save_text_resume() -> None:
    st.session_state.resume_text = st.session_state.get("_text_resume", "")


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


def render_step1() -> None:
    st.subheader("이력서를 입력해주세요")
    # Change 2: 개인정보 안내 문구
    st.info("🔒 입력하신 정보는 분석에만 사용되며, 서버에 저장되지 않습니다.")

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
                    # Change 5: 텍스트 탭 위젯 초기화 → 다음 렌더링 시 추출된 텍스트로 재초기화
                    st.session_state.pop("_text_resume", None)
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
            value=st.session_state.resume_text or _RESUME_TEMPLATE,
            height=400,
            placeholder=_RESUME_TEMPLATE,
            key="_text_resume",
            on_change=_save_text_resume,
        )
        st.caption("수정하면 자동으로 반영돼요.")
        _char_counter(st.session_state.get("_text_resume", ""))

    st.divider()
    _resume_ok = bool(st.session_state.resume_text.strip()) and len(st.session_state.resume_text) <= _MAX_CHARS
    if st.button("다음 →", type="primary", disabled=not _resume_ok):
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
                st.session_state["_jd_url_preview_text"] = result_text
                st.session_state.pop("_jd_url_edit", None)
                st.session_state.pop("_jd_tab_override", None)
            else:
                st.session_state["_jd_tab_override"] = "image"
                st.rerun()

        if st.session_state.get("_jd_url_preview_text"):
            st.caption(
                "불러온 내용을 확인하고 수정한 뒤 'JD 등록'을 눌러주세요. "
                "광고·네비게이션 등 불필요한 내용을 삭제하면 분석 정확도가 높아져요."
            )
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
                st.success("✅ 등록됐어요!")

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

    # ── 이미지 탭 ────────────────────────────────────────────
    with tab_img:
        uploaded_img = st.file_uploader(
            "공고 스크린샷 업로드",
            type=["png", "jpg", "jpeg", "webp"],
            key="_jd_img",
        )

        if _PASTE_ENABLED:
            st.caption("또는 이미지를 Ctrl+C로 복사한 뒤 아래 버튼 클릭")
            paste_result = _paste_image_button("📋 클립보드 이미지 붙여넣기 (이미지 복사 후 클릭)")
            if paste_result.image_data is not None:
                buf = io.BytesIO()
                paste_result.image_data.save(buf, format="PNG")
                new_bytes = buf.getvalue()
                # 새 이미지일 때만 OCR 텍스트 초기화 (rerun마다 재발화 방지)
                if new_bytes != st.session_state.get("_jd_pasted_img"):
                    st.session_state["_jd_pasted_img"] = new_bytes
                    st.session_state.pop("_jd_img_preview_text", None)
                    st.session_state.pop("_jd_img_edit", None)

        # 파일 업로드 우선, 없으면 붙여넣기 이미지 사용
        if uploaded_img:
            active_img_bytes = uploaded_img.getvalue()
            st.image(active_img_bytes, use_container_width=True)
        elif st.session_state.get("_jd_pasted_img"):
            active_img_bytes = st.session_state["_jd_pasted_img"]
            st.image(active_img_bytes, use_container_width=True)
        else:
            active_img_bytes = None

        if active_img_bytes is not None:
            if st.button("이미지에서 텍스트 추출", key="_extract_img"):
                with st.spinner("이미지를 읽는 중..."):
                    try:
                        text = extract_text_from_image(active_img_bytes)
                        if text.strip():
                            st.session_state["_jd_img_preview_text"] = text
                            st.session_state.pop("_jd_img_edit", None)
                            st.session_state.pop("_jd_tab_override", None)
                        else:
                            st.session_state.pop("_jd_img_preview_text", None)
                            st.session_state["_jd_tab_override"] = "text"
                            st.rerun()
                    except Exception:
                        st.session_state.pop("_jd_img_preview_text", None)
                        st.session_state["_jd_tab_override"] = "text"
                        st.rerun()

        if st.session_state.get("_jd_img_preview_text"):
            st.caption("추출된 내용을 확인하고 수정한 뒤 'JD 등록'을 눌러주세요.")
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
                st.success("✅ 등록됐어요!")

    # ── 등록 상태 ────────────────────────────────────────────
    if st.session_state.jd_text:
        st.caption(f"✅ 공고 등록됨 ({len(st.session_state.jd_text):,}자)")

    st.divider()
    col_prev, col_next = st.columns(2)
    with col_prev:
        if st.button("← 이전", use_container_width=True):
            st.session_state.step = 1
            st.rerun()
    with col_next:
        _jd_ok = bool(st.session_state.jd_text.strip()) and len(st.session_state.jd_text) <= _MAX_CHARS
        if st.button("🚀 분석 시작", type="primary", use_container_width=True, disabled=not _jd_ok):
            events.capture("jd_registered", {"method": _detect_jd_method()})
            events.capture("analysis_started")
            st.session_state.step = 3
            st.rerun()


def render_step3() -> None:
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

    events.capture("analysis_completed", {"score": result.get("score") or 0})
    st.session_state.analysis_result = result
    st.session_state.step = 4
    st.rerun()


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
    if score is None:
        st.info("ℹ️ 평가 가능한 기술 요건이 없어 점수를 산출할 수 없어요.")
    else:
        color = "🟢" if score >= 70 else ("🟡" if score >= 50 else "🔴")
        col_score, col_bar = st.columns([1, 3])
        with col_score:
            st.metric("매칭 스코어", f"{color} {score}점")
        with col_bar:
            st.progress(score / 100)

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
        if status in ("partial", "unmatched") and req.get("tip"):
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

    # ── 총평 ──────────────────────────────────────────────
    st.subheader("📝 총평")
    st.info(result.get("summary", ""))

    st.divider()

    # ── 피드백 ────────────────────────────────────────────
    if not st.session_state.feedback_submitted:
        st.markdown("##### 💬 이 분석이 도움이 됐나요?")
        col_yes, col_no = st.columns(2)
        with col_yes:
            if st.button("👍 도움됐어요", use_container_width=True):
                _submit_feedback(helpful=True, reason="", score=score)
        with col_no:
            if st.button("👎 아쉬웠어요", use_container_width=True):
                st.session_state["_show_reason"] = True

        if st.session_state.get("_show_reason"):
            reason = st.radio(
                "어떤 점이 아쉬웠나요?",
                ["결과가 부정확한 것 같아요", "내용이 너무 추상적이에요",
                 "이력서를 잘 못 읽은 것 같아요", "기타"],
                key="_feedback_reason",
            )
            other_text = ""
            if reason == "기타":
                other_text = st.text_area(
                    "어떤 점이 아쉬웠는지 알려주세요 (선택)",
                    placeholder="자유롭게 적어주세요",
                    key="_feedback_other",
                    height=100,
                )
            if st.button("제출", type="primary"):
                final_reason = f"기타: {other_text.strip()}" if reason == "기타" and other_text.strip() else reason
                _submit_feedback(helpful=False, reason=final_reason, score=score)
    else:
        st.success("피드백 감사해요! 🙏")

    st.divider()

    # ── 공유 / 재분석 ──────────────────────────────────────
    copy_text = (
        f"[JD 매칭 분석기]\n"
        f"{result.get('company', '')} · {result.get('position', '')}\n"
        f"매칭 스코어: {f'{score}점' if score is not None else '평가 불가'}\n\n"
        f"{result.get('summary', '')}"
    )
    col_copy, col_img, col_share = st.columns(3)

    with col_copy:
        # JS 클립보드 복사 (다운로드 없이 바로 복사)
        components.html(f"""
        <button id="copyBtn" onclick="
          navigator.clipboard.writeText({json.dumps(copy_text)}).then(() => {{
            document.getElementById('copyBtn').innerText = '✅ 복사됐어요!';
            setTimeout(() => document.getElementById('copyBtn').innerText = '📋 텍스트 복사', 2000);
          }}).catch(() => {{
            var ta = document.createElement('textarea');
            ta.value = {json.dumps(copy_text)};
            document.body.appendChild(ta); ta.select();
            document.execCommand('copy'); document.body.removeChild(ta);
            document.getElementById('copyBtn').innerText = '✅ 복사됐어요!';
            setTimeout(() => document.getElementById('copyBtn').innerText = '📋 텍스트 복사', 2000);
          }});" style="background:white;color:#1E293B;border:1px solid #D1D5DB;
          padding:8px 0;border-radius:6px;font-size:14px;cursor:pointer;width:100%;">
          📋 텍스트 복사</button>
        """, height=45)

    with col_img:
        try:
            img_bytes = generate_result_image(result)
            st.download_button(
                "🖼️ 이미지 저장",
                data=img_bytes,
                file_name="jd_match_result.png",
                mime="image/png",
                use_container_width=True,
            )
        except Exception:
            st.caption("이미지 생성에 실패했어요.")

    with col_share:
        # Web Share API (모바일 네이티브 공유) → 미지원 시 링크 복사
        components.html("""
        <button onclick="
          if (navigator.share) {
            navigator.share({title:'JD 매칭 분석기',
              text:'이력서 × JD 매칭을 AI로 분석해보세요!',
              url:window.location.href});
          } else {
            navigator.clipboard.writeText(window.location.href).then(() => {
              this.innerText = '✅ 링크 복사됨!';
              setTimeout(() => this.innerText = '🔗 공유하기', 2000);
            });
          }" style="background:#10B981;color:white;border:none;
          padding:8px 0;border-radius:6px;font-size:14px;cursor:pointer;width:100%;">
          🔗 공유하기</button>
        """, height=45)

    st.divider()
    if st.button("🔄 다시 분석하기", use_container_width=True):
        _reset()


def _submit_feedback(helpful: bool, reason: str, score: int | None) -> None:
    if _FEEDBACK_ENABLED:
        try:
            _save_feedback(helpful=helpful, reason=reason, score=score)
        except Exception:
            pass
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


# ── 라우팅 ────────────────────────────────────────────────────
# Change 4: min(..., 3) 제거 → step=4일 때 ③도 ✅로 표시
render_step_indicator(st.session_state.step)

step = st.session_state.step
if step == 1:
    render_step1()
elif step == 2:
    render_step2()
elif step == 3:
    render_step3()
else:
    render_step4()
