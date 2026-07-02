from unittest.mock import MagicMock, patch
import modules.events as events


def test_capture_calls_posthog_client():
    mock_client = MagicMock()
    events._client = mock_client
    with patch.object(events, "_tracking_context", return_value=("sess-abc", False, "")):
        events.capture("analysis_started", {"score": 82})
    mock_client.capture.assert_called_once_with(
        distinct_id="sess-abc",
        event="analysis_started",
        properties={"score": 82, "is_internal": False, "utm_source": ""},
    )
    events._client = None


def test_capture_noop_when_not_initialized():
    events._client = None
    events.capture("analysis_started")  # 예외 없이 종료


def test_capture_uses_empty_dict_when_no_properties():
    mock_client = MagicMock()
    events._client = mock_client
    with patch.object(events, "_tracking_context", return_value=("sess-xyz", False, "")):
        events.capture("app_loaded")
    mock_client.capture.assert_called_once_with(
        distinct_id="sess-xyz",
        event="app_loaded",
        properties={"is_internal": False, "utm_source": ""},
    )
    events._client = None


def test_capture_attaches_is_internal_true():
    mock_client = MagicMock()
    events._client = mock_client
    with patch.object(events, "_tracking_context", return_value=("uid-123", True, "ev")):
        events.capture("app_loaded")
    props = mock_client.capture.call_args.kwargs["properties"]
    assert props["is_internal"] is True
    assert props["utm_source"] == "ev"
    events._client = None


def test_capture_utm_source_preserved_with_other_properties():
    mock_client = MagicMock()
    events._client = mock_client
    with patch.object(events, "_tracking_context", return_value=("uid-456", False, "lk")):
        events.capture("jd_registered", {"method": "url"})
    props = mock_client.capture.call_args.kwargs["properties"]
    assert props["utm_source"] == "lk"
    assert props["method"] == "url"
    events._client = None
