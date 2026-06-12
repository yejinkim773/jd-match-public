import json
import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

_JD_KEYWORDS = [
    "자격요건", "우대사항", "담당업무", "지원자격", "직무소개", "자격조건",
    "근무조건", "모집요강", "필수요건", "이런 분", "모집부문", "지원방법",
    "주요업무", "직무내용", "업무내용", "채용조건",
    # 현대 ATS(ninehire, 그린잡 등) 스타일 키워드
    "이런 업무", "이런 경험", "전형절차", "합류", "함께할", "이런 분들",
    "요구사항", "포지션", "직무기술서",
    "requirements", "qualifications", "responsibilities",
]


def _looks_like_jd(text: str) -> bool:
    lower = text.lower()
    return any(kw.lower() in lower for kw in _JD_KEYWORDS)


def _extract_text(soup: BeautifulSoup) -> str:
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    lines = [line.strip() for line in soup.get_text(separator="\n").splitlines() if line.strip()]
    return "\n".join(lines)


def _fetch_iframe_text(iframes, base_url: str) -> str:
    """iframe src를 따라가서 JD 텍스트를 추출."""
    for iframe in iframes:
        src = iframe.get("src") or iframe.get("data-src")
        if not src or src.startswith(("javascript:", "about:")):
            continue
        iframe_url = urljoin(base_url, src)
        try:
            r = requests.get(iframe_url, headers=HEADERS, timeout=10)
            if not r.ok:
                continue
            iframe_soup = BeautifulSoup(r.text, "lxml")
            text = _extract_text(iframe_soup)
            if _looks_like_jd(text) and len(text) > 200:
                return text
        except Exception:
            continue
    return ""


# ── 잡코리아 전용 크롤러 ──────────────────────────────────────

_JOBKOREA_BASE = "https://www.jobkorea.co.kr"


def _fetch_jobkorea(url: str) -> tuple[bool, str]:
    """잡코리아 전용 크롤러.
    iframe이 JS로 동적 생성되므로 raw HTML에서 정규식으로 Ifrm URL을 추출."""
    main_resp = requests.get(url, headers=HEADERS, timeout=10)
    main_resp.raise_for_status()
    html = main_resp.text

    # 메인에서 기본 정보 추출 (고용형태, 경력, 마감일 등)
    meta_text = _extract_text(BeautifulSoup(html, "lxml"))

    # JS 안에 &(리터럴)로 인코딩된 Ifrm URL 추출
    match = re.search(r'GI_Read_Comt_Ifrm[^"<>]{10,300}', html)
    if not match:
        if _looks_like_jd(meta_text) and len(meta_text) > 200:
            return True, meta_text[:20000]
        return False, "JD 내용을 읽지 못했어요"

    raw_path = match.group(0)
    # & (6글자 리터럴) → & 치환 후 끝의 백슬래시 제거
    decoded_path = raw_path.replace("\\u0026", "&").rstrip("\\")
    iframe_url = f"{_JOBKOREA_BASE}/Recruit/{decoded_path}"

    iframe_resp = requests.get(iframe_url, headers=HEADERS, timeout=10)
    iframe_resp.raise_for_status()
    jd_text = _extract_text(BeautifulSoup(iframe_resp.text, "lxml"))

    if not jd_text.strip():
        return False, "채용공고 내용을 텍스트로 읽지 못했어요 (이미지 형식일 수 있어요)"

    combined = f"{meta_text}\n\n[상세 채용 정보]\n{jd_text}"
    return True, combined[:20000]


# ── 사람인 전용 크롤러 ──────────────────────────────────────

_SARAMIN_AJAX = "https://www.saramin.co.kr/zf_user/jobs/relay/view-ajax"
_SARAMIN_HEADERS = {**HEADERS, "X-Requested-With": "XMLHttpRequest"}

# 메타데이터 레이블(경력, 학력 등)과 달리 실제 JD 본문에만 등장하는 키워드
_SARAMIN_CONTENT_MARKERS = [
    "담당업무", "주요업무", "이런 업무",
    "이런 분을", "이런 분이면", "이런 분들을",
    "우대사항", "우대 사항",
    "직무 소개", "포지션 소개",
    "자격 요건", "필수 자격", "필수요건",
]


def _has_jd_content(text: str) -> bool:
    return any(kw in text for kw in _SARAMIN_CONTENT_MARKERS)


def _fetch_saramin(url: str) -> tuple[bool, str]:
    """사람인 전용 크롤러.
    relay/view-ajax로 텍스트 JD 추출. 실제 상세 내용 없으면 이미지형으로 판단."""
    match = re.search(r'rec_idx=(\d+)', url)
    if not match:
        return False, "rec_idx를 URL에서 찾지 못했어요"
    rec_idx = match.group(1)

    ajax_headers = {**_SARAMIN_HEADERS, "Referer": url}
    resp = requests.get(
        _SARAMIN_AJAX,
        params={"rec_idx": rec_idx, "view_type": "public-recruit"},
        headers=ajax_headers,
        timeout=10,
    )
    resp.raise_for_status()

    jd_text = _extract_text(BeautifulSoup(resp.text, "lxml"))

    # 실제 JD 상세 내용(담당업무, 이런 분을 등)이 없으면 이미지형으로 판단
    if not _has_jd_content(jd_text):
        return False, "이미지형 JD예요. 공고 화면을 캡처해서 '이미지 업로드' 방식으로 분석해보세요."

    return True, jd_text[:20000]


# ── JSON-LD 구조화 데이터 추출 ────────────────────────────────

