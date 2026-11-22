"""The site builds, every internal link and image resolves, downloads are honest."""
from __future__ import annotations

import copy
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import build  # noqa: E402


class Refs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.refs: list[str] = []
        self.ids: set[str] = set()

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.add(a["id"])
        for k in ("href", "src"):
            if a.get(k):
                self.refs.append(a[k])


@pytest.fixture(scope="module")
def dist():
    return build.build("/")


def pages(dist):
    return sorted(dist.rglob("*.html"))


def parse(p: Path) -> Refs:
    r = Refs()
    r.feed(p.read_text(encoding="utf-8"))
    return r


def resolve(dist: Path, page: Path, ref: str) -> Path:
    path = ref.split("#")[0].split("?")[0]
    target = dist / path.lstrip("/") if path.startswith("/") else page.parent / path
    return target / "index.html" if (path.endswith("/") or target.is_dir()) else target


def test_all_pages_built(dist):
    rel = {str(p.relative_to(dist)).replace("\\", "/") for p in pages(dist)}
    assert {"index.html", "download/index.html", "usb/index.html", "apps/index.html",
            "apps/airox-connect/index.html", "404.html"} <= rel


def test_internal_links_and_images_resolve(dist):
    for page in pages(dist):
        r = parse(page)
        for ref in r.refs:
            if re.match(r"^(https?:|mailto:)", ref):
                continue
            if ref.startswith("#"):
                assert ref[1:] in r.ids, f"{page}: missing anchor {ref}"
                continue
            assert resolve(dist, page, ref).exists(), f"{page}: broken link {ref}"


def test_no_plain_http_links(dist):
    for page in pages(dist):
        for ref in parse(page).refs:
            assert not ref.startswith("http://"), f"{page}: insecure link {ref}"


def test_download_pages_show_size_and_hash(dist):
    data = json.loads((ROOT / "site.json").read_text(encoding="utf-8"))
    for p in data["products"]:
        page = dist / ("download" if p["kind"] == "os" else f"apps/{p['id']}") / "index.html"
        text = page.read_text(encoding="utf-8")
        main = next(d for d in p["downloads"] if d.get("primary"))
        assert main["sha256"] in text
        assert build.size_text(main["bytes"]) in text
        # unpublished products must not link to the file yet
        assert (main["url"] in text) == bool(p.get("published"))


def test_size_text():
    assert build.size_text(4658798592) == "4.66 GB"
    assert build.size_text(61159165) == "61.2 MB"


def test_validate_rejects_bad_products():
    data = json.loads((ROOT / "site.json").read_text(encoding="utf-8"))
    bad = copy.deepcopy(data)
    bad["products"][0]["downloads"][0]["url"] = "http://example.com/x.iso"
    with pytest.raises(build.SiteError):
        build.validate(bad)
    bad = copy.deepcopy(data)
    bad["products"][1]["downloads"][0]["sha256"] = "abc"
    with pytest.raises(build.SiteError):
        build.validate(bad)
    bad = copy.deepcopy(data)
    bad["products"][1]["screenshots"].append(["img/nope.webp", "missing"])
    with pytest.raises(build.SiteError):
        build.validate(bad)


def test_base_path_for_github_pages():
    out = build.build("/airux-website/")
    home = (out / "index.html").read_text(encoding="utf-8")
    assert 'href="/airux-website/download/"' in home
    assert 'src="/airux-website/static/' in home
    build.build("/")


def test_old_address_forwards_every_page():
    site = json.loads((ROOT / "site.json").read_text(encoding="utf-8"))["site"]["url"].rstrip("/")
    real = {str(p.relative_to(build.build("/"))).replace("\\", "/") for p in build.DIST.rglob("index.html")}
    out = build.build_redirect("/airux-website/")
    try:
        moved = {str(p.relative_to(out)).replace("\\", "/") for p in out.rglob("index.html")}
        assert moved == real                          # every page of the real site has a forward
        assert not (out / "static").exists()          # and nothing else is published there
        usb = (out / "usb" / "index.html").read_text(encoding="utf-8")
        assert f'url={site}/usb/"' in usb and f'rel="canonical" href="{site}/usb/"' in usb
        assert "location.hash" in usb                 # /usb/#windows keeps its #windows
        home = (out / "index.html").read_text(encoding="utf-8")
        assert f'url={site}/"' in home
        nf = (out / "404.html").read_text(encoding="utf-8")
        assert 'b = "/airux-website/"' in nf and f'"{site}"' in nf
    finally:
        build.build("/")
