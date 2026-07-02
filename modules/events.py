import streamlit as st

_client = None


def init(api_key: str) -> None:
    from posthog import Posthog
    global _client
    if _client is not None:
        return
    _client = Posthog(
        project_api_key=api_key,
        host="https://us.i.posthog.com",
        flush_at=1,
    )


def _tracking_context() -> tuple[str, bool, str]:
    return (
        st.session_state.get("_uid", ""),
        st.session_state.get("_is_internal", False),
        st.session_state.get("_utm_source", ""),
    )


def capture(event: str, properties: dict | None = None) -> None:
    if _client is None:
        return
    uid, is_internal, utm_source = _tracking_context()
    props = {
        "is_internal": is_internal,
        "utm_source": utm_source,
        **(properties or {}),
    }
    _client.capture(
        distinct_id=uid,
        event=event,
        properties=props,
    )
