import uuid
import streamlit as st

_client = None


def init(api_key: str) -> None:
    from posthog import Posthog
    global _client
    _client = Posthog(project_api_key=api_key, host="https://app.posthog.com")


def _session_id() -> str:
    if "session_id" not in st.session_state:
        st.session_state.session_id = str(uuid.uuid4())
    return st.session_state.session_id


def capture(event: str, properties: dict | None = None) -> None:
    if _client is None:
        return
    _client.capture(_session_id(), event, properties or {})
