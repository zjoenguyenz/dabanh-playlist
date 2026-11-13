#!/usr/bin/env python3
"""Best-effort scraper for the xoilac / 90phut / socolive site family.

Each site lists today's matches on /truc-tiep/<slug>/ pages. A match
page embeds a streamData JSON with "playerHost" plus a match_id in an
inline script; the playable URL is

    <playerHost>/default/<match_id>.m3u8

— the exact URL the site's own web player builds. This script emits
extra M3U entries grouped per site, which the mirror workflow appends
to the main playlist.

Failure policy: any error (site down, layout changed, zero matches)
yields zero entries for that site and never raises — the main mirror
must never depend on this script.
"""
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    )
}

SITES = [
    ("Xoilac365", "https://xoilac365j.mobi"),
    ("90Phut", "https://90phutzbi.tv"),
    ("Xoilac3", "https://xoilac3.me"),
    ("Xoilac86", "https://xoilac86tv.club"),
    ("Socolive", "https://socolivezas.tv"),
    ("TructiepBongDa", "https://tructiepbongda.name"),
]

MAX_MATCHES_PER_SITE = 30
TIMEOUT = 20
ICT = timezone(timedelta(hours=7))

LINK_RE = re.compile(r'href="((?:https?://[^"/]+)?/truc-tiep/[^"?#]+/)"')
HOST_RE = re.compile(r'"playerHost"\s*:\s*"([^"]+)"')
MID_RE = re.compile(r"match_id\s*=\s*'([A-Za-z0-9]+)'")
MTIME_RE = re.compile(r'"matchTime"\s*:\s*(\d{9,11})')


def fetch(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read().decode("utf-8", "ignore")


def title_from(url, html):
    """Build the app's 'HH:MM DD/MM ⚽ Team A vs Team B' title format.

    Kickoff comes from streamData.matchTime (epoch) when present, else
    from the slug (-luc-HHMM-ngay-DD-MM-YYYY or a trailing -DD-MM-YYYY).
    """
    slug = url.rstrip("/").split("/truc-tiep/")[-1]
    kick = ""
    m = re.search(r"-luc-(\d{2})(\d{2})-ngay-(\d{2})-(\d{2})-(\d{4})$", slug)
    if m:
        kick = f"{m.group(1)}:{m.group(2)} {m.group(3)}/{m.group(4)}"
        core = slug[: m.start()]
    else:
        m = re.search(r"-(\d{2})-(\d{2})-(\d{4})$", slug)
        core = slug[: m.start()] if m else slug
    mt = MTIME_RE.search(html)
    if mt:
        dt = datetime.fromtimestamp(int(mt.group(1)), tz=ICT)
        kick = dt.strftime("%H:%M %d/%m")
    title = core.replace("-", " ").strip().title()
    return f"{kick} ⚽ {title}".strip() if kick else f"⚽ {title}"


def scrape_match(url):
    """Return (title, stream_url) for one match page, or None."""
    try:
        html = fetch(url)
    except Exception:
        return None
    host = HOST_RE.search(html)
    mid = MID_RE.search(html)
    if not host or not mid:
        return None
    host = host.group(1).replace("\\/", "/").rstrip("/")
    stream = f"{host}/default/{mid.group(1)}.m3u8"
    return title_from(url, html), stream


def scrape_site(name, base):
    # Match links live both on the homepage and on the /truc-tiep/
    # index; which one carries them differs per site in this family.
    links = []
    seen = set()
    for page in (base + "/", base + "/truc-tiep/"):
        try:
            html = fetch(page)
        except Exception as exc:
            print(f"[{name}] {page} failed: {exc}", file=sys.stderr)
            continue
        for raw in LINK_RE.findall(html):
            url = raw if raw.startswith("http") else base + raw
            if url not in seen:
                seen.add(url)
                links.append(url)
    links = links[:MAX_MATCHES_PER_SITE]
    entries = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        for result in pool.map(scrape_match, links):
            if result:
                entries.append(result)
    print(f"[{name}] {len(entries)}/{len(links)} match pages yielded streams", file=sys.stderr)
    return entries


def main():
    out = []
    seen_streams = set()
    for name, base in SITES:
        for title, stream in scrape_site(name, base):
            if stream in seen_streams:
                continue  # sister sites carry identical schedules/streams
            seen_streams.add(stream)
            out.append(f'#EXTINF:-1 group-title="{name}",{title}')
            out.append(stream)
    sys.stdout.write("\n".join(out) + ("\n" if out else ""))
    print(f"Total extra entries: {len(out) // 2}", file=sys.stderr)


if __name__ == "__main__":
    main()
