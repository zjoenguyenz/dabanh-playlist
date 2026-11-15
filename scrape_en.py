#!/usr/bin/env python3
"""English-commentary backup block for the dabanh playlist mirror.

Emits M3U entries (stdout) for a curated set of English-language sports
channels, group "EN · BLV Anh", meant to be appended AFTER the whole
Vietnamese list in tttt.m3u. Selection (owner, 2026-11-14): best measured
image quality first (true 1080p where it exists), then lowest latency;
the block stands on several independent upstreams so one dead upstream
only costs its own channels.

Dynamic URLs (Xumo via the BuddyChewChew generator, Wurl via apsattv)
carry session ad parameters, so they are re-pulled from the freshest
generator lists on every run; the constants below are the last verified
snapshot (2026-11-14, sample-played end to end from a US IP) used only
when a fresh pull fails. Static URLs (Amagi, Google DAI, the ESPN panel)
have no session parameters. Every emitted URL is health-checked
(master playlist must answer 200 and look like HLS); dead entries are
dropped for that run. Any failure anywhere yields fewer entries, never
an error: this script must never block the mirror.
"""
import sys
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
GROUP = "EN · BLV Anh"

XUMO_LIST = ("https://raw.githubusercontent.com/BuddyChewChew/"
             "xumo-playlist-generator/refs/heads/main/playlists/"
             "xumo_playlist.m3u")
USLG_LIST = "https://www.apsattv.com/uslg.m3u"
VIZIO_LIST = "https://www.apsattv.com/vizio.m3u"

# Last verified snapshot, 2026-11-14 (fallbacks only).
FALLBACK = {
    "fox": "https://dbrb49pjoymg4.cloudfront.net/10001/99991196/hls/xumo.m3u8?ads.xumo_channelId=99991196&ads._fw_ifa_type=&ads._fw_did=491daae8-ab31-4543-aacc-da1e096f02f2&ads.amznappId=&ads.lat=&ads.lon=&ads.os=&ads.osv=&ads.asnw=&ads.caid=FoxSports&ads.csid=xumo_web_FoxSports_ssai&ads._fw_is_lat=0&ads._fw_us_privacy=&ads._fw_coppa=0&ads.genre=Sport,Sports,SA,SC,SE,SN&ads._fw_content_category=&ads._fw_content_language=en&ads._fw_content_genre=Sport,Sports,SA,SC,SE,SN&ads._fw_content_rating=&ads.xumo_contentId=142&ads.xumo_contentName=FoxSports&ads.xumo_providerId=142&ads.xumo_providerName=FoxSports&ads._fw_deviceMake=GitHubAction&ads._fw_device_model=PythonScript&ads.channelId=99991196&ads.xumo_platform=web&ads.site_id=&ads.appName=xumo&ads.appVersion=1.0.0&ads._fw_app_bundle=web.xumo.com&ads._fw_app_store_url=",
    "fubo": "https://dbrb49pjoymg4.cloudfront.net/10001/99951548/hls/master.m3u8?includeAssetTags=true&ads.xumo_channelId=99951548&ads.xumo_streamId=99951548&ads.channelId=99951548&ads.channelName=FuboTV&ads.caid=FuboTV&ads.csid=xumo_web_FuboTV_ssai&ads.genre=Sport,Sports,SC,SE,SN,IAB17&ads._fw_content_genre=Sport,Sports,SC,SE,SN,IAB17&ads._fw_coppa=0.0&ads.xumo_contentId=1046&ads.xumo_contentName=FuboTV&ads.xumo_providerId=1046&ads.xumo_providerName=FuboTV&ads.asnw=&ads.xumo_channelName=FuboTV&ads._fw_h_x_country=US&ads._fw_ifa_type=&ads._fw_did=2ee040b1-d415-4c85-b069-6e8700e6b00e&ads.amznappId=&ads.lat=&ads.lon=&ads.os=&ads.osv=&ads._fw_is_lat=0&ads._fw_us_privacy=&ads._fw_content_category=&ads._fw_content_language=en&ads._fw_content_rating=&ads._fw_deviceMake=GitHubAction&ads._fw_device_model=PythonScript&ads.xumo_platform=web&ads.site_id=&ads.appVersion=1.0.0&ads._fw_app_bundle=web.xumo.com&ads._fw_app_store_url=&ads.appName=xumo",
    "nbc": "https://d4whmvwm0rdvi.cloudfront.net/10007/99951253/hls/master.m3u8?includeAssetTags=true&ads.xumo_channelId=99951253&ads.xumo_streamId=99951253&ads.channelId=99951253&ads.asnw=169843&ads.afid=380753925&ads.sfid=19208128&ads.csid=xumo_web_NBCUSports_ssai_cro&ads._fw_coppa=0&ads.xumo_contentId=3929&ads.xumo_contentName=NBCUSports&ads.xumo_providerId=3929&ads.xumo_providerName=NBCUSports&ads.caid=&ads._fw_is_lat=0&ads._fw_us_privacy=&ads._fw_did=38298231-7ef3-4fd8-8ef7-24e527987b28&ads._fw_vcid2=512116:38298231-7ef3-4fd8-8ef7-24e527987b28&ads._fw_app_bundle=&ads._fw_app_store_url=&ads._fw_deviceMake=&ads._fw_device_model=&ads._fw_deviceType=3-Connected_TV&ads.appVersion=1.0.0&ads._fw_ifa_type=&ads.appName=XumoPlay&ads._fw_content_category=&ads._fw_content_genre=&ads._fw_content_language=en&ads._fw_content_rating=",
    "stadium": "https://wurl120sports.global.transmit.live/hls/6863f426233e6604b8b45832/v1/stadium_gracenote/lg_us/latest/main/hls/playlist.m3u8?wurl_channel=160&wurl_name=Stadium&coppa=0&uid=[DEVICE_ID]&rdid=[IFA]&ifatype=[IFA_TYPE]&dnt=[LMT]&donotsell=[DNS]&isgdpr=[GDPR]&gdpr=[GDPR_CONSENT]&country=[COUNTRY]&pr=[US_PRIVACY]&appstoreurl=[APP_STOREURL]&bundleid=[APP_BUNDLE]&appname=[APP_NAME]&appversion=[APP_VERSION]&dt=[DEVICE_TYPE]&make=[DEVICE_MAKE]&model=[DEVICE_MODEL]&targetad=[TARGETAD_ALLOWED]&fck=[FCK]&viewsize=[VIEWSIZE]&nonce=[NONCE]",
    "fifa": "https://95cedebd.wurl.com/master/f36d25e7e52f1ba8d7e56eb859c636563214f541/Vml6aW9fRklGQVBsdXNFbmdsaXNoX0hMUw/playlist.m3u8?ads.wurl_channel=1854&ads.wurl_name=FIFAPlusEnglish&ads.coppa=0&ads.psid=%7bADID%7d&ads.targetopt=%7bTARGETOPT%7d&ads.us_privacy=%7bUSPRIVACY%7d&ads.ifa_type=%7bIFATYPE%7d&ads.lmt=%7bLMT%7d&ads.app_bundle=%7bAPP_BUNDLE%7d&ads.app_name=%7bAPP_NAME%7d&ads.app_store_url=%7bAPP_STORE_URL%7d&ads.url=%7bDOMAIN%7d&ads.w=%7bWIDTH%7d&ads.h=%7bHEIGHT%7d&ads.device_make=%7bDEVICE_MAKE%7d&ads.vizdartoken=eyJhdWQiOiI5OCIsIndmcGNpZCI6NDU0NzkyNzc3MH0",
}