def _extract_jsonld(soup: BeautifulSoup) -> str:
    """<script type="application/ld+json"> 안의 JobPosting 데이터 추출."""
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            if not isinstance(data, dict):
                continue
            if data.get("@type") not in ("JobPosting", "Job"):
                continue
            parts = []
            org = data.get("hiringOrganization", {})
            if isinstance(org, dict) and org.get("name"):
                parts.append(f"회사: {org['name']}")
            title = data.get("title") or data.get("name")
            if title:
                parts.append(f"직무명: {title}")
            for field, label in [
                ("description", "상세내용"),
                ("qualifications", "자격요건"),
                ("responsibilities", "담당업무"),
                ("skills", "기술스택"),
                ("jobBenefits", "혜택"),
            ]:
                val = data.get(field)
                if not val:
                    continue
                if isinstance(val, list):
                    val = ", ".join(str(v) for v in val)
                clean = BeautifulSoup(str(val), "lxml").get_text(separator="\n").strip()
                parts.append(f"{label}:\n{clean}")
            if parts:
                return "\n\n".join(parts)
        except Exception:
            continue
    return ""


def _collect_long_strings(obj, result: list, min_len: int = 50):
    """중첩 JSON에서 긴 문자열 값을 재귀적으로 수집."""
    if isinstance(obj, str):
        if len(obj) >= min_len:
            result.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            _collect_long_strings(v, result, min_len)
    elif isinstance(obj, list):
        for item in obj:
            _collect_long_strings(item, result, min_len)


# ── ninehire 전용 크롤러 ──────────────────────────────────────

def _fetch_ninehire(url: str) -> tuple[bool, str]:
    """ninehire ATS 전용 크롤러. API → JSON-LD → 일반 파싱 순으로 시도."""
    match = re.search(r'/job_posting/([^?/&#]+)', url)
    if not match:
        return False, "posting ID를 URL에서 찾지 못했어요"
    posting_id = match.group(1)
    company_slug = urlparse(url).hostname.split('.')[0]

    for api_url in [
        f"https://api.ninehire.site/v1/job_postings/{posting_id}",
        f"https://{company_slug}.ninehire.site/api/job_postings/{posting_id}",
        f"https://www.ninehire.site/api/v1/job_postings/{posting_id}",
    ]:
        try:
            r = requests.get(api_url, headers=HEADERS, timeout=8)
            if r.ok and "json" in r.headers.get("content-type", ""):
                texts: list[str] = []
                _collect_long_strings(r.json(), texts)
                joined = "\n\n".join(texts)
                if _looks_like_jd(joined) and len(joined) > 200:
                    return True, joined[:20000]
        except Exception:
            continue

    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        jld = _extract_jsonld(soup)
        if jld and len(jld) > 200:
            return True, jld[:20000]

        text = _extract_text(soup)
        if len(text) > 200:  # ninehire URL이면 job posting임을 알고 있으므로 키워드 체크 생략
            return True, text[:20000]
    except Exception as e:
        return False, str(e)

    return False, "ninehire 공고를 자동으로 읽지 못했어요. 공고 화면을 캡처해서 '이미지 업로드'로 분석해보세요."


# ── 범용 크롤러 ──────────────────────────────────────────────

def fetch_jd_from_url(url: str) -> tuple[bool, str]:
    """Returns (success, text_or_error_message)."""
    try:
        # 사이트별 전용 크롤러 라우팅
        if "jobkorea.co.kr" in url:
            return _fetch_jobkorea(url)
        if "saramin.co.kr" in url:
            return _fetch_saramin(url)
        if "ninehire.site" in url:
            return _fetch_ninehire(url)

        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml")
        iframes = soup.find_all("iframe")  # decompose 전에 수집

        # JSON-LD structured data 먼저 시도 (SPA 사이트도 SEO용으로 삽입하는 경우 있음)
        jld = _extract_jsonld(soup)
        if jld and len(jld) > 200:
            return True, jld[:20000]

        cleaned = _extract_text(soup)

        if len(cleaned) < 200:
            return False, "페이지에서 충분한 텍스트를 가져오지 못했어요"

        # ATS 연동 공고 또는 JD 키워드 없음 → iframe fallback
        if "채용 관리 솔루션" in cleaned or not _looks_like_jd(cleaned):
            iframe_text = _fetch_iframe_text(iframes, url)
            if iframe_text:
                return True, iframe_text[:20000]
            if "채용 관리 솔루션" in cleaned:
                return False, "외부 채용 시스템 연동 공고예요. JD 내용을 직접 복사해 붙여넣어 주세요."
            return False, "채용공고 내용을 텍스트로 읽지 못했어요 (이미지 형식일 수 있어요)"

        return True, cleaned[:20000]

    except requests.exceptions.Timeout:
        return False, "요청 시간이 초과됐어요"
    except requests.exceptions.HTTPError as e:
        return False, f"페이지 접근 실패 ({e.response.status_code})"
    except Exception as e:
        return False, str(e)


def fetch_images_from_url(url: str) -> list[bytes]:
    """페이지에서 콘텐츠 이미지(20KB 이상)를 최대 5개 다운로드해 반환."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        result = []
        seen = set()
        for img in soup.find_all("img"):
            src = (
                img.get("src")
                or img.get("data-src")
                or img.get("data-original")
                or img.get("data-lazy-src")
            )
            if not src or src.startswith("data:"):
                continue
            img_url = urljoin(url, src)
            if img_url in seen:
                continue
            seen.add(img_url)
            try:
                r = requests.get(img_url, headers=HEADERS, timeout=10)
                if r.ok and len(r.content) > 20_000:
                    result.append(r.content)
                    if len(result) >= 5:
                        break
            except Exception:
                continue
        return result
    except Exception:
        return []
