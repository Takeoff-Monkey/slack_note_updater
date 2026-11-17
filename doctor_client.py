"""
doctor_client.py — drop-in health reporter for Doctor Bot.

Copy this single file into any Python app. No third-party deps required
(uses urllib from the stdlib), but if `requests` is installed it will use it.

Setup (env vars on the reporting app):
    DOCTOR_URL            e.g. https://doctor-bot.fly.dev
    DOCTOR_SECRET         the INGEST_SHARED_SECRET configured on Doctor Bot
    DOCTOR_SERVICE_ID     the service id you registered, e.g. "takeo-reviewer"

Quick start:
    from doctor_client import Doctor
    doctor = Doctor()                 # reads env vars
    doctor.start_heartbeat()          # background thread, beats every 60s

    # Report a handled error:
    try:
        risky()
    except Exception as e:
        doctor.error("risky() failed", exc=e)
        raise

    # Ship a batch of log lines:
    doctor.log(["started run", "processed 42 items"])

All calls are best-effort and never raise into your app: if Doctor Bot is
down, your app keeps running and the failure is swallowed (optionally logged).
"""

from __future__ import annotations

import json
import os
import threading
import time
import traceback
import urllib.request
import urllib.error
from typing import Any, Iterable, Optional

try:  # optional, nicer if present
    import requests  # type: ignore
    _HAVE_REQUESTS = True
except Exception:  # pragma: no cover
    _HAVE_REQUESTS = False


class Doctor:
    def __init__(
        self,
        url: Optional[str] = None,
        secret: Optional[str] = None,
        service_id: Optional[str] = None,
        version: Optional[str] = None,
        commit_sha: Optional[str] = None,
        heartbeat_interval_sec: int = 60,
        verbose: bool = False,
    ) -> None:
        self.url = (url or os.environ.get("DOCTOR_URL", "")).rstrip("/")
        self.secret = secret or os.environ.get("DOCTOR_SECRET", "")
        self.service_id = service_id or os.environ.get("DOCTOR_SERVICE_ID", "")
        self.version = version or os.environ.get("APP_VERSION")
        # Heroku/Render/Fly commonly expose a commit sha under various names.
        self.commit_sha = (
            commit_sha
            or os.environ.get("COMMIT_SHA")
            or os.environ.get("HEROKU_SLUG_COMMIT")
            or os.environ.get("RAILWAY_GIT_COMMIT_SHA")
        )
        self.interval = heartbeat_interval_sec
        self.verbose = verbose
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        # Current status reported by the heartbeat; your app can flip this.
        self.status = "ok"

        if not (self.url and self.secret and self.service_id):
            self._warn(
                "Doctor not fully configured (need DOCTOR_URL, DOCTOR_SECRET, "
                "DOCTOR_SERVICE_ID). Reporting is disabled."
            )

    # ---- public API ----

    def heartbeat(self, status: Optional[str] = None, **metadata: Any) -> None:
        """Send a single heartbeat. status in {ok, degraded, failing}."""
        self._post(
            "/heartbeat",
            {
                "service_id": self.service_id,
                "status": status or self.status,
                "version": self.version,
                "commit_sha": self.commit_sha,
                "metadata": metadata or {},
            },
        )

    def event(
        self,
        severity: str,
        message: str,
        *,
        exc: Optional[BaseException] = None,
        source: Optional[str] = None,
        correlation_id: Optional[str] = None,
        **metadata: Any,
    ) -> None:
        """Report an event. severity in {info, warning, error, critical}."""
        stacktrace = None
        if exc is not None:
            stacktrace = "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            )
        self._post(
            "/event",
            {
                "service_id": self.service_id,
                "severity": severity,
                "source": source,
                "message": message,
                "stacktrace": stacktrace,
                "correlation_id": correlation_id,
                "metadata": metadata or {},
            },
        )

    def error(self, message: str, *, exc: Optional[BaseException] = None, **md: Any) -> None:
        self.event("error", message, exc=exc, **md)

    def critical(self, message: str, *, exc: Optional[BaseException] = None, **md: Any) -> None:
        self.event("critical", message, exc=exc, **md)

    def warning(self, message: str, **md: Any) -> None:
        self.event("warning", message, **md)

    def info(self, message: str, **md: Any) -> None:
        self.event("info", message, **md)

    def log(self, lines: Iterable[str], level: str = "info") -> None:
        """Ship a batch of log lines."""
        entries = [{"level": level, "message": str(line)} for line in lines]
        if not entries:
            return
        self._post("/log", {"service_id": self.service_id, "entries": entries})

    def run(
        self,
        *,
        user_id: Optional[str] = None,
        user_name: Optional[str] = None,
        action: Optional[str] = None,
        status: str = "ok",
        **metadata: Any,
    ) -> None:
        """Record one user-triggered run of this service (usage telemetry).

        Example (Slack slash command):
            doctor.run(user_id=command["user_id"],
                       user_name=command.get("user_name"),
                       action="/review")
        """
        self._post(
            "/run",
            {
                "service_id": self.service_id,
                "user_id": user_id,
                "user_name": user_name,
                "action": action,
                "status": status,
                "metadata": metadata or {},
            },
        )

    def start_heartbeat(self) -> None:
        """Begin a daemon thread that beats every `interval` seconds."""
        if self._thread is not None:
            return
        if not (self.url and self.secret and self.service_id):
            return

        def loop() -> None:
            # Beat once immediately so the service shows up fast.
            self.heartbeat()
            while not self._stop.wait(self.interval):
                self.heartbeat()

        self._thread = threading.Thread(target=loop, daemon=True, name="doctor-heartbeat")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    # ---- internals ----

    def _post(self, path: str, payload: dict) -> None:
        if not (self.url and self.secret and self.service_id):
            return
        body = {k: v for k, v in payload.items() if v is not None}
        data = json.dumps(body).encode("utf-8")
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {self.secret}",
        }
        target = f"{self.url}{path}"
        try:
            if _HAVE_REQUESTS:
                requests.post(target, data=data, headers=headers, timeout=5)
            else:
                req = urllib.request.Request(target, data=data, headers=headers, method="POST")
                urllib.request.urlopen(req, timeout=5).read()
        except Exception as e:  # never break the host app
            self._warn(f"doctor post to {path} failed: {e}")

    def _warn(self, msg: str) -> None:
        if self.verbose:
            print(f"[doctor] {msg}")
