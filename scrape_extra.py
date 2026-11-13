#!/usr/bin/env python3
"""Best-effort scraper for the xoilac / 90phut / socolive site family.

Two stream mechanisms exist in this family (both found live 2026-11-12):

A) list_stream (xoilac365, 90phut, xoilac86, socolive): the match page
   carries a JS array `list_stream` of player-page URLs on a per-site
   host (e.g. https://xl365.domainkqt.cc/ajax/chanel/type/8/link/...).
   Each player page embeds exactly one direct stream URL (.flv).

B) inplyr (xoilac3, tructiepbongda): the match page embeds JSON
   `streamData` with "playerHost" plus an inline `match_id`; the
   stream URL is <playerHost>/default/<match_id>.m3u8.

Output: extra M3U entries on stdout, one group per site. Any failure
anywhere yields fewer entries, never an exception — the mirror's main
source must stay unaffected.
"""
import concurrent.futures
import datetime
import re
import sys
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
ICT = datetime.timezone(datetime.timedelta(hours=7))

SITES = [
    ("Xoilac365", "https://xoilac365j.mobi"),
    ("90Phut", "https://90phutzbi.tv"),
    ("Xoilac3", "https://xoilac3.me"),
    ("Xoilac86", "https://xoilac86tv.club"),
    ("Socolive", "https://socolivezas.tv"),
    ("TructiepBongDa", "https://tructiepbongda.name"),
]

LINK_RE = re.compile(r'href="((?:https?://[^"/]+)?/truc-tiep/[^"?#]+/)"')
LIST_STREAM_RE = re.compile(r"list_stream\s*=\s*\[(.*?)\];", re.S)
STREAM_PAGE_RE = re.compile(r'https?:\\?/\\?/[^\s"\'\\]+')
DIRECT_STREAM_RE = re.compile(r'https?://[^\s"\'<>]+\.(?:flv|m3u8)(?:\?[^\s"\'<>]*)?')
HOST_RE = re.compile(r'"playerHost"\s*:\s*"(https?://[^"]+)"')
MID_RE = re.compile(r"match_id\s*=\s*'([A-Za-z0-9]+)'")
TIME_RE = re.compile(r'"matchTime"\s*:\s*(\d{10})')
SLUG_DATE_RE = re.compile(r"-(\d{2})-(\d{2})-(\d{4})/?$")
SLUG_LUC_RE = re.compile(
    r"^(.*?)-luc-(\d{2})(\d{2})-ngay-(\d{2})-(\d{2})-(\d{4})/?$")
MAX_MATCHES_PER_SITE = 30


def fetch(url, referer=None):
    headers = {"User-Agent": UA}
    if referer:
        headers["Referer"] = referer
    last_exc = None
    for attempt in range(2):  # one retry: these sites time out transiently
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=20) as resp:
                return resp.read().decode("utf-8", "ignore")
        except Exception as exc:  # noqa: BLE001 - best effort by design
            last_exc = exc
    raise last_exc


def slug_name(slug):
    name = SLUG_DATE_RE.sub("", slug)
    name = re.sub(r"-\d{2}-\d{2}$", "", name)
    return name.replace("-", " ").strip().title()


def title_from(url, html):
    """'HH:MM DD/MM ⚽ Team A vs Team B' in ICT when determinable."""
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    m = TIME_RE.search(html)
    luc = SLUG_LUC_RE.match(slug + "/")
    when = None
    if m:
        when = datetime.datetime.fromtimestamp(int(m.group(1)), ICT)
    elif luc:
        try:
            when = datetime.datetime(
                int(luc.group(6)), int(luc.group(5)), int(luc.group(4)),
                int(luc.group(2)), int(luc.group(3)), tzinfo=ICT)
            slug = luc.group(1)
        except ValueError:
            when = None
    name = slug_name(slug)
    if when:
        return f"{when:%H:%M %d/%m} ⚽ {name}"
    return f"⚽ {name}"


def scrape_match(url):
    """One match page -> list of (title, stream_url); never raises."""
    try:
        html = fetch(url)
    except Exception:
        return []
    title = title_from(url, html)
    out = []
    block = LIST_STREAM_RE.search(html)
    if block:
        pages = []
        for raw in STREAM_PAGE_RE.findall(block.group(1)):
            page = raw.replace("\\/", "/")
            if page not in pages:
                pages.append(page)
        for page in pages[:2]:
            try:
                player = fetch(page, referer=url)
            except Exception:
                continue
            for stream in DIRECT_STREAM_RE.findall(player):
                if "lfastcdn" in stream:
                    continue  # ad assets on the player page
                out.append((title, stream))
                break  # one stream per player page
        if out:
            return out
    host = HOST_RE.search(html)
    mid = MID_RE.search(html)
    if host and mid:
        out.append((title, f"{host.group(1)}/default/{mid.group(1)}.m3u8"))
    return out


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
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        for found in pool.map(scrape_match, links):
            results.extend(found)
    print(f"[{name}] {len(results)} streams from {len(links)} match pages",
          file=sys.stderr)
    return results


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
