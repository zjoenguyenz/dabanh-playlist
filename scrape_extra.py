#!/usr/bin/env python3
"""Best-effort scraper for the xoilac / 90phut / socolive site family.

Two stream mechanisms exist in this family (both found live 2026-11-12):

A) list_stream (xoilac365, 90phut, xoilac86, socolive): the match page
   carries a JS array `list_stream` of player-page URLs on a per-site
   host (e.g. https://xl365.domainkqt.cc/ajax/chanel/type/8/link/...).
   Each player page embeds exactly one direct stream URL (.flv).

B) inplyr (xoilac3, tructiepbongda): the match page embeds JSON
   `streamData` with "playerHost" plus an inline `match_id`; the
   stream URL is <playerHost>/default/<match_id>.m3u8. These pages
   also carry per-match commentator (BLV) anchors "?blv=<uid>" whose
   streams are <playerHost>/room/<uid>.m3u8.

Extras beyond plain entries:
- "🔥 Hot" group, emitted first: only the matches the sites
  themselves flag hot on their listings (card class "...-item-hot"),
  with their BLV variants included when the flagged match has any.
- BLV entries: "<title> • BLV <name>" with the room stream.

Output: extra M3U entries on stdout. Any failure anywhere yields
fewer entries, never an exception — the mirror's main source must
stay unaffected.
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
ANCHOR_RE = re.compile(r"<a\b[^>]*>", re.I)
HREF_RE = re.compile(r'href="([^"]+)"')
LIST_STREAM_RE = re.compile(r"list_stream\s*=\s*\[(.*?)\];", re.S)
STREAM_PAGE_RE = re.compile(r'https?:\\?/\\?/[^\s"\'\\]+')
DIRECT_STREAM_RE = re.compile(r'https?://[^\s"\'<>]+\.(?:flv|m3u8)(?:\?[^\s"\'<>]*)?')
HOST_RE = re.compile(r'"playerHost"\s*:\s*"(https?:\\?/\\?/[^"]+)"')
MID_RE = re.compile(r"match_id\s*=\s*'([A-Za-z0-9]+)'")
BLV_JSON_RE = re.compile(r'"uid":"(\d+)","nickName":"([^"]+)","roomID":"(\d+)"')
TIME_RE = re.compile(r'"matchTime"\s*:\s*(\d{10})')
BLV_RE = re.compile(r'<a href="([^"]*)\?blv=(\d+)"[^>]*>(.*?)</a>', re.S)
SLUG_DATE_RE = re.compile(r"-(\d{2})-(\d{2})-(\d{4})/?$")
SLUG_LUC_RE = re.compile(
    r"^(.*?)-luc-(\d{2})(\d{2})-ngay-(\d{2})-(\d{2})-(\d{4})/?$")
MAX_MATCHES_PER_SITE = 30
HOT_GROUP = "🔥 Hot"


def fetch(url, referer=None):
    headers = {"User-Agent": UA}
    if referer:
        headers["Referer"] = referer
    last_exc = None
    for _ in range(2):  # one retry: these sites time out transiently
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
    """One match page -> dict(main=[(title, stream)], blv=[(title,
    stream)]); never raises."""
    result = {"main": [], "blv": []}
    try:
        html = fetch(url)
    except Exception:
        return result
    title = title_from(url, html)
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
                result["main"].append((title, stream))
                break  # one stream per player page
        if result["main"]:
            return result
    host = HOST_RE.search(html)
    mid = MID_RE.search(html)
    if host and mid:
        base = host.group(1).replace("\\/", "/")
        result["main"].append((title, f"{base}/default/{mid.group(1)}.m3u8"))
        seen_rooms = set()

        def add_blv(name, room):
            # nickName arrives as raw JSON text: decode \uXXXX escapes into
            # real characters FIRST. Without this, name.title() below chews
            # the escapes into garbage like "Nh\U1Eca Ca" (seen live
            # 2026-11-13 in the published mirror).
            name = re.sub(r"\\u([0-9a-fA-F]{4})",
                          lambda m: chr(int(m.group(1), 16)), name)
            name = re.sub(r"\\U([0-9a-fA-F]{8})",
                          lambda m: chr(int(m.group(1), 16)), name)
            name = re.sub(r"\s+", " ", name).strip()
            if not name or len(name) > 40 or room in seen_rooms:
                return
            seen_rooms.add(room)
            if not name.upper().startswith("BLV"):
                name = "BLV " + name.title()
            result["blv"].append(
                (f"{title} • {name}", f"{base}/room/{room}.m3u8"))

        # Primary source: the commentator array inside streamData JSON
        # (uid / nickName / roomID per commentator).
        for _uid, nick, room in BLV_JSON_RE.findall(html):
            add_blv(nick, room)
        # Fallback only when the JSON array named nobody: self-
        # referential ?blv=<uid> anchors on the page (uid as room).
        if not result["blv"]:
            path = "/" + url.split("/", 3)[-1]  # this match's own path
            for href, uid, inner in BLV_RE.findall(html):
                if href.endswith(path):
                    add_blv(re.sub(r"<[^>]+>", " ", inner), uid)
    return result


def scrape_site(name, base):
    """-> (entries, hot_entries): [(title, stream)] each."""
    links = []
    seen = set()
    hot_urls = set()
    for page in (base + "/", base + "/truc-tiep/"):
        try:
            html = fetch(page)
        except Exception as exc:
            print(f"[{name}] {page} failed: {exc}", file=sys.stderr)
            continue
        for tag in ANCHOR_RE.findall(html):
            hm = HREF_RE.search(tag)
            if not hm:
                continue
            raw = hm.group(1)
            m = re.search(r"((?:https?://[^\"/]+)?/truc-tiep/[^\"?#]+/)$", raw)
            if not m:
                continue
            url = m.group(1)
            url = url if url.startswith("http") else base + url
            if "item-hot" in tag:
                hot_urls.add(url)
            if url not in seen:
                seen.add(url)
                links.append(url)
    links = links[:MAX_MATCHES_PER_SITE]

    def job(url):
        return url, scrape_match(url)

    entries, hot_entries = [], []
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        for url, found in pool.map(job, links):
            entries.extend(found["main"])
            entries.extend(found["blv"])
            # Hot means the SITE flagged the match (item-hot card).
            # BLV presence is not a hot signal: the inplyr sites attach
            # their whole commentator roster to every match page.
            if url in hot_urls:
                hot_entries.extend(found["main"])
                hot_entries.extend(found["blv"])
    print(f"[{name}] {len(entries)} streams from {len(links)} match pages"
          f" ({len(hot_entries)} hot)", file=sys.stderr)
    return entries, hot_entries


_KICKOFF_RE = re.compile(r'(\d{1,2}):(\d{2})\s+(\d{1,2})/(\d{1,2})')
HOT_MAX_AGE_MIN = 135


def kickoff_of(title):
    """First 'HH:MM DD/MM' in the title, Asia/Ho_Chi_Minh, current year —
    the same rule the apps use (KickoffParser). None when absent."""
    m = _KICKOFF_RE.search(title or "")
    if not m:
        return None
    try:
        from zoneinfo import ZoneInfo
        vn = ZoneInfo("Asia/Ho_Chi_Minh")
    except Exception:
        return None
    now = datetime.datetime.now(vn)
    try:
        ko = now.replace(hour=int(m.group(1)), minute=int(m.group(2)),
                         day=int(m.group(3)), month=int(m.group(4)),
                         second=0, microsecond=0)
    except ValueError:
        return None
    if (now - ko).days > 30:  # New Year fixtures, same roll-forward as the apps
        ko += datetime.timedelta(days=365)
    return ko


def is_stale_hot(title):
    """True when a Hot entry's kickoff is over HOT_MAX_AGE_MIN old. The
    source sites leave finished matches flagged hot for hours and the
    apps can only infer 'live' from the kickoff, so stale entries are
    dropped from the Hot group (they stay in their site/league groups,
    where the apps reclassify them as replays)."""
    ko = kickoff_of(title)
    if ko is None:
        return False
    from zoneinfo import ZoneInfo
    now = datetime.datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))
    return (now - ko).total_seconds() > HOT_MAX_AGE_MIN * 60


def prune_stale_hot(text):
    """Remove stale Hot-group entries from playlist text. An entry block
    is its #EXTINF line plus the following lines up to the next #EXTINF
    (the stream URL and any #EXTVLCOPT lines)."""
    lines = text.split("\n")
    out, i, dropped = [], 0, 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("#EXTINF") and f'group-title="{HOT_GROUP}"' in line:
            j = i + 1
            while j < len(lines) and not lines[j].startswith("#EXTINF"):
                j += 1
            title = line.split(",", 1)[1] if "," in line else line
            if is_stale_hot(title):
                dropped += 1
                i = j
                continue
            out.extend(lines[i:j])
            i = j
        else:
            out.append(line)
            i += 1
    if dropped:
        print(f"sanitize: pruned {dropped} stale Hot entries", file=sys.stderr)
    return "\n".join(out)


DEAD_DROP_FLOOR = 0.35  # probe-drops above this share => distrust the prober


def _block_url_headers(block):
    """(url, headers) of one entry block: the stream URL plus the
    playback headers the entry itself declares via #EXTVLCOPT."""
    url, headers = None, {}
    for ln in block:
        if ln.startswith("#EXTVLCOPT:http-referrer="):
            headers["Referer"] = ln.split("=", 1)[1].strip()
        elif ln.startswith("#EXTVLCOPT:http-user-agent="):
            headers["User-Agent"] = ln.split("=", 1)[1].strip()
        elif ln.startswith(("http://", "https://")):
            url = ln.strip()
    return url, headers


def _probe_alive(url, headers):
    """True = keep the entry. Only VANTAGE-INDEPENDENT death returns
    False: HTTP 404/410 (the URL itself is gone — true from anywhere)
    or a 200 whose body is not a playlist (for .m3u8). Everything else
    keeps the entry: connect/DNS failures and timeouts depend on where
    the probe runs (measured 2026-11-13: every inplyr link fails to
    connect from a datacenter vantage yet plays fine from the user's
    TV), and geo/auth blocks (403/401) are exactly what the apps'
    Vietnam tunnel exists for."""
    h = {"User-Agent": headers.get("User-Agent", UA)}
    if "Referer" in headers:
        h["Referer"] = headers["Referer"]
    try:
        req = urllib.request.Request(url, headers=h)
    except Exception:  # noqa: BLE001 - unbuildable URL: keep, apps cope
        return True
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            body = resp.read(2048)
            if ".m3u8" in url.split("?")[0]:
                return b"#EXTM3U" in body
            return len(body) > 0
    except urllib.error.HTTPError as e:
        return e.code not in (404, 410)
    except Exception:  # noqa: BLE001 - vantage-dependent: keep
        return True


def filter_dead_links(text):
    """Drop filler + definitively-dead entries from playlist text.

    Filler: '/no-signal/' placeholder slates (freem3u) — not content.
    The rest are probed in parallel with each entry's own declared
    headers. A safety floor aborts probe-drops (filler still goes) if
    too large a share would drop, e.g. if the runner's network is bad.
    """
    lines = text.split("\n")
    head, blocks, i = [], [], 0
    while i < len(lines) and not lines[i].startswith("#EXTINF"):
        head.append(lines[i])
        i += 1
    while i < len(lines):
        j = i + 1
        while j < len(lines) and not lines[j].startswith("#EXTINF"):
            j += 1
        blocks.append(lines[i:j])
        i = j
    keep, jobs, filler = [], [], 0
    for b in blocks:
        url, headers = _block_url_headers(b)
        if url is None:
            keep.append(b)
        elif 'group-title="Updated ' in b[0]:
            # Freshness-stamp pseudo-entry: its URL is a no-signal slate
            # BY DESIGN — the apps read the mirror's generation time from
            # this entry. Never treat it as filler (bug 2026-11-13: the
            # /no-signal/ rule below silently stripped it every run).
            keep.append(b)
        elif "/no-signal/" in url:
            filler += 1
        else:
            jobs.append((b, url, headers))
    dead = set()
    if jobs:
        with concurrent.futures.ThreadPoolExecutor(max_workers=24) as ex:
            futs = {ex.submit(_probe_alive, u, h): k
                    for k, (_, u, h) in enumerate(jobs)}
            for fut in concurrent.futures.as_completed(futs):
                if not fut.result():
                    dead.add(futs[fut])
    if jobs and len(dead) / len(jobs) > DEAD_DROP_FLOOR:
        print(f"validate: {len(dead)}/{len(jobs)} probe-dead exceeds "
              f"floor; keeping all probed entries", file=sys.stderr)
        dead = set()
    dropped_hosts = {}
    for k, (b, url, _) in enumerate(jobs):
        if k in dead:
            host = url.split("/")[2] if "://" in url else "?"
            dropped_hosts[host] = dropped_hosts.get(host, 0) + 1
        else:
            keep.append(b)
    if dead or filler:
        top = sorted(dropped_hosts.items(), key=lambda kv: -kv[1])[:5]
        print(f"validate: probed {len(jobs)}, dropped dead {len(dead)} "
              f"{top}, dropped filler {filler}", file=sys.stderr)
    out = list(head)
    for b in keep:
        out.extend(b)
    return "\n".join(out)


def sanitize_main_playlist(path="tttt.m3u"):
    """Decode literal backslash-u escapes in the mirrored primary playlist.

    The primary source sometimes ships titles with un-decoded escapes
    (BLV names). The workflow runs this script right after fetching the
    primary copy, so cleaning tttt.m3u here covers the whole published
    file before commit. (This lives here, not in the workflow YAML,
    because the GitHub integration cannot edit workflow files.)
    Best effort: any failure leaves the playlist untouched.
    """
    try:
        with open(path, encoding="utf-8", errors="ignore") as fh:
            orig = fh.read()
        s = re.sub(r'\\U([0-9a-fA-F]{8})', lambda m: chr(int(m.group(1), 16)), orig)
        s = re.sub(r'\\[uU]([0-9a-fA-F]{4})', lambda m: chr(int(m.group(1), 16)), s)
        out, i = [], 0
        while i < len(s):
            o = ord(s[i])
            if 0xD800 <= o <= 0xDBFF and i + 1 < len(s) and 0xDC00 <= ord(s[i + 1]) <= 0xDFFF:
                out.append(chr(0x10000 + ((o - 0xD800) << 10) + (ord(s[i + 1]) - 0xDC00)))
                i += 2
            elif 0xD800 <= o <= 0xDFFF:
                out.append('\ufffd')
                i += 1
            else:
                out.append(s[i])
                i += 1
        cleaned = filter_dead_links(prune_stale_hot("".join(out)))
        if cleaned != orig:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(cleaned)
            print("sanitize: decoded escapes in tttt.m3u", file=sys.stderr)
    except Exception as e:
        print(f"sanitize skipped: {e}", file=sys.stderr)


def main():
    sanitize_main_playlist()
    hot_out, out = [], []
    hot_seen, seen_streams = set(), set()
    for name, base in SITES:
        entries, hot_entries = scrape_site(name, base)
        for title, stream in hot_entries:
            if is_stale_hot(title):
                continue  # finished long ago; site still flags it hot
            if stream not in hot_seen:
                hot_seen.add(stream)
                hot_out.append(f'#EXTINF:-1 group-title="{HOT_GROUP}",{title}')
                hot_out.append(stream)
        for title, stream in entries:
            if stream in seen_streams:
                continue  # sister sites carry identical schedules/streams
            seen_streams.add(stream)
            out.append(f'#EXTINF:-1 group-title="{name}",{title}')
            out.append(stream)
    lines = hot_out + out
    sys.stdout.write("\n".join(lines) + ("\n" if lines else ""))
    print(f"Total extra entries: {len(lines) // 2} "
          f"(hot: {len(hot_out) // 2})", file=sys.stderr)


if __name__ == "__main__":
    main()
