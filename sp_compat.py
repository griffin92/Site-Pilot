"""Streamlit API compatibility shim.

Streamlit 1.49 deprecated `use_container_width=True` in favour of
`width="stretch"` on image/button/dataframe widgets. Passing the old kwarg on a
new version emits deprecation warnings and will eventually break; passing the
new value on an old version raises immediately. Detect once, then use the right
one everywhere.
"""
from functools import lru_cache


@lru_cache(maxsize=1)
def _streamlit_version():
    try:
        from importlib.metadata import version
        parts = version("streamlit").split(".")
        return (int(parts[0]), int(parts[1]))
    except Exception:
        return (1, 40)   # assume older; the legacy kwarg still works there


@lru_cache(maxsize=1)
def _use_new_width_api():
    return _streamlit_version() >= (1, 49)


def stretch():
    """Kwargs that make a widget fill its container, on either API."""
    return {"width": "stretch"} if _use_new_width_api() else {"use_container_width": True}
