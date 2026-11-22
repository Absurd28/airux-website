#!/usr/bin/env python3
"""Build the AIRUX website into dist/ from site.json, templates/ and static/. Standard library only.

    python3 build.py                 the site at the domain root (Cloudflare Pages: airux-os.pages.dev)
    SITE_BASE=/airux-website/ python3 build.py --redirect
                                     the old GitHub Pages address: every page forwards to the
                                     same page at site.json's "url"

Products (the OS and each app) live in site.json; adding an app is one entry there plus its
screenshots in static/img/. A product with "published": false shows "Coming soon" instead of
download buttons, so the site never links to a file that is not uploaded yet.
"""
from __future__ import annotations

import html
import json
import os
import re
import shutil
import struct
import sys
from pathlib import Path
from string import Template

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
VERSION = "2"            # cache-buster for style.css and site.js; bump when they change


class SiteError(Exception):
    pass


def esc(s: str) -> str:
    return html.escape(str(s), quote=True)


def size_text(n: int) -> str:
    """Decimal units, like download sites and file managers on the web: 4658798592 -> 4.66 GB."""
    for unit, f in (("GB", 1e9), ("MB", 1e6), ("KB", 1e3)):
        if n >= f:
            return f"{n / f:.2f} {unit}" if unit == "GB" else f"{n / f:.1f} {unit}"
    return f"{n} bytes"


