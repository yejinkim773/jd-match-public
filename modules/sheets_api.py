from datetime import datetime

import gspread
import streamlit as st
from google.oauth2.service_account import Credentials

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]
_FEEDBACK_HEADERS = ["타임스탬프", "도움여부", "이유", "스코어"]


def _feedback_sheet() -> gspread.Worksheet:
    creds = Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]), scopes=_SCOPES
    )
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(st.secrets["SPREADSHEET_ID"])
    try:
        ws = spreadsheet.worksheet("피드백")
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title="피드백", rows=1000, cols=4)
        ws.append_row(_FEEDBACK_HEADERS)
    return ws


def save_feedback(helpful: bool, reason: str, score: int) -> None:
    ws = _feedback_sheet()
    ws.append_row([
        datetime.now().isoformat(),
        "yes" if helpful else "no",
        reason,
        score,
    ])
