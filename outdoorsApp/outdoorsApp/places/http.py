"""Small JSON-over-HTTP helper shared by the seeder and the weather module."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "UtahWayfinder/0.1 (CrimsonHacks project)"


class SourceError(RuntimeError):
    pass


def request_json(url: str, *, params: dict | None = None, headers: dict | None = None,
                 data: bytes | None = None, retries: int = 3, timeout: int = 120):
    # Keys always go in headers, never the URL, so they can't leak into error messages.
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT, **(headers or {})})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(15 if error.code == 429 else 5 * (attempt + 1))
                continue
            raise SourceError(f"HTTP {error.code} from {url.split('?')[0]}") from None
        except (urllib.error.URLError, TimeoutError) as error:
            if attempt < retries - 1:
                time.sleep(3)
                continue
            raise SourceError(f"Couldn't reach {url.split('?')[0]}: {error}") from None
    raise SourceError("unreachable")
