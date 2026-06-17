from PIL import Image
import io
from modules.result_image import generate_result_image


_SAMPLE = {
    "company": "카카오",
    "position": "PM (서비스기획)",
    "score": 82,
    "summary": "SQL 실무 경험을 구체적으로 보완하면 지원 경쟁력이 높아질 것 같아요.",
}


def test_returns_bytes():
    result = generate_result_image(_SAMPLE)
    assert isinstance(result, bytes)
    assert len(result) > 0


def test_output_is_valid_png():
    result = generate_result_image(_SAMPLE)
    img = Image.open(io.BytesIO(result))
    assert img.format == "PNG"


def test_image_dimensions():
    result = generate_result_image(_SAMPLE)
    img = Image.open(io.BytesIO(result))
    assert img.width == 800
    assert img.height == 480


def test_handles_missing_fields():
    result = generate_result_image({})
    assert isinstance(result, bytes)
