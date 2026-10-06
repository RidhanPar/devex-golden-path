"""Minimal read-only GitHub REST client: standard library only, paginated, rate-limit aware."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from typing import Any

API = "https://api.github.com"
_NEXT = re.compile(r'<([^>]+)>;\s*rel="next"')


def token_from_env() -> str | None:
    """GITHUB_TOKEN / GH_TOKEN, else the GitHub CLI's token, else anonymous (60 req/hour)."""
    for name in ("GITHUB_TOKEN", "GH_TOKEN"):
        if os.environ.get(name):
            return os.environ[name]
    gh = shutil.which("gh")
    if gh:
        result = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [gh, "auth", "token"], capture_output=True, text=True, check=False
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    return None


class GitHub:
    def __init__(self, token: str | None) -> None:
        self.headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "devex-golden-path-dora",
        }
        if token:
            self.headers["Authorization"] = f"Bearer {token}"
        self.calls = 0

    def _request(self, url: str) -> tuple[Any, str | None]:
        if not url.startswith(API + "/"):
            raise ValueError(f"refusing non-GitHub URL: {url}")
        for attempt in range(4):
            request = urllib.request.Request(url, headers=self.headers)  # noqa: S310 - https only
            try:
                with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
                    self.calls += 1
                    link = response.headers.get("Link", "")
                    match = _NEXT.search(link)
                    return json.load(response), match.group(1) if match else None
            except urllib.error.HTTPError as err:
                self.calls += 1
                if err.code in (404, 409):  # missing, or an empty repository
                    return None, None
                if err.code in (403, 429) and err.headers.get("X-RateLimit-Remaining") == "0":
                    reset = int(err.headers.get("X-RateLimit-Reset", "0"))
                    time.sleep(min(max(reset - time.time(), 1), 900))
                    continue
                if err.code >= 500 and attempt < 3:
                    time.sleep(2**attempt)
                    continue
                raise
        raise RuntimeError(f"giving up on {url}")

    def get(self, path: str) -> Any:
        data, _ = self._request(f"{API}/{path.lstrip('/')}")
        return data

    def paginate(self, path: str, key: str | None = None, limit: int = 1000) -> list[Any]:
        """All items of a list endpoint (or of `key` in a wrapped list), up to `limit`."""
        sep = "&" if "?" in path else "?"
        url: str | None = f"{API}/{path.lstrip('/')}{sep}per_page=100"
        items: list[Any] = []
        while url and len(items) < limit:
            data, url = self._request(url)
            if data is None:
                break
            items.extend(data[key] if key else data)
        return items[:limit]
