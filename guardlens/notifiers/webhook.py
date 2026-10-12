"""Webhook notifier using the standard library (no additional dependency)."""
from __future__ import annotations

import json
from urllib.request import Request, urlopen

from guardlens.notifiers import Notifier, register_notifier


@register_notifier
class WebhookNotifier(Notifier):
    key = "webhook"
    config_schema = {
        "url": {"type": "url", "required": True, "label": "Webhook address", "help": "GuardLens sends each alert here as JSON."},
        "timeout_seconds": {"type": "float", "default": 5, "min": 1, "max": 60, "label": "Give up after"},
        "headers": {"type": "object", "default": {}, "label": "Extra headers", "help": "For example an authorization header."},
    }

    def setup(self, config):
        self.url = config["url"]
        if not isinstance(self.url, str) or not self.url.startswith(("http://", "https://")):
            raise ValueError("url must start with http:// or https://")
        self.timeout = float(config.get("timeout_seconds", 5))
        if not 0 < self.timeout <= 30:
            raise ValueError("timeout_seconds must be between 0 and 30")
        self.headers = {str(k): str(v) for k, v in config.get("headers", {}).items()}

    def send(self, event):
        body = json.dumps(event).encode()
        request = Request(self.url, data=body, method="POST", headers={"Content-Type": "application/json", **self.headers})
        with urlopen(request, timeout=self.timeout) as response:
            if response.status >= 400: raise RuntimeError(f"webhook returned {response.status}")
