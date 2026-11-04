"""Bounded, anonymous browser sessions for the public portfolio demonstration."""

import secrets
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from http.cookies import CookieError, SimpleCookie

from querylens.service import timestamp

COOKIE_NAME = "__Host-querylens-session"


@dataclass
class DemoSession:
    key: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    touched: float = field(default_factory=time.monotonic)
    requests: deque = field(default_factory=deque)
    plans: OrderedDict = field(default_factory=OrderedDict)
    history: deque = field(default_factory=lambda: deque(maxlen=50))


class DemoSessions:
    def __init__(self, *, ttl=3600, capacity=128):
        self.ttl = ttl
        self.capacity = capacity
        self.sessions = OrderedDict()
        self.requests = deque()
        self.lock = threading.RLock()

    def get(self, cookie_header, *, create=False):
        cookies = SimpleCookie()
        try:
            cookies.load(cookie_header or "")
        except CookieError:
            pass
        key = cookies[COOKIE_NAME].value if COOKIE_NAME in cookies else None
        now = time.monotonic()
        with self.lock:
            expired = [k for k, s in self.sessions.items() if now - s.touched >= self.ttl]
            for expired_key in expired:
                del self.sessions[expired_key]
            session = self.sessions.get(key)
            created = session is None and create
            if created:
                session = DemoSession()
                self.sessions[session.key] = session
                while len(self.sessions) > self.capacity:
                    self.sessions.popitem(last=False)
            if session:
                session.touched = now
                self.sessions.move_to_end(session.key)
            return session, created

    def allow(self, session):
        now = time.monotonic()
        with self.lock:
            for queue in (session.requests, self.requests):
                while queue and now - queue[0] >= 60:
                    queue.popleft()
            if len(session.requests) >= 20 or len(self.requests) >= 120:
                return False
            session.requests.append(now)
            self.requests.append(now)
            return True

    def remember(self, session, plan):
        with self.lock:
            session.plans[plan["id"]] = plan
            while len(session.plans) > 20:
                session.plans.popitem(last=False)

    def plan(self, session, plan_id):
        if not isinstance(plan_id, str):
            return None
        with self.lock:
            return session.plans.get(plan_id)

    def record(self, session, question, source, status, *, result=None, detail=""):
        result = result or {}
        with self.lock:
            session.history.appendleft(
                {
                    "created": timestamp(),
                    "question": question[:1000],
                    "source": source,
                    "status": status,
                    "row_count": result.get("row_count", 0),
                    "duration_ms": result.get("duration_ms", 0),
                    "detail": detail[:1000],
                }
            )

    def history(self, session):
        with self.lock:
            return list(session.history) if session else []
