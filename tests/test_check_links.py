"""check_links.py's parsing and comparing, with a fake network: no request leaves the machine."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_links as cl  # noqa: E402
from check_links import Response  # noqa: E402

ISO = "airux-0.1-amd64.hybrid.iso"
SHA = "636429840a22266d181a941c8aa6d46bb76222aeb393d6a73b0547251718c51c"
ISO_URL = "https://example.org/iso/download"
SUMS_URL = "https://example.org/sums/download"
APK_URL = "https://example.org/app.apk"

DATA = {"products": [
    {"kind": "os", "downloads": [
        {"file": ISO, "url": ISO_URL, "bytes": 4658798592, "sha256": SHA, "primary": True},
        {"file": "SHA256SUMS", "url": SUMS_URL, "primary": False}]},
    {"kind": "app", "downloads": [
        {"file": "app.apk", "url": APK_URL, "bytes": 100, "sha256": "0" * 64, "primary": True}]},
]}


def fake(responses: dict[tuple[str, str], Response], calls: list | None = None):
    def get(url, method, read_body):
        if calls is not None:
            calls.append((url, method))
        return responses.get((url, method), Response(404))
    return get


def site(tmp_path: Path, html: str) -> Path:
    (tmp_path / "index.html").write_text(html, encoding="utf-8")
    return tmp_path


GOOD = {
    (ISO_URL, "HEAD"): Response(200, 4658798592),
    (SUMS_URL, "HEAD"): Response(200, 90),
    (SUMS_URL, "GET"): Response(200, 90, f"{SHA}  {ISO}\n".encode()),
    (APK_URL, "HEAD"): Response(200, 100),
}


def test_all_good(tmp_path):
    dist = site(tmp_path, '<a href="https://ok.example/">x</a><a href="/local/">y</a>')
    resp = {**GOOD, ("https://ok.example/", "HEAD"): Response(200)}
    assert cl.check(DATA, dist, fake(resp), log=lambda s: None) == []


def test_wrong_byte_count_is_reported(tmp_path):
    resp = {**GOOD, (ISO_URL, "HEAD"): Response(200, 4658798591)}
    problems = cl.check(DATA, site(tmp_path, ""), fake(resp), log=lambda s: None)
    assert problems == [f"download {ISO} ({ISO_URL}): Content-Length is 4658798591 bytes, "
                        "site.json says 4658798592"]


def test_download_status_and_missing_length():
    d = {"file": "a.iso", "url": "https://x/a.iso", "bytes": 5}
    assert "expected HTTP 200, got HTTP 404" in cl.download_problems(d, Response(404))[0]
    assert "could not reach it (timed out)" in cl.download_problems(d, Response(0, error="timed out"))[0]
    assert "no Content-Length" in cl.download_problems(d, Response(200, None))[0]
    assert cl.download_problems({"file": "S", "url": "https://x/S"}, Response(200, None)) == []


def test_parse_sha256sums_formats():
    text = f"{SHA}  {ISO}\n{'A' * 64} *build/iso/other.iso\n\nnot a line\n"
    assert cl.parse_sha256sums(text) == {ISO: SHA, "other.iso": "a" * 64}


def test_sums_problems():
    assert cl.sums_problems(f"{SHA}  {ISO}\n", ISO, SHA.upper()) == []
    assert "listed as" in cl.sums_problems(f"{'b' * 64}  {ISO}\n", ISO, SHA)[0]
    assert "is not listed" in cl.sums_problems(f"{SHA}  other.iso\n", ISO, SHA)[0]
    assert "no checksum lines" in cl.sums_problems("<!doctype html><html>", ISO, SHA)[0]


def test_head_refused_falls_back_to_get(tmp_path):
    calls: list = []
    url = "https://nohead.example/"
    resp = {**GOOD, (url, "HEAD"): Response(405), (url, "GET"): Response(200)}
    assert cl.check(DATA, site(tmp_path, f'<a href="{url}">x</a>'), fake(resp, calls), log=lambda s: None) == []
    assert (url, "GET") in calls


def test_broken_link_names_its_page(tmp_path):
    url = "https://gone.example/page"
    resp = {**GOOD, (url, "HEAD"): Response(404)}
    problems = cl.check(DATA, site(tmp_path, f'<img src="{url}">'), fake(resp), log=lambda s: None)
    assert problems == [f"link {url}: HTTP 404 (on index.html)"]


def test_downloads_are_not_fetched_twice_and_http_links_skipped(tmp_path):
    calls: list = []
    html = f'<a href="{ISO_URL}">iso</a><a href="http://plain.example/">p</a><a href="mailto:a@b">m</a>'
    cl.check(DATA, site(tmp_path, html), fake(GOOD, calls), log=lambda s: None)
    assert calls.count((ISO_URL, "HEAD")) == 1
    assert not any("plain.example" in u for u, _ in calls)


def test_empty_dist_is_a_problem(tmp_path):
    problems = cl.check(DATA, tmp_path / "missing", fake(GOOD), log=lambda s: None)
    assert problems == [f"no HTML pages in {tmp_path / 'missing'}: run `python3 build.py` first"]


def test_retry_on_server_error(monkeypatch):
    seq = iter([Response(503), Response(0, error="reset"), Response(200)])
    monkeypatch.setattr(cl, "_once", lambda url, method, read_body: next(seq))
    monkeypatch.setattr(cl.time, "sleep", lambda s: None)
    assert cl.fetch("https://x/").status == 200
    seq2 = iter([Response(404)])
    monkeypatch.setattr(cl, "_once", lambda url, method, read_body: next(seq2))
    assert cl.fetch("https://x/").status == 404   # a 404 is not retried
