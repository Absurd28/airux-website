# AIRUX website

The download site for [AIRUX](https://github.com/Absurd28/AIRUX_OS) and its apps: download the OS,
check it, write it to a USB stick, and get apps such as AIROX Connect. Live at
**[airux-os.pages.dev](https://airux-os.pages.dev/)**.

Plain static pages built by one standard-library Python script. No framework, no tracking, no
cookies, no third-party scripts or fonts; light and dark themes; it works without JavaScript.

```bash
python3 build.py                      # -> dist/
python3 -m http.server -d dist 8765   # preview at http://127.0.0.1:8765/
python3 -m pytest -q tests            # links, images, hashes, https-only
```

- `site.json`: the OS and every app (versions, downloads with size and SHA-256, screenshots).
- `templates/`: the page frame and the USB guide. `static/`: CSS, JS, logo, screenshots.
- A product with `"published": false` shows "Coming soon" instead of download links.

Putting it online (free hosting, uploads, a domain later): see [DEPLOY.md](DEPLOY.md).

Licence: MIT, like AIRUX.
