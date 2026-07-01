import uuid
import streamlit as st

_client = None


def init(api_key: str) -> None:
    from posthog import Posthog
    global _client
    print(f"[PostHog] init called, key prefix: {api_key[:12]}...")
    _client = Posthog(
        project_api_key=api_key,
        host="https://us.i.posthog.com",
        flush_at=1,
    )
    print(f"[PostHog] client created: {_client is not None}")


def _session_id() -> str:
    if "session_id" not in st.session_state:
        st.session_state.session_id = str(uuid.uuid4())
    return st.session_state.session_id


def capture(event: str, properties: dict | None = None) -> None:
    if _client is None:
        print(f"[PostHog] SKIP '{event}' — client is None")
        return
    print(f"[PostHog] capture: {event} {properties or {}}")
    _client.capture(_session_id(), event, properties or {})
