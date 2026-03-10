"""Webhook Sink Plugin — POST screening decisions to any URL."""

import dataclasses
import json
from typing import Any

import httpx

from narrowfield import (
    PluginInfo,
    ScreeningDecision,
)


class Plugin:
    """Send screening decisions to a webhook endpoint."""

    def __init__(self):
        self.url: str = ""
        self.auth_header: str = ""
        self.timeout: float = 10.0

    def info(self) -> PluginInfo:
        return PluginInfo(
            name="webhook",
            display_name="Webhook",
            version="0.1.0",
            description="POST screening decisions to any webhook URL",
            capabilities=["sink:decisions"],
        )

    def configure(self, config: dict[str, Any]) -> None:
        self.url = config["url"]
        self.auth_header = config.get("auth_header", "")
        self.timeout = float(config.get("timeout", 10))

    def test_connection(self) -> dict[str, Any]:
        if not self.url:
            return {"ok": False, "message": "No URL configured"}
        try:
            headers = {}
            if self.auth_header:
                headers["Authorization"] = self.auth_header
            resp = httpx.get(self.url, headers=headers, timeout=self.timeout)
            return {"ok": resp.status_code < 400, "message": f"HTTP {resp.status_code}"}
        except Exception as e:
            return {"ok": False, "message": str(e)}

    def send_decision(self, decision: ScreeningDecision) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self.auth_header:
            headers["Authorization"] = self.auth_header

        payload = dataclasses.asdict(decision)
        # bytes aren't JSON-serializable — drop resume_bytes if somehow present
        payload.pop("resume_bytes", None)

        try:
            resp = httpx.post(self.url, json=payload, headers=headers, timeout=self.timeout)
            external_id = ""
            try:
                external_id = resp.json().get("id", "")
            except Exception:
                pass
            return {
                "ok": resp.status_code < 300,
                "message": f"HTTP {resp.status_code}",
                "external_id": str(external_id),
            }
        except Exception as e:
            return {"ok": False, "message": str(e), "external_id": ""}

    def send_decisions(self, decisions: list[ScreeningDecision]) -> dict[str, Any]:
        sent = 0
        failed = 0
        for d in decisions:
            result = self.send_decision(d)
            if result["ok"]:
                sent += 1
            else:
                failed += 1
        return {
            "ok": failed == 0,
            "message": f"Sent {sent}, failed {failed}",
            "sent": sent,
            "failed": failed,
        }