def webp_size(path: Path) -> tuple[int, int]:
    """Width and height of a WebP file (VP8X, VP8 or VP8L), so <img> gets its size and pages don't jump."""
    b = path.read_bytes()[:40]
    if b[:4] != b"RIFF" or b[8:12] != b"WEBP":
        raise SiteError(f"{path} is not a WebP file")
    chunk = b[12:16]
    if chunk == b"VP8X":
        w = int.from_bytes(b[24:27], "little") + 1
        h = int.from_bytes(b[27:30], "little") + 1
    elif chunk == b"VP8 ":
        w, h = struct.unpack("<HH", b[26:30])
        w, h = w & 0x3FFF, h & 0x3FFF
    elif chunk == b"VP8L":
        bits = int.from_bytes(b[21:25], "little")
        w, h = (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    else:
        raise SiteError(f"{path}: unknown WebP chunk {chunk!r}")
    return w, h


# ---------------------------------------------------------------------------------- checks
def validate(data: dict) -> None:
    seen = set()
    for p in data["products"]:
        pid = p["id"]
        if not re.fullmatch(r"[a-z0-9-]+", pid) or pid in seen:
            raise SiteError(f"bad or repeated product id {pid!r}")
        seen.add(pid)
        for k in ("name", "version", "kind", "tagline", "summary", "downloads", "features", "screenshots"):
            if k not in p:
                raise SiteError(f"{pid}: missing {k}")
        if not any(d.get("primary") for d in p["downloads"]):
            raise SiteError(f"{pid}: no primary download")
        for d in p["downloads"]:
            if not d["url"].startswith("https://"):
                raise SiteError(f"{pid}: download URL must be https: {d['url']}")
            if d.get("primary"):
                if not re.fullmatch(r"[0-9a-f]{64}", d.get("sha256", "")):
                    raise SiteError(f"{pid}: primary download needs a SHA-256")
                if not isinstance(d.get("bytes"), int) or d["bytes"] <= 0:
                    raise SiteError(f"{pid}: primary download needs its size in bytes")
        for src, alt in p["screenshots"]:
            if not (ROOT / "static" / src).is_file():
                raise SiteError(f"{pid}: screenshot {src} is missing")
            if not alt.strip():
                raise SiteError(f"{pid}: screenshot {src} needs a description")
    if not any(p["kind"] == "os" for p in data["products"]):
        raise SiteError("site.json needs the OS product")


# ---------------------------------------------------------------------------------- pieces
class Site:
    def __init__(self, data: dict, base: str):
        self.data, self.s, self.base = data, data["site"], base
        self.base_tpl = Template((ROOT / "templates" / "base.html").read_text(encoding="utf-8"))
        self.os = next(p for p in data["products"] if p["kind"] == "os")
        self.apps = [p for p in data["products"] if p["kind"] != "os"]
        self.pages: list[str] = []

    def url(self, path: str) -> str:
        return self.base + path.lstrip("/")

    def write(self, path: str, title: str, description: str, content: str, nav: str = "") -> None:
        out = DIST / path / "index.html" if not path.endswith(".html") else DIST / path
        out.parent.mkdir(parents=True, exist_ok=True)
        full_title = title if title.startswith("AIRUX") else f"{title} · AIRUX"
        page = self.base_tpl.substitute(
            title=esc(full_title), description=esc(description), base=self.base, version=VERSION,
            canonical=esc(self.s["url"].rstrip("/") + "/" + (path if not path.endswith(".html") else "")),
            og_image=esc(self.s["url"].rstrip("/") + "/static/img/og.png"),
            github=esc(self.s["github"]), license=esc(self.s["license"]),
            licenses_url=esc(self.s["licenses_url"]), known_issues_url=esc(self.s["known_issues_url"]),
            nav_download=' aria-current="page"' if nav == "download" else "",
            nav_usb=' aria-current="page"' if nav == "usb" else "",
            nav_apps=' aria-current="page"' if nav == "apps" else "",
            content=content)
        out.write_text(page, encoding="utf-8", newline="\n")
        if not path.endswith(".html"):
            self.pages.append(path)

    def img(self, src: str, alt: str, cls: str = "", lazy: bool = True) -> str:
        w, h = webp_size(ROOT / "static" / src)
        attrs = ' loading="lazy"' if lazy else ""
        if cls:
            attrs += f' class="{cls}"'
        return (f'<img src="{self.url("static/" + src)}" alt="{esc(alt)}" width="{w}" height="{h}"'
                f'{attrs} decoding="async">')

    def gallery(self, p: dict, limit: int | None = None) -> str:
        shots = p["screenshots"][:limit] if limit else p["screenshots"]
        figs = "".join(
            f'<figure><a href="{self.url("static/" + src)}">{self.img(src, alt)}</a>'
            f"<figcaption>{esc(alt)}</figcaption></figure>" for src, alt in shots)
        return f'<div class="gallery{" phone" if p["kind"] == "app" else ""}">{figs}</div>'

    def features(self, p: dict) -> str:
        cards = "".join(f'<div class="card"><h3>{esc(t)}</h3><p>{esc(d)}</p></div>' for t, d in p["features"])
        return f'<div class="grid">{cards}</div>'

    def download_box(self, p: dict) -> str:
        main = next(d for d in p["downloads"] if d.get("primary"))
        others = [d for d in p["downloads"] if not d.get("primary")]
        meta = (f'<dl class="meta"><div><dt>File</dt><dd><code>{esc(main["file"])}</code></dd></div>'
                f'<div><dt>Size</dt><dd>{size_text(main["bytes"])}</dd></div>'
                f'<div><dt>Version</dt><dd>{esc(p["version"])} · {esc(p.get("released", ""))}</dd></div></dl>'
                f'<div class="hash"><span class="label">SHA-256</span>'
                f'<code class="sha" data-copy-text="{esc(main["sha256"])}">{esc(main["sha256"])}</code>'
                f'<button class="copy" type="button" data-copy>Copy</button></div>')
        if p.get("published"):
            btn = (f'<a class="btn primary big" href="{esc(main["url"])}" rel="noopener">{esc(main["label"])}'
                   f' <span class="btn-sub">{size_text(main["bytes"])}</span></a>')
            extra = "".join(f'<li><a href="{esc(d["url"])}" rel="noopener">{esc(d["label"])}</a></li>' for d in others)
            extra = f'<ul class="also">{extra}</ul>' if extra else ""
        else:
            btn = ('<span class="btn primary big disabled" aria-disabled="true">Coming soon'
                   ' <span class="btn-sub">the download is being uploaded</span></span>')
            extra = ""
        note = f'<p class="preview-note">{esc(p["preview"])}</p>' if p.get("preview") else ""
        return f'<div class="dl-box">{btn}{extra}{note}{meta}</div>'

    def bullets(self, items: list[str], cls: str = "ticks") -> str:
        return f'<ul class="{cls}">' + "".join(f"<li>{esc(i)}</li>" for i in items) + "</ul>"

    def app_card(self, p: dict) -> str:
        where = "Operating system" if p["kind"] == "os" else p.get("platform", "App")
        href = self.url("download/") if p["kind"] == "os" else self.url(f"apps/{p['id']}/")
        status = "" if p.get("published") else '<span class="pill">Coming soon</span>'
        return (f'<a class="app-card" href="{href}"><img src="{self.url("static/" + p["icon"])}" alt="" width="56" height="56">'
                f'<div><h3>{esc(p["name"])} {status}</h3><p class="muted">{esc(where)} · version {esc(p["version"])}</p>'
                f'<p>{esc(p["tagline"])}</p></div></a>')

    # ------------------------------------------------------------------------------ pages
    def home(self) -> None:
        o = self.os
        main = next(d for d in o["downloads"] if d.get("primary"))
        cta = (f'<a class="btn primary big" href="{self.url("download/")}">Download AIRUX {esc(o["version"])}'
               f' <span class="btn-sub">{size_text(main["bytes"])} · 64-bit PC</span></a>')
        content = f"""
<section class="hero">
  <div class="wrap hero-in">
    <div class="hero-text">
      <p class="eyebrow">Free and open source · Debian 13</p>
      <h1>Your computer, with an assistant that <span class="grad">won't make things up</span>.</h1>
      <p class="lead">{esc(self.s["tagline"])}</p>
      <div class="cta">{cta}<a class="btn ghost big" href="{self.url("usb/")}">How to make a USB</a></div>
      <p class="muted small">Everything runs on your PC: the language model, speech, voice and memory.</p>
    </div>
    <div class="hero-shot">{self.img(o["screenshots"][0][0], o["screenshots"][0][1], "shot", lazy=False)}</div>
  </div>
</section>

<section class="wrap section">
  <h2>What is AIRUX?</h2>
  <p class="lead narrow">{esc(o["summary"])}</p>
  {self.features(o)}
</section>

<section class="wrap section">
  <h2>See it</h2>
  {self.gallery(o, 6)}
  <p><a href="{self.url("download/")}#screenshots">More screenshots</a></p>
</section>

<section class="wrap section">
  <h2>Get started in three steps</h2>
  <ol class="three">
    <li><a href="{self.url("download/")}"><b>Download</b><span>the ISO ({size_text(main["bytes"])}) and check it.</span></a></li>
    <li><a href="{self.url("usb/")}"><b>Make a USB</b><span>with Rufus, balenaEtcher or dd.</span></a></li>
    <li><a href="{self.url("usb/")}#boot"><b>Start from it</b><span>try AIRUX live, install if you like it.</span></a></li>
  </ol>
</section>

<section class="wrap section">
  <h2>Apps for AIRUX</h2>
  <div class="apps">{"".join(self.app_card(p) for p in self.apps)}</div>
  <p><a href="{self.url("apps/")}">All apps</a></p>
</section>
"""
        self.write("", "AIRUX: the OS with a local assistant that won't make things up",
                   self.s["tagline"], content)

    def download(self) -> None:
        o = self.os
        main = next(d for d in o["downloads"] if d.get("primary"))
        f = esc(main["file"])
        content = f"""
<section class="page-head wrap">
  <p class="eyebrow">Step 1 of 3</p>
  <h1>Download AIRUX {esc(o["version"])}</h1>
  <p class="lead">{esc(o["tagline"])}</p>
</section>
<section class="wrap two">
  <div>{self.download_box(o)}</div>
  <div>
    <h2 class="h3">What you need</h2>
    {self.bullets(o["requirements"])}
    <h2 class="h3">Good to know</h2>
    {self.bullets(o["notes"], "plain")}
  </div>
</section>

<section class="wrap section">
  <h2 id="verify">Check the download</h2>
  <p>Compare the file's SHA-256 with the one above. If they differ, the download is broken: download it again.</p>
  <div class="tabs" data-tabs>
    <div class="tablist" role="tablist" aria-label="Your system">
      <button role="tab" id="vt-windows" aria-controls="v-windows" data-os="windows">Windows</button>
      <button role="tab" id="vt-macos" aria-controls="v-macos" data-os="macos">macOS</button>
      <button role="tab" id="vt-linux" aria-controls="v-linux" data-os="linux">Linux</button>
    </div>
    <section class="tabpanel" id="v-windows" role="tabpanel" aria-labelledby="vt-windows"><h3 class="tab-title">Windows (PowerShell)</h3>
      <div class="code"><pre><code>Get-FileHash .\\{f} -Algorithm SHA256</code></pre><button class="copy" type="button" data-copy>Copy</button></div></section>
    <section class="tabpanel" id="v-macos" role="tabpanel" aria-labelledby="vt-macos"><h3 class="tab-title">macOS (Terminal)</h3>
      <div class="code"><pre><code>shasum -a 256 {f}</code></pre><button class="copy" type="button" data-copy>Copy</button></div></section>
    <section class="tabpanel" id="v-linux" role="tabpanel" aria-labelledby="vt-linux"><h3 class="tab-title">Linux</h3>
      <div class="code"><pre><code>sha256sum {f}</code></pre><button class="copy" type="button" data-copy>Copy</button></div></section>
  </div>
  <div class="next"><a class="btn primary" href="{self.url("usb/")}">Next: make a bootable USB →</a></div>
</section>

<section class="wrap section">
  <h2 id="screenshots">Screenshots</h2>
  {self.gallery(o)}
</section>
"""
        self.write("download/", f"Download AIRUX {o['version']}",
                   f"Download the AIRUX {o['version']} ISO ({size_text(main['bytes'])}) for 64-bit PCs, check it and write it to a USB stick.",
                   content, "download")

    def usb(self) -> None:
        main = next(d for d in self.os["downloads"] if d.get("primary"))
        body = Template((ROOT / "templates" / "usb.html").read_text(encoding="utf-8")).substitute(
            base=self.base, iso_file=esc(main["file"]), github=esc(self.s["github"]),
            known_issues_url=esc(self.s["known_issues_url"]))
        self.write("usb/", "Make a bootable USB stick",
                   "Write the AIRUX ISO to a USB stick on Windows, macOS or Linux, start your PC from it, try AIRA and install.",
                   body, "usb")

    def apps_page(self) -> None:
        cards = "".join(self.app_card(p) for p in [self.os] + self.apps)
        content = f"""
<section class="page-head wrap">
  <h1>AIRUX and its apps</h1>
  <p class="lead">Everything we make, in one place. More apps are on the way.</p>
</section>
<section class="wrap"><div class="apps">{cards}</div></section>
"""
        self.write("apps/", "Apps", "AIRUX and the apps made for it, such as AIROX Connect for Android.", content, "apps")

    def app_page(self, p: dict) -> None:
        install = ""
        if p.get("install"):
            install = ('<h2>Install and pair</h2><ol class="steps">'
                       + "".join(f"<li>{esc(s)}</li>" for s in p["install"]) + "</ol>")
        content = f"""
<section class="page-head wrap">
  <p class="eyebrow">{esc(p.get("platform", "App"))} app</p>
  <h1>{esc(p["name"])}</h1>
  <p class="lead">{esc(p["tagline"])}</p>
</section>
<section class="wrap two">
  <div>{self.download_box(p)}</div>
  <div>
    <p>{esc(p["summary"])}</p>
    <h2 class="h3">What you need</h2>
    {self.bullets(p.get("requirements", []))}
    <p><a href="{esc(p["repo"])}" rel="noopener">Source code on GitHub</a></p>
  </div>
</section>
<section class="wrap section">{self.features(p)}</section>
<section class="wrap section">{install}</section>
<section class="wrap section"><h2>Screenshots</h2>{self.gallery(p)}</section>
"""
        self.write(f"apps/{p['id']}/", p["name"], p["tagline"], content, "apps")

    def not_found(self) -> None:
        content = f"""
<section class="page-head wrap center">
  <h1>Page not found</h1>
  <p class="lead">That page doesn't exist. AIRA would say "I'm not sure", and so do we.</p>
  <p><a class="btn primary" href="{self.base}">Go to the home page</a></p>
</section>
"""
        self.write("404.html", "Page not found", "This page does not exist.", content)

    def extras(self) -> None:
        site_url = self.s["url"].rstrip("/")
        urls = "".join(f"<url><loc>{esc(site_url + '/' + p)}</loc></url>" for p in self.pages)
        (DIST / "sitemap.xml").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>\n', encoding="utf-8")
        (DIST / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {site_url}/sitemap.xml\n", encoding="utf-8")
        shutil.copy(ROOT / "_headers", DIST / "_headers")


def build(base: str = "/") -> Path:
    data = json.loads((ROOT / "site.json").read_text(encoding="utf-8"))
    validate(data)
    if DIST.exists():
        shutil.rmtree(DIST)
    shutil.copytree(ROOT / "static", DIST / "static")
    site = Site(data, base if base.endswith("/") else base + "/")
    site.home()
    site.download()
    site.usb()
    site.apps_page()
    for p in site.apps:
        site.app_page(p)
    site.not_found()
    site.extras()
    return DIST


MOVED = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>The AIRUX website has moved</title>
<meta name="robots" content="noindex">
<link rel="canonical" href="$to">
<meta http-equiv="refresh" content="0; url=$to">
$script</head>
<body>
<p>The AIRUX website has moved to <a href="$to">$to</a>.</p>
</body>
</html>
"""

# For links to pages that no longer exist: keep the path, so /usb/#windows lands on /usb/#windows.
FORWARD = """<script>
var p = location.pathname, b = $base;
if (p.indexOf(b) === 0) p = "/" + p.slice(b.length);
location.replace($site + p + location.search + location.hash);
</script>
"""


def build_redirect(base: str) -> Path:
    """The site's old address after a move: each page of the real site becomes a page that sends
    the visitor to the same page at site.json's "url", and 404.html forwards anything else."""
    site_url = json.loads((ROOT / "site.json").read_text(encoding="utf-8"))["site"]["url"].rstrip("/")
    real = build("/")
    pages = sorted(str(p.parent.relative_to(real)).replace("\\", "/") for p in real.rglob("index.html"))
    shutil.rmtree(DIST)
    tpl = Template(MOVED)
    for rel in pages:
        to = site_url + "/" + ("" if rel == "." else rel + "/")
        out = DIST / ("" if rel == "." else rel) / "index.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(tpl.substitute(to=esc(to), script=""), encoding="utf-8", newline="\n")
    script = Template(FORWARD).substitute(base=json.dumps(base), site=json.dumps(site_url))
    (DIST / "404.html").write_text(tpl.substitute(to=esc(site_url + "/"), script=script),
                                   encoding="utf-8", newline="\n")
    (DIST / "robots.txt").write_text("User-agent: *\nAllow: /\n", encoding="utf-8")
    return DIST


if __name__ == "__main__":
    base = os.environ.get("SITE_BASE", "/")
    base = base if base.endswith("/") else base + "/"
    try:
        out = build_redirect(base) if "--redirect" in sys.argv[1:] else build(base)
    except SiteError as e:
        sys.exit(f"build failed: {e}")
    n = sum(1 for _ in out.rglob("*.html"))
    print(f"built {n} {'redirect ' if '--redirect' in sys.argv[1:] else ''}pages into {out}")
