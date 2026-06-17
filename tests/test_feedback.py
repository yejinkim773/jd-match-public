from unittest.mock import MagicMock, patch, call
from datetime import datetime


def test_save_feedback_appends_row():
    mock_ws = MagicMock()
    with patch("modules.sheets_api._feedback_sheet", return_value=mock_ws), \
         patch("modules.sheets_api.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 6, 17, 12, 0, 0)
        from modules.sheets_api import save_feedback
        save_feedback(helpful=True, reason="", score=82)

    mock_ws.append_row.assert_called_once_with(
        ["2026-06-17T12:00:00", "yes", "", 82]
    )


def test_save_feedback_no_when_not_helpful():
    mock_ws = MagicMock()
    with patch("modules.sheets_api._feedback_sheet", return_value=mock_ws), \
         patch("modules.sheets_api.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 6, 17, 12, 0, 0)
        from modules.sheets_api import save_feedback
        save_feedback(helpful=False, reason="결과가 부정확한 것 같아요", score=45)

    mock_ws.append_row.assert_called_once_with(
        ["2026-06-17T12:00:00", "no", "결과가 부정확한 것 같아요", 45]
    )
