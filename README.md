# dabanh-playlist

Backup mirror of the dabanh M3U playlist.

- Primary source: https://thtt.pages.dev/tttt.m3u
- This mirror: https://raw.githubusercontent.com/zjoenguyenz/dabanh-playlist/main/tttt.m3u

A GitHub Actions workflow re-fetches the primary source every 2 hours
and commits the new copy only when it changed and still looks like a
valid playlist (starts with #EXTM3U, at least 50 entries). If the
primary source ever dies, the last good copy keeps being served from
the mirror URL above.
