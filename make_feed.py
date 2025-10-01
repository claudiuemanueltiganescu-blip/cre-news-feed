import json
import os
import sys
from datetime import datetime, timezone
from email.utils import format_datetime
from urllib.parse import urljoin

import requests
import yaml
from bs4 import BeautifulSoup
from dateutil import parser as dateparser
from xml.etree.ElementTree import Element, SubElement, ElementTree

DEFAULT_HEADERS = {
    "User-Agent": "CustomFeedBot/1.0 (+https://example.com)"
}

def rfc822(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return format_datetime(dt)

def load_yaml(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def load_state(path: str):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"seen": {}}

def save_state(path: str, state: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def fetch(url: str) -> requests.Response:
    resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=30)
    resp.raise_for_status()
    return resp

def parse_rss(xml_text: str):
    soup = BeautifulSoup(xml_text, "xml")
    items = []
    entries = soup.find_all(["entry", "item"])
    for e in entries:
        title = (e.title or {}).get_text(strip=True) if e.title else None
        link = None
        if e.find("link"):
            link_tag = e.find("link")
            link = link_tag.get("href") or link_tag.get_text(strip=True)
        guid = None
        if e.find("id"):
            guid = e.find("id").get_text(strip=True)
        elif e.find("guid"):
            guid = e.find("guid").get_text(strip=True)
        summary_el = e.find(["summary", "content", "description"])
        summary = summary_el.get_text(" ", strip=True) if summary_el else ""
        date_text = None
        for tag in ["published", "updated", "pubDate", "dc:date", "date"]:
            t = e.find(tag)
            if t and t.get_text(strip=True):
                date_text = t.get_text(strip=True)
                break
        if date_text:
            try:
                dt = dateparser.parse(date_text)
            except Exception:
                dt = datetime.now(timezone.utc)
        else:
            dt = datetime.now(timezone.utc)

        if not link:
            alt = e.find("link", rel="alternate")
            if alt and alt.get("href"):
                link = alt["href"]

        guid = guid or link or (title or "")[:80]
        items.append({
            "title": title or "(untitled)",
            "link": link or "",
            "guid": guid,
            "summary": summary,
            "date": dt,
        })
    return items

def parse_html(url: str, cfg: dict):
    resp = fetch(url)
    soup = BeautifulSoup(resp.text, "lxml")
    list_selector = cfg.get("list_selector")
    if not list_selector:
        raise ValueError("Missing list_selector for HTML source")
    blocks = soup.select(list_selector)
    results = []
    for b in blocks:
        title_el = b.select_one(cfg.get("title_selector")) if cfg.get("title_selector") else None
        title = title_el.get_text(" ", strip=True) if title_el else None

        link_el = b.select_one(cfg.get("link_selector")) if cfg.get("link_selector") else None
        link = None
        if link_el:
            href = link_el.get("href")
            if href:
                link = urljoin(cfg.get("base_url") or url, href)

        desc = ""
        if cfg.get("description_selector"):
            desc_el = b.select_one(cfg["description_selector"])
            if desc_el:
                desc = desc_el.get_text(" ", strip=True)

        dt = None
        if cfg.get("date_selector"):
            date_el = b.select_one(cfg["date_selector"])
            if date_el:
                text = date_el.get(cfg.get("date_attr")) if cfg.get("date_attr") else None
                if not text:
                    text = date_el.get_text(" ", strip=True)
                if text:
                    try:
                        if cfg.get("date_format"):
                            from datetime import datetime as dtmod
                            dt = dtmod.strptime(text, cfg["date_format"])
                        else:
                            dt = dateparser.parse(text)
                    except Exception:
                        dt = None
        if dt is None:
            dt = datetime.now(timezone.utc)

        if not (title or link):
            continue

        guid = link or (title or "")[:80]
        results.append({
            "title": title or "(untitled)",
            "link": link or "",
            "guid": guid,
            "summary": desc,
            "date": dt,
        })
    return results

def build_feed(channel_meta: dict, items: list, out_path: str):
    rss = Element("rss", version="2.0")
    channel = SubElement(rss, "channel")
    for k in ["title", "link", "description", "language", "ttl"]:
        if k in channel_meta:
            el = SubElement(channel, k)
            el.text = str(channel_meta[k])
    last_build_date = SubElement(channel, "lastBuildDate")
    last_build_date.text = rfc822(datetime.now(timezone.utc))

    for it in items:
        item = SubElement(channel, "item")
        t = SubElement(item, "title"); t.text = it["title"]
        l = SubElement(item, "link"); l.text = it["link"]
        g = SubElement(item, "guid"); g.text = it["guid"]
        d = SubElement(item, "description"); d.text = it.get("summary", "")
        pd = SubElement(item, "pubDate"); pd.text = rfc822(it["date"])

    ElementTree(rss).write(out_path, encoding="utf-8", xml_declaration=True)

def main(config_path: str, out_path: str = "feed.xml"):
    cfg = load_yaml(config_path)
    state_path = cfg.get("state_file", "state.json")
    state = load_state(state_path)
    seen = state.get("seen", {})

    all_items = []
    for src in cfg.get("sources", []):
        stype = src.get("type")
        name = src.get("name", "source")
        url = src.get("url")
        try:
            if stype == "rss":
                resp = fetch(url)
                items = parse_rss(resp.text)
            elif stype == "html":
                items = parse_html(url, src)
            else:
                print(f"Skipping {name}: unknown type '{stype}'", file=sys.stderr)
                continue
            for it in items:
                guid = it["guid"]
                if guid not in seen:
                    all_items.append(it)
                    seen[guid] = True
        except Exception as e:
            print(f"[WARN] Failed to process {name} ({url}): {e}", file=sys.stderr)
            continue

    all_items.sort(key=lambda x: x["date"], reverse=True)
    limit = int(cfg.get("limit", 60))
    all_items = all_items[:limit]

    feed_meta = cfg.get("feed", {})
    build_feed(feed_meta, all_items, out_path)

    state["seen"] = seen
    save_state(state_path, state)

    print(f"Wrote {out_path} with {len(all_items)} items.")

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Build a custom RSS feed from mixed sources (RSS + HTML).")
    ap.add_argument("--config", "-c", default="sites.yaml", help="Path to YAML config")
    ap.add_argument("--out", "-o", default="feed.xml", help="Output RSS file path")
    args = ap.parse_args()
    main(args.config, args.out)