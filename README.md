# CRE News Tracker

This repo builds and hosts a combined RSS feed (from 6 CRE sites) via GitHub Pages.

## Quick setup
1. Create a new GitHub repo named `cre-news-feed` (or any name).
2. Upload all files from this ZIP.
3. Go to **Settings → Pages** and set **Source = GitHub Actions**.
4. The included workflow will run every 30 minutes and publish `feed.xml` to Pages.
5. Your feed will be available at:
   `https://<your-username>.github.io/cre-news-feed/feed.xml`

## Local test
```bash
pip install -r requirements.txt
python make_feed.py -c sites.yaml -o feed.xml
```

## Customize
- Edit `sites.yaml` to add or tweak sources/selectors.
- Edit `feed.title`/`feed.link` to your preferred branding.