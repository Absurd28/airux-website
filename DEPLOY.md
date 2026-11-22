# Putting the AIRUX website online

Everything here is free. Three places hold the pieces:

| What | Where | Cost |
| --- | --- | --- |
| The website | GitHub Pages (`absurd28.github.io/airux-website`), deployed on every push | Free: HTTPS, 100 GB a month |
| The ISO (4.66 GB) and `SHA256SUMS` | SourceForge project `airux` | Free: files up to 10 GB, world mirrors |
| The AIROX Connect APK (61 MB) | GitHub Releases on `Absurd28/AIROX_Connect` | Free |

GitHub Releases can't hold the ISO: each file must be under 2 GiB.

## 1. Put the website's code on GitHub

Create an empty repository `airux-website` on GitHub (no README), then:

```bash
cd ../airux-website
git remote add origin https://github.com/Absurd28/airux-website.git
git push -u origin main
```

## 2. Upload the ISO to SourceForge

1. Make a free account at sourceforge.net, then **Create a Project**. Name: `AIRUX`, URL name `airux`.
2. Make a `SHA256SUMS` that lists the file by its name only, so `sha256sum -c` works for downloaders:

   ```bash
   cd /srv/airux-work/build/iso
   sha256sum airux-0.1-amd64.hybrid.iso > SHA256SUMS.upload
   ```

3. Upload with rsync, which resumes if the connection drops (it asks for your SourceForge password):

   ```bash
   rsync -avP -e ssh airux-0.1-amd64.hybrid.iso <your-sf-user>@frs.sourceforge.net:/home/frs/project/airux/0.1/
   rsync -avP -e ssh SHA256SUMS.upload <your-sf-user>@frs.sourceforge.net:/home/frs/project/airux/0.1/SHA256SUMS
   ```

4. On the project's **Files** page, open the ISO's (i) menu and make it the default download for
   Windows, macOS and Linux.

The site's link is `https://sourceforge.net/projects/airux/files/0.1/airux-0.1-amd64.hybrid.iso/download`.

## 3. Publish the APK on GitHub Releases

```bash
cd ../AIROX_Connect
cp app/build/outputs/apk/debug/app-debug.apk airox-connect-0.1.0.apk
sha256sum airox-connect-0.1.0.apk > airox-connect-0.1.0.apk.sha256
gh release create v0.1.0 airox-connect-0.1.0.apk airox-connect-0.1.0.apk.sha256 \
  --title "AIROX Connect 0.1.0 (preview)" --notes "Preview build, debug-signed."
```

The site shows this APK's SHA-256 (`c34784bc…b82c`); upload exactly that file.

**Release builds.** The APK is debug-signed, so the site labels it a preview. For a proper release,
make your own signing key once and keep it and its passwords to yourself (never in a repository):

```bash
keytool -genkeypair -v -keystore airox-release.jks -alias airox -keyalg RSA -keysize 4096 -validity 10000
```

Then sign `assembleRelease` with it, upload that APK, put its size and SHA-256 in `site.json`, and
remove the `"preview"` line.

## 4. Turn the downloads on

When the ISO and the APK are uploaded, set `"published": true` for each product in `site.json`,
check the links, then push:

```bash
curl -sIL https://sourceforge.net/projects/airux/files/0.1/airux-0.1-amd64.hybrid.iso/download | grep -i "^http\|content-length"
curl -sIL https://github.com/Absurd28/AIROX_Connect/releases/download/v0.1.0/airox-connect-0.1.0.apk | grep -i "^http\|content-length"
python3 build.py && python3 -m pytest -q tests
git commit -am "Downloads are live" && git push
```

Until then the buttons say "Coming soon", so the site never links to a missing file.

## 5. Hosting: GitHub Pages now, Cloudflare Pages optional

The site is live on GitHub Pages: `.github/workflows/github-pages.yml` tests, builds and deploys
on every push to `main`. To move to Cloudflare Pages later (no bandwidth cap, `airux.pages.dev`):

1. Make a free Cloudflare account.
2. **Workers & Pages → Create → Pages → Connect to Git**, pick `Absurd28/airux-website`.
3. Project name `airux` (the address becomes `airux.pages.dev`; if the name is taken, pick another
   and set the same address in `site.json` → `site.url`).
4. Build command `python3 build.py`, output directory `dist`. Save and deploy.

5. Set `site.url` in `site.json` to the new address, and turn off GitHub Pages in the repository's
   **Settings → Pages** (or delete the workflow) so there is one copy of the site.

Cloudflare reads `_headers` (HTTPS-only, a strict content policy, caching); GitHub Pages ignores it.

## 6. A domain of your own, later

Checked on 2026-11-22: `airux.org` and `airox.org` are taken; `airuxos.org`, `airuxos.com`,
`airux.dev`, `airux.io` and `airoxos.org` were free.

- Cheapest to keep: **Cloudflare Registrar** sells at cost, the same price every year (an `.org` is
  about $11 a year, `.dev` about $13–15).
- Then in Cloudflare Pages: **Custom domains → Set up a domain**. Set `site.url` in `site.json` to
  the new address and push.

Free domain names exist but are not dependable for a product: `eu.org` approvals take months, and
`is-a.dev`-style names are for personal developer pages. The free `airux.pages.dev` address is the
better free choice.

## Adding an app

Add an entry to `products` in `site.json` (copy AIROX Connect's), put its screenshots as WebP in
`static/img/<app>/`, run `python3 build.py` and the tests. It appears on the Apps page, the home
page and at `/apps/<id>/`.

## CI/CD

| Workflow | Runs when | What it does |
| --- | --- | --- |
| `github-pages.yml` | every push to `main`, or **Run workflow** | runs the tests, builds, deploys to GitHub Pages; a failing test stops the deploy |
| `links.yml` | Mondays 06:00 UTC, or **Run workflow** | builds, then `tests/check_links.py`: every download answers 200 with the size in `site.json`, `SHA256SUMS` lists the ISO's hash, no external link is broken. Read-only; deploys nothing |
| Dependabot (`.github/dependabot.yml`) | monthly | opens a pull request when an action in the workflows has a new version |

Run the link check yourself before changing a download:

```bash
python3 build.py && python3 tests/check_links.py    # exit code 1 and a FAIL line per problem
```

GitHub sends scheduled-workflow notifications to whoever last changed the workflow's `cron` line.

**Scheduled runs stop after 60 days without commits.** In a public repository GitHub disables a
scheduled workflow when the repository has had no activity, such as commits, for 60 days. A later
push does not turn it back on. To re-enable it: **Actions** tab → **Link check** in the list on
the left → **Enable workflow** (or `gh workflow enable links.yml`).
