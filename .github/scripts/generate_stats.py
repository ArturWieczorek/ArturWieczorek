#!/usr/bin/env python3
"""
Generate the profile stats cards as static SVGs from the GitHub GraphQL API.

No third-party render service: numbers come straight from GitHub, the SVGs are
drawn here, and the workflow commits them. If the API call fails the script
exits 0 without writing, so the previously committed (good) cards are kept.

Env:
  GITHUB_TOKEN  token with read access (the Actions built-in token is enough
                for public stats)
  USERNAME      GitHub login to report on
"""

import json
import os
import sys
import urllib.request
import urllib.error
from html import escape

# ---- ayu palette (matches the rest of the README) ----------------------------
BG = "#0a0e14"
GREEN = "#7ee787"   # prompt / headings
CYAN = "#5ccfe6"    # numbers / accent
TEXT = "#c9d4e0"    # labels
MUTED = "#2c3a4d"   # bar track / divider
MONO = "'SFMono-Regular',Consolas,'Liberation Mono',Menlo,monospace"

API = "https://api.github.com/graphql"

QUERY = """
query($login:String!, $after:String){
  user(login:$login){
    login
    name
    followers { totalCount }
    pullRequests { totalCount }
    issues { totalCount }
    publicRepos: repositories(ownerAffiliations:OWNER, privacy:PUBLIC) { totalCount }
    repositoriesContributedTo(contributionTypes:[COMMIT,PULL_REQUEST,ISSUE,REPOSITORY]) { totalCount }
    contributionsCollection { totalCommitContributions restrictedContributionsCount }
    repositories(first:100, after:$after, ownerAffiliations:OWNER, isFork:false, orderBy:{field:STARGAZERS, direction:DESC}){
      pageInfo { hasNextPage endCursor }
      nodes {
        languages(first:10, orderBy:{field:SIZE, direction:DESC}){
          edges { size node { name color } }
        }
      }
    }
  }
}
"""


def graphql(token, login, after=None):
    body = json.dumps({"query": QUERY, "variables": {"login": login, "after": after}}).encode()
    req = urllib.request.Request(API, data=body, method="POST")
    req.add_header("Authorization", "bearer " + token)
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "profile-stats-generator")
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode())
    if payload.get("errors"):
        raise RuntimeError("GraphQL errors: %s" % payload["errors"])
    user = payload.get("data", {}).get("user")
    if not user:
        raise RuntimeError("no user data in response")
    return user


def collect(token, login):
    langs = {}            # name -> [size, color]
    base = None
    after = None
    while True:
        user = graphql(token, login, after)
        if base is None:
            base = user
        repos = user["repositories"]
        for node in repos["nodes"]:
            for edge in node["languages"]["edges"]:
                n = edge["node"]["name"]
                slot = langs.setdefault(n, [0, edge["node"]["color"]])
                slot[0] += edge["size"]
        if repos["pageInfo"]["hasNextPage"]:
            after = repos["pageInfo"]["endCursor"]
        else:
            break

    cc = base["contributionsCollection"]
    stats = {
        "name": base.get("name") or base["login"],
        "Public repos": base["publicRepos"]["totalCount"],
        "Commits (last yr)": cc["totalCommitContributions"] + cc.get("restrictedContributionsCount", 0),
        "Pull requests": base["pullRequests"]["totalCount"],
        "Issues": base["issues"]["totalCount"],
        "Contributed to": base["repositoriesContributedTo"]["totalCount"],
        "Followers": base["followers"]["totalCount"],
    }
    top = sorted(langs.items(), key=lambda kv: kv[1][0], reverse=True)[:6]
    return stats, top


def num(n):
    return "{:,}".format(n)


def stats_card(stats):
    rows = ["Public repos", "Commits (last yr)", "Pull requests",
            "Issues", "Contributed to", "Followers"]
    w, h = 560, 300
    pad = 30
    y0, step = 122, 30
    out = [
        f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" role="img">',
        f'<rect width="{w}" height="{h}" rx="8" fill="{BG}"/>',
        f'<text x="{pad}" y="58" font-family="{MONO}" font-size="22" font-weight="700" fill="{GREEN}">&gt; git stats --author {escape(stats["name"])}</text>',
        f'<line x1="{pad}" y1="80" x2="{w-pad}" y2="80" stroke="{MUTED}" stroke-width="1.5"/>',
    ]
    for i, label in enumerate(rows):
        y = y0 + i * step
        out.append(f'<text x="{pad}" y="{y}" font-family="{MONO}" font-size="18" fill="{TEXT}">{label}</text>')
        out.append(f'<text x="{w-pad}" y="{y}" font-family="{MONO}" font-size="18" font-weight="700" fill="{CYAN}" text-anchor="end">{num(stats[label])}</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def langs_card(top):
    w, h = 390, 300
    pad = 28
    y0, step = 116, 33
    track_x, track_w, bar_h = 148, 202, 16
    total = sum(size for _, (size, _) in top) or 1
    out = [
        f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" xmlns="http://www.w3.org/2000/svg" role="img">',
        f'<rect width="{w}" height="{h}" rx="8" fill="{BG}"/>',
        f'<text x="{pad}" y="58" font-family="{MONO}" font-size="22" font-weight="700" fill="{GREEN}">&gt; top languages</text>',
        f'<line x1="{pad}" y1="80" x2="{w-pad}" y2="80" stroke="{MUTED}" stroke-width="1.5"/>',
    ]
    if top:
        top_size = top[0][1][0] or 1
        for i, (name, (size, color)) in enumerate(top):
            y = y0 + i * step
            pct = size * 100.0 / total
            bar = max(3, round(track_w * size / top_size))
            color = color or CYAN
            disp = name if len(name) <= 12 else name[:11] + "."
            out.append(f'<text x="{pad}" y="{y}" font-family="{MONO}" font-size="17" fill="{TEXT}">{escape(disp)}</text>')
            out.append(f'<rect x="{track_x}" y="{y-14}" width="{track_w}" height="{bar_h}" rx="{bar_h/2}" fill="{MUTED}"/>')
            out.append(f'<rect x="{track_x}" y="{y-14}" width="{bar}" height="{bar_h}" rx="{bar_h/2}" fill="{color}"/>')
            out.append(f'<text x="{w-pad}" y="{y}" font-family="{MONO}" font-size="17" font-weight="700" fill="{CYAN}" text-anchor="end">{pct:.0f}%</text>')
    else:
        out.append(f'<text x="{pad}" y="{y0}" font-family="{MONO}" font-size="17" fill="{TEXT}">no language data</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main():
    token = os.environ.get("GITHUB_TOKEN")
    login = os.environ.get("USERNAME")
    if not token or not login:
        print("GITHUB_TOKEN and USERNAME are required", file=sys.stderr)
        return 1
    try:
        stats, top = collect(token, login)
    except (urllib.error.URLError, urllib.error.HTTPError, RuntimeError, KeyError, TimeoutError) as exc:
        # Upstream/API problem: keep the last committed cards, stay green.
        print("could not fetch stats, keeping last good cards: %s" % exc, file=sys.stderr)
        return 0

    os.makedirs("assets", exist_ok=True)
    with open("assets/github-stats.svg", "w") as fh:
        fh.write(stats_card(stats))
    with open("assets/top-langs.svg", "w") as fh:
        fh.write(langs_card(top))
    print("wrote assets/github-stats.svg and assets/top-langs.svg")
    print("stats:", {k: v for k, v in stats.items() if k != "name"})
    print("langs:", [(n, s) for n, (s, _) in top])
    return 0


if __name__ == "__main__":
    sys.exit(main())
