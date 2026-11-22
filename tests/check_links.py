#!/usr/bin/env python3
"""Check the site's live links. Standard library only.

    python3 build.py && python3 tests/check_links.py      exit code 1 if anything is wrong

It checks that:
  - every download in site.json answers HTTP 200 after redirects, with a Content-Length equal to
    its "bytes" where site.json gives one;
  - the SHA256SUMS download lists the OS ISO with the sha256 that site.json shows;
  - every external https link in the built dist/**/*.html answers with a status below 400 (HEAD,
    falling back to GET when a server refuses HEAD with 405 or 403).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
USER_AGENT = "link-check/1.0 (Python-urllib)"
TIMEOUT = 30          # seconds per request
ATTEMPTS = 3          # tries per request on network errors, 429 and 5xx
BACKOFF = 2.0         # seconds; doubles after each failed try
SUMS_LIMIT = 1 << 20  # read at most 1 MiB of a checksum file


@dataclass
class Response:
    status: int                  # 0 when the server could not be reached
    length: int | None = None    # Content-Length of the final response, if sent
    body: bytes = b""
    final_url: str = ""
    error: str = ""              # why the server could not be reached


Fetch = Callable[[str, str, bool], Response]   # (url, method, read_body) -> Response


# ---------- network ----------

def _once(url: str, method: str, read_body: bool) -> Response:
    req = urllib.request.Request(url, method=method, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            length = r.headers.get("Content-Length")
            body = r.read(SUMS_LIMIT) if read_body else b""
            return Response(r.status, int(length) if length and length.isdigit() else None, body, r.geturl())
    except urllib.error.HTTPError as e:
        return Response(e.code, final_url=e.geturl() or url)
    except (urllib.error.URLError, OSError) as e:   # DNS, refused, TLS, timeout
        return Response(0, error=str(getattr(e, "reason", e)))


def fetch(url: str, method: str = "HEAD", read_body: bool = False) -> Response:
    """One request with a small retry on network errors, 429 and 5xx."""
    wait = BACKOFF
    for attempt in range(1, ATTEMPTS + 1):
        r = _once(url, method, read_body)
        if not (r.status == 0 or r.status == 429 or r.status >= 500) or attempt == ATTEMPTS:
            return r
        time.sleep(wait)
        wait *= 2
    return r  # unreachable; keeps type checkers calm


def head_or_get(url: str, get: Fetch = fetch) -> Response:
    """HEAD first; GET (without reading the body) when the server refuses HEAD."""
    r = get(url, "HEAD", False)
    if r.status in (403, 405):
        r = get(url, "GET", False)
    return r


# ---------- pure checks (unit-tested without the network) ----------

def describe(r: Response) -> str:
    return f"could not reach it ({r.error})" if r.status == 0 else f"HTTP {r.status}"


def download_problems(d: dict, r: Response) -> list[str]:
    """Problems with one site.json download, given its final response."""
    name = f"{d['file']} ({d['url']})"
    if r.status != 200:
        return [f"download {name}: expected HTTP 200, got {describe(r)}"]
    want = d.get("bytes")
    if want is not None:
        if r.length is None:
            return [f"download {name}: no Content-Length sent, expected {want} bytes"]
        if r.length != want:
            return [f"download {name}: Content-Length is {r.length} bytes, site.json says {want}"]
    return []


def parse_sha256sums(text: str) -> dict[str, str]:
    """`sha256sum` output (`<hash>  <name>` or `<hash> *<name>`) -> {name: hash}. Paths keep only the
    file name, so `build/airux.iso` and `airux.iso` match."""
    sums: dict[str, str] = {}
    for line in text.splitlines():
        m = re.match(r"^\s*([0-9a-fA-F]{64})\s+\*?(.+?)\s*$", line)
        if m:
            sums[m.group(2).replace("\\", "/").rsplit("/", 1)[-1]] = m.group(1).lower()
    return sums


def sums_problems(text: str, file: str, sha256: str) -> list[str]:
    sums = parse_sha256sums(text)
    if not sums:
        return [f"SHA256SUMS: no checksum lines found (is it an HTML page?): {text[:80]!r}"]
    got = sums.get(file)
    if got is None:
        return [f"SHA256SUMS: {file} is not listed (it lists {', '.join(sorted(sums))})"]
    if got != sha256.lower():
        return [f"SHA256SUMS: {file} is listed as {got}, site.json says {sha256.lower()}"]
    return []


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: set[str] = set()

    def handle_starttag(self, tag, attrs):
        for k, v in attrs:
            if k in ("href", "src") and v and v.startswith("https://"):
                self.links.add(v)


def external_links(html: str) -> set[str]:
    p = _Links()
    p.feed(html)
    return p.links


def link_problem(url: str, r: Response, pages: list[str]) -> str | None:
    if 0 < r.status < 400:
        return None
    return f"link {url}: {describe(r)} (on {', '.join(pages)})"


# ---------- the run ----------

def check(data: dict, dist: Path, get: Fetch = fetch, log: Callable[[str], None] = print) -> list[str]:
    problems: list[str] = []
    downloads = [d for p in data["products"] for d in p.get("downloads", [])]

    for d in downloads:
        r = head_or_get(d["url"], get)
        found = download_problems(d, r)
        problems += found
        if not found:
            log(f"ok   download {d['file']}: HTTP 200" + (f", {r.length} bytes" if d.get("bytes") else ""))

    sums = next((d for d in downloads if d["file"] == "SHA256SUMS"), None)
    os_main = next((d for p in data["products"] if p["kind"] == "os" for d in p["downloads"]
                    if d.get("primary")), None)
    if sums and os_main:
        r = get(sums["url"], "GET", True)
        if r.status != 200:
            problems.append(f"SHA256SUMS ({sums['url']}): expected HTTP 200, got {describe(r)}")
        else:
            found = sums_problems(r.body.decode("utf-8", "replace"), os_main["file"], os_main["sha256"])
            problems += found
            if not found:
                log(f"ok   SHA256SUMS lists {os_main['file']} with {os_main['sha256'][:12]}…")
    elif os_main:
        problems.append("site.json: the OS has no SHA256SUMS download to check its hash against")

    html_files = sorted(dist.rglob("*.html")) if dist.is_dir() else []
    if not html_files:
        problems.append(f"no HTML pages in {dist}: run `python3 build.py` first")
    on_pages: dict[str, list[str]] = {}
    for f in html_files:
        for url in external_links(f.read_text(encoding="utf-8")):
            on_pages.setdefault(url, []).append(str(f.relative_to(dist)).replace("\\", "/"))
    checked = {d["url"] for d in downloads}
    for url in sorted(on_pages.keys() - checked):
        r = head_or_get(url, get)
        problem = link_problem(url, r, on_pages[url])
        if problem:
            problems.append(problem)
        else:
            log(f"ok   link {url}: HTTP {r.status}")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--site", type=Path, default=ROOT / "site.json")
    ap.add_argument("--dist", type=Path, default=ROOT / "dist")
    args = ap.parse_args(argv)
    data = json.loads(args.site.read_text(encoding="utf-8"))
    problems = check(data, args.dist)
    for p in problems:
        print(f"FAIL {p}")
    print(f"{len(problems)} problem(s)" if problems else "all links ok")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
