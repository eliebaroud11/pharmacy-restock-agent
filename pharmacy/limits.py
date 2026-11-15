"""Usage limits on AI calls, so nobody (a mistake, a stuck tab or a bad actor) can drain the AI credit.

Counts come from the audit log, so they survive restarts and apply across browser tabs.
"""
import os
from datetime import datetime, timedelta

from .db import log

PER_USER_PER_HOUR = int(os.environ.get("PHARMA_AI_PER_USER_HOUR", "30"))
ALL_USERS_PER_DAY = int(os.environ.get("PHARMA_AI_PER_DAY", "300"))
ACTION = "ai call"


class LimitReached(Exception):
    pass


def _count(conn, since, actor=None):
    q = "SELECT COUNT(*) FROM audit_log WHERE action = ? AND at >= ?"
    args = [ACTION, since.isoformat(timespec="seconds")]
    if actor is not None:
        q += " AND actor = ?"
        args.append(actor)
    return conn.execute(q, args).fetchone()[0]


def use_ai(conn, actor: str, what: str):
    """Call before every AI request. Records it, or raises LimitReached without calling the AI."""
    now = datetime.now()
    if _count(conn, now - timedelta(hours=1), actor) >= PER_USER_PER_HOUR:
        raise LimitReached(f"You've reached the limit of {PER_USER_PER_HOUR} AI checks per hour. Try again later.")
    if _count(conn, now - timedelta(days=1)) >= ALL_USERS_PER_DAY:
        raise LimitReached(f"The pharmacy reached its daily limit of {ALL_USERS_PER_DAY} AI checks. Contact an administrator.")
    log(conn, actor, ACTION, {"what": what})
    conn.commit()