STATIC = {
    "golazo": ("https://dai.google.com/linear/hls/event/"
               "7f3Wv6f7QEKfQna22jHqLQ/master.m3u8"),
    "bein_xtra": "https://bein-xtra-bein.amagi.tv/playlist.m3u8",
    "fs1": "http://85.237.89.160:9590/usa-s/FOX-SPORTS-1/index.m3u8",
    "espn": "http://85.237.89.160:9590/usa-s/ESPN-HD/index.m3u8",
    "espn2": "http://85.237.89.160:9590/usa-s/ESPN-2-HD/index.m3u8",
    "espnu": "http://85.237.89.160:9590/usa-s/ESPN-U-HD/index.m3u8",
}


def fetch(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def extract(list_text, match):
    """URL following the #EXTINF whose title satisfies match(title)."""
    lines = list_text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("#EXTINF"):
            title = line.split(",", 1)[-1].strip()
            if match(title) and i + 1 < len(lines):
                return lines[i + 1].strip()
    return None


def healthy(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=15) as r:
            head = r.read(512).decode("utf-8", "replace")
            return r.status == 200 and "#EXTM3U" in head
    except Exception:
        return False


def dynamic(list_url, match, key):
    try:
        url = extract(fetch(list_url), match)
        if url:
            return url
    except Exception as exc:
        print(f"[en] {key}: fresh pull failed: {exc}", file=sys.stderr)
    return FALLBACK[key]


def main():
    entries = [
        # 1080p group first (quality priority), ordered by measured
        # bitrate/latency on 2026-11-14; the ESPN trio is 720p — the
        # best that exists for those channels — and closes the block.
        ("EN · CBS Sports Golazo", STATIC["golazo"]),
        ("EN · Fox Sports 1", STATIC["fs1"]),
        ("EN · FOX Sports", dynamic(XUMO_LIST, lambda t: t == "FOX Sports", "fox")),
        ("EN · Fubo Sports", dynamic(XUMO_LIST, lambda t: t == "Fubo Sports Network", "fubo")),
        ("EN · Stadium", dynamic(USLG_LIST, lambda t: "Stadium" in t, "stadium")),
        ("EN · NBC Sports NOW", dynamic(XUMO_LIST, lambda t: t == "NBC Sports NOW", "nbc")),
        ("EN · beIN SPORTS XTRA", STATIC["bein_xtra"]),
        ("EN · FIFA+", dynamic(VIZIO_LIST, lambda t: t == "FIFA+", "fifa")),
        ("EN · ESPN", STATIC["espn"]),
        ("EN · ESPN 2", STATIC["espn2"]),
        ("EN · ESPNU", STATIC["espnu"]),
    ]
    out = []
    for name, url in entries:
        if url and healthy(url):
            out.append(f'#EXTINF:-1 group-title="{GROUP}",{name}')
            out.append(url)
        else:
            print(f"[en] dropped (health check): {name}", file=sys.stderr)
    sys.stdout.write("\n".join(out) + ("\n" if out else ""))
    print(f"[en] emitted {len(out) // 2} entries", file=sys.stderr)


if __name__ == "__main__":
    main()
