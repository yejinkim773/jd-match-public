from datetime import date

import gspread
import streamlit as st
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

HEADERS = [
    "분석일", "회사명", "포지션", "매칭 스코어",
    "마감일", "강점", "총평", "JD URL", "지원 여부",
]


def _sheet():
    creds = Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]), scopes=SCOPES
    )
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(st.secrets["SPREADSHEET_ID"])
    try:
        ws = spreadsheet.worksheet("공고목록")
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title="공고목록", rows=500, cols=len(HEADERS))
        ws.append_row(HEADERS)
    return ws


def save_result(result: dict, jd_url: str = "") -> None:
    ws = _sheet()
    preferred = result.get("preferred_matches", [])
    strengths_text = "\n".join(p.get("requirement", "") for p in preferred)
    row = [
        date.today().isoformat(),
        result.get("company", "미확인"),
        result.get("position", ""),
        result.get("score", 0),
        result.get("deadline") or "",
        strengths_text,
        result.get("summary", ""),
        jd_url,
        "N",
    ]
    ws.append_row(row, value_input_option="USER_ENTERED")


def update_applied(row: int, applied: bool) -> None:
    ws = _sheet()
    col = HEADERS.index("지원 여부") + 1
    ws.update_cell(row, col, "Y" if applied else "N")


def fetch_jobs() -> list[dict]:
    ws = _sheet()
    rows = ws.get_all_records()
    jobs = []
    for i, row in enumerate(rows, start=2):
        jobs.append({
            "row": i,
            "company": row.get("회사명", ""),
            "position": row.get("포지션", ""),
            "score": int(row.get("매칭 스코어") or 0),
            "deadline": row.get("마감일") or None,
            "applied": str(row.get("지원 여부", "N")).upper() == "Y",
            "summary": row.get("총평", ""),
            "url": row.get("JD URL", ""),
        })
    return jobs
