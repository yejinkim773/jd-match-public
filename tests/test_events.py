from unittest.mock import MagicMock, patch
import modules.events as events


def test_capture_calls_posthog_client():
    mock_client = MagicMock()
    events._client = mock_client
    with patch.object(events, "_session_id", return_value="sess-abc"):
        events.capture("analysis_started", {"score": 82})
    mock_client.capture.assert_called_once_with(
        "sess-abc", "analysis_started", {"score": 82}
    )
    events._client = None


def test_capture_noop_when_not_initialized():
    events._client = None
    events.capture("analysis_started")  # 예외 없이 종료


def test_capture_uses_empty_dict_when_no_properties():
    mock_client = MagicMock()
    events._client = mock_client
    with patch.object(events, "_session_id", return_value="sess-xyz"):
        events.capture("app_loaded")
    mock_client.capture.assert_called_once_with("sess-xyz", "app_loaded", {})
    events._client = None
