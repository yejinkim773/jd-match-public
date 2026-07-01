import base64
import io
import json
import re
from pathlib import Path

import requests
import streamlit as st
from PIL import Image

_PROMPT_FILE = Path(__file__).parent.parent / "prompt.md"


def _load_prompt(resume: str, jd: str) -> str:
    template = _PROMPT_FILE.read_text(encoding="utf-8")
    return template.replace("{resume}", resume).replace("{jd}", jd)

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
_MODEL = "gemini-2.5-flash"
_GEMINI_URL = f"{_BASE_URL}/models/{_MODEL}:generateContent"
_TIMEOUT = 30


def _call(parts: list, timeout: int = _TIMEOUT) -> str:
    api_key = st.secrets["GOOGLE_API_KEY"]
    resp = requests.post(
        f"{_GEMINI_URL}?key={api_key}",
        json={"contents": [{"parts": parts}]},
        timeout=timeout,
    )
    if not resp.ok:
        raise ValueError(f"Google API 오류 ({resp.status_code}): {resp.text}")
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"]


def _parse_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"JSON을 찾을 수 없어요. 응답 원문: {text[:300]}")
    return json.loads(match.group())


def list_models() -> list[str]:
    api_key = st.secrets["GOOGLE_API_KEY"]
    resp = requests.get(f"{_BASE_URL}/models?key={api_key}", timeout=10)
    if not resp.ok:
        return [f"오류: {resp.text[:200]}"]
    models = resp.json().get("models", [])
    return [m["name"] for m in models if "generateContent" in m.get("supportedGenerationMethods", [])]


def test_connection() -> str:
    api_key = st.secrets["GOOGLE_API_KEY"]
    resp = requests.post(
        f"{_GEMINI_URL}?key={api_key}",
        json={"contents": [{"parts": [{"text": "안녕"}]}]},
        timeout=_TIMEOUT,
    )
    return f"Status: {resp.status_code}\n\n{resp.text[:800]}"


def extract_text_from_image(image_bytes: bytes) -> str:
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    return _call([
        {"text": (
            "이 이미지에서 채용공고 텍스트를 추출해주세요. "
            "반드시 한국어(한글)로 출력하고, 한자(중국어)나 일본어로 변환하지 마세요. "
            "원문의 줄바꿈 구조를 최대한 유지해주세요."
        )},
        {"inline_data": {"mime_type": "image/jpeg", "data": b64}},
    ])


def _compute_grade(required_matches: list[dict]) -> str:
    valid = [r for r in required_matches if isinstance(r, dict)]
    scoreable = [
        r for r in valid
        if str(r.get("category", "skill_based")).strip().lower() == "skill_based"
    ]
    total = len(scoreable)
    if total == 0:
        return "추가 준비 필요"
    matched = sum(1 for r in scoreable if r.get("status") == "matched")
    partial = sum(1 for r in scoreable if r.get("status") == "partial")
    ratio = (matched + partial * 0.5) / total

    if ratio >= 0.85:
        return "적합도 높음"
    elif ratio >= 0.70:
        return "대체로 적합"
    elif ratio >= 0.50:
        return "보완 후 지원 권장"
    else:
        return "추가 준비 필요"


_MAX_INPUT_CHARS = 10_000


def analyze_match(resume: str, jd: str) -> dict:
    if len(resume) > _MAX_INPUT_CHARS or len(jd) > _MAX_INPUT_CHARS:
        raise ValueError("too_long")
    prompt = _load_prompt(resume, jd)
    result = _parse_json(_call([{"text": prompt}], timeout=60))
    result.pop("grade", None)
    result["grade"] = _compute_grade(result.get("required_matches", []))
    return result
