"""Display helpers for untrusted text (invoice content and AI output).

Streamlit renders labels, st.markdown, st.info, st.error etc. as Markdown, so a malicious
invoice could put a clickable link or an image that loads from an outside server on screen.
plain() escapes every Markdown/HTML control character so the text shows exactly as written.
"""
import re

_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+\-.!|<>~$:])")


def plain(value, limit: int = 500) -> str:
    s = "" if value is None else str(value)
    s = s.replace("\r", " ").replace("\n", " ")
    if len(s) > limit:
        s = s[:limit] + "…"
    return _SPECIAL.sub(r"\\\1", s)
