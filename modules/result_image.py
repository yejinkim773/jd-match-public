import io
from PIL import Image, ImageDraw, ImageFont

_W, _H = 800, 480
_HEADER_H = 64
_BG = "#FFFFFF"
_HEADER_BG = "#1E293B"
_TEXT_DARK = "#1E293B"
_TEXT_GRAY = "#64748B"

_GRADE_COLORS = {
    "적합도 높음":      "#10B981",
    "대체로 적합":      "#34D399",
    "보완 후 지원 권장": "#F59E0B",
    "추가 준비 필요":   "#F97316",
}


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
    draw.text((24, 18), "JD 매칭 분석기", fill="#FFFFFF", font=_font(20))

    # 회사 · 포지션
    company = result.get("company", "")
    position = result.get("position", "")
    title = f"{company}  ·  {position}" if company or position else "분석 결과"
    draw.text((32, _HEADER_H + 24), title, fill=_TEXT_DARK, font=_font(22))

    # 적합도 레이블
    grade = result.get("grade", "추가 준비 필요")
    grade_color = _GRADE_COLORS.get(grade, "#6B7280")
    draw.text((32, _HEADER_H + 72), "적합도", fill=_TEXT_GRAY, font=_font(14))
    draw.text((32, _HEADER_H + 92), grade, fill=grade_color, font=_font(32))

    # 총평
    summary = result.get("summary", "")
    draw.text((32, _HEADER_H + 152), "총평", fill=_TEXT_GRAY, font=_font(14))
    draw.text((32, _HEADER_H + 172), _wrap(summary, 52), fill=_TEXT_DARK, font=_font(16))

    # 워터마크
    draw.text((32, _H - 32), "jd-match.streamlit.app", fill=_TEXT_GRAY, font=_font(13))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
