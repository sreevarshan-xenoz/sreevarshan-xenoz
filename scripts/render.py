#!/usr/bin/env python3
"""Draws the artwork on my GitHub profile.

  year-{theme}.svg          the last 365 days of contributions, one spoke per day
  card-{repo}-{theme}.svg   a featured repository's file tree, drawn radially

Data comes from the GitHub API using GITHUB_TOKEN. Fonts are embedded so the
images render the same everywhere, and are subset when fontTools is installed.
Fonts: Instrument Serif and IBM Plex Mono, both SIL Open Font License 1.1.

Usage: GITHUB_TOKEN=... python scripts/render.py [out_dir]
"""
import base64
import html
import datetime as dt
import io
import json
import math
import os
import sys
import time
import urllib.request
from pathlib import Path

USER = "sreevarshan-xenoz"
PROJECTS = [  # repo, display name, tagline (keep taglines under ~32 characters)
    ("xencode", "xencode", "local-first AI coding agent"),
    ("Pocketdesk", "Pocketdesk", "your desktop, on your phone"),
    ("project-friday", "FRIDAY", "a desktop agent for Windows"),
    ("codehalo", "CodeHalo", "a HUD for AI coding agents"),
    ("fluxbond", "FluxBond", "Wi-Fi and 5G, bonded as one"),
    ("LedgerMind", "LedgerMind", "finance-ops reconciliation agent"),
]
SKIP_DIRS = {"node_modules", "target", "dist", "build", "vendor", ".git", "__pycache__", ".next", ".venv"}

THEMES = {
    "dark": {
        "ink": "#f0f6fc", "dim": "#9198a1", "faint": "#3d444d", "branch": "#6e7681", "glow": 0.5,
        "heat": ["#7f1d1d", "#c2410c", "#f97316", "#fbbf24", "#fff7ed"],
    },
    "light": {
        "ink": "#1f2328", "dim": "#59636e", "faint": "#d1d9e0", "branch": "#8c959f", "glow": 0,
        "heat": ["#fdba74", "#f97316", "#ea580c", "#9a3412", "#431407"],
        "card_heat": ["#f97316", "#ea580c", "#c2410c", "#7c2d12", "#431407"],  # thin strokes need deeper ink
    },
}

FONT_DIR = Path(__file__).parent / "fonts"
FONTS = {  # css family -> file
    "S": "instrument-serif-latin-400-normal.woff2",
    "SI": "instrument-serif-latin-400-italic.woff2",
    "M": "ibm-plex-mono-latin-400-normal.woff2",
    "MM": "ibm-plex-mono-latin-500-normal.woff2",
}
FALLBACK = {"S": "Georgia, serif", "SI": "Georgia, serif", "M": "ui-monospace, monospace", "MM": "ui-monospace, monospace"}
MONTHS = "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split()


# ---------------------------------------------------------------- data

def _request(url, body=None):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": USER}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    for attempt in range(6):
        req = urllib.request.Request(url, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                if res.status == 202:  # GitHub is still computing; ask again
                    time.sleep(3)
                    continue
                return json.load(res)
        except OSError:
            if attempt == 5:
                raise
            time.sleep(2 + attempt * 2)
    raise RuntimeError(f"no data from {url}")


def api(path):
    return _request(f"https://api.github.com/{path}")


def contribution_days():
    query = """query($login: String!) { user(login: $login) { contributionsCollection {
      contributionCalendar { weeks { contributionDays { date contributionCount } } } } } }"""
    res = _request("https://api.github.com/graphql", {"query": query, "variables": {"login": USER}})
    weeks = res["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]
    days = [(dt.date.fromisoformat(d["date"]), d["contributionCount"]) for w in weeks for d in w["contributionDays"]]
    return days[-365:]


def repo_data(repo):
    meta = api(f"repos/{USER}/{repo}")
    tree = api(f"repos/{USER}/{repo}/git/trees/{meta['default_branch']}?recursive=1")["tree"]
    files = [(e["path"], e.get("size", 0)) for e in tree if e["type"] == "blob"]
    files = [(p, s) for p, s in files if not SKIP_DIRS.intersection(p.split("/")[:-1])]
    langs = api(f"repos/{USER}/{repo}/languages")
    return {"files": files, "langs": langs, "pushed": dt.datetime.fromisoformat(meta["pushed_at"].replace("Z", "+00:00"))}


# ---------------------------------------------------------------- svg helpers

class Type:
    """Collects the characters each font draws so the embedded fonts can be subset."""

    def __init__(self):
        self.used = {k: set() for k in FONTS}

    def __call__(self, family, s):
        self.used[family].update(s)
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def css(self):
        out = []
        for fam, file in FONTS.items():
            if not self.used[fam]:
                continue
            raw = (FONT_DIR / file).read_bytes()
            raw = _subset(raw, self.used[fam] | {" "})
            b64 = base64.b64encode(raw).decode()
            out.append(f"@font-face{{font-family:'{fam}';src:url(data:font/woff2;base64,{b64}) format('woff2')}}")
            out.append(f".{fam.lower()}{{font-family:'{fam}',{FALLBACK[fam]}}}")
        return "".join(out)


def _subset(raw, chars):
    try:
        from fontTools import subset
        from fontTools.ttLib import TTFont
    except ImportError:
        return raw
    font = TTFont(io.BytesIO(raw))
    opts = subset.Options()
    opts.flavor = "woff2"
    opts.layout_features = ["kern", "liga", "calt"]
    sub = subset.Subsetter(opts)
    sub.populate(text="".join(chars))
    sub.subset(font)
    buf = io.BytesIO()
    font.flavor = "woff2"
    font.save(buf)
    return buf.getvalue()


def pt(cx, cy, r, deg):
    a = math.radians(deg)
    return cx + r * math.cos(a), cy + r * math.sin(a)


def f1(v):
    s = f"{v:.1f}"
    return s[:-2] if s.endswith(".0") else s


def heat_gradient(gid, cx, cy, r_in, r_out, colors):
    """Radial gradient so a stroke gets hotter the further it reaches from the centre."""
    span = r_out - r_in
    stops = [(r_in, colors[0]), (r_in + span * 0.3, colors[1]), (r_in + span * 0.58, colors[2]),
             (r_in + span * 0.82, colors[3]), (r_out, colors[4])]
    s = "".join(f'<stop offset="{r / r_out:.3f}" stop-color="{c}"/>' for r, c in stops)
    return f'<radialGradient id="{gid}" gradientUnits="userSpaceOnUse" cx="{cx}" cy="{cy}" r="{f1(r_out)}">{s}</radialGradient>'


def svg(w, h, label, defs, body, style, t):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-label="{html.escape(label)}">'
            f'<style>{t.css()}{style}'
            '@media (prefers-reduced-motion: reduce){*{animation:none!important}}</style>'
            f'<defs>{defs}</defs>{body}</svg>\n')


# ---------------------------------------------------------------- year ring

def render_year(days, theme):
    th, t = THEMES[theme], Type()
    W, H, cx, cy = 1000, 700, 500, 350
    r0, L, gap = 132, 168, 8
    R = r0 + L
    n = len(days)
    counts = [c for _, c in days]
    peak = max(range(n), key=lambda i: counts[i])
    top = math.log1p(counts[peak]) or 1

    def ang(i):
        return -90 + gap / 2 + (360 - gap) * (i + 0.5) / n

    def reach(c):
        return 6 + (L - 6) * math.log1p(c) / top

    spokes, dots = [], []
    for i, (_, c) in enumerate(days):
        a = ang(i)
        if c:
            x1, y1 = pt(cx, cy, r0, a)
            x2, y2 = pt(cx, cy, r0 + reach(c), a)
            spokes.append(f'<path d="M{f1(x1)} {f1(y1)}L{f1(x2)} {f1(y2)}" pathLength="1" style="--i:{i}"/>')
        else:
            x, y = pt(cx, cy, r0 + 1.5, a)
            dots.append(f'<circle cx="{f1(x)}" cy="{f1(y)}" r="1.1"/>')

    # scale grooves, broken at the seam where their labels sit
    grooves = []
    a1, a2 = -90 + gap / 2, 270 - gap / 2
    for v in (1, 10, 100):
        if v > counts[peak]:
            continue
        r = r0 + reach(v)
        (sx, sy), (ex, ey) = pt(cx, cy, r, a1), pt(cx, cy, r, a2)
        grooves.append(f'<path d="M{f1(sx)} {f1(sy)}A{f1(r)} {f1(r)} 0 1 1 {f1(ex)} {f1(ey)}"/>')
        grooves.append(f'<text x="{cx}" y="{f1(cy - r)}" class="m" font-size="10" text-anchor="middle" '
                       f'dominant-baseline="central" fill="{th["dim"]}">{t("M", str(v))}</text>')

    # month ticks and labels
    months = []
    for i, (d, _) in enumerate(days):
        a = ang(i) - (360 - gap) / n / 2
        if d.day != 1 or min(a + 90, 270 - a) < 9:  # leave the seam to the NOW marker
            continue
        (tx1, ty1), (tx2, ty2) = pt(cx, cy, r0 - 12, a), pt(cx, cy, r0 - 4, a)
        months.append(f'<path d="M{f1(tx1)} {f1(ty1)}L{f1(tx2)} {f1(ty2)}" stroke="{th["faint"]}" stroke-width="1"/>')
        lx, ly = pt(cx, cy, R + 34, a)
        name = MONTHS[d.month - 1] + (f" {d.year}" if d.month == 1 else "")
        months.append(f'<text x="{f1(lx)}" y="{f1(ly)}" class="m" font-size="12" letter-spacing="1.5" '
                      f'text-anchor="middle" dominant-baseline="central" fill="{th["dim"]}">{t("M", name)}</text>')

    px, py = pt(cx, cy, r0 + reach(counts[peak]) + 9, ang(peak))
    marks = (f'<circle cx="{f1(px)}" cy="{f1(py)}" r="4.5" fill="none" stroke="{th["ink"]}" stroke-width="1.2"/>'
             f'<text x="{cx}" y="{cy - R - 26}" class="mm" font-size="11" letter-spacing="2" text-anchor="middle" '
             f'fill="{th["ink"]}">{t("MM", "NOW")}</text>'
             f'<path d="M{cx} {cy - R - 18}V{cy - R - 6}" stroke="{th["ink"]}" stroke-width="1"/>')

    # name, wrapped by a slowly turning ring of text
    lr = 112
    circ = 2 * math.pi * lr
    ring_text = "SYSTEMS & AI ENGINEER · LOCAL-FIRST SOFTWARE · RUST · PYTHON · TYPESCRIPT · GO · "
    centre = (f'<path id="lr" d="M{cx} {cy - lr}a{lr} {lr} 0 1 1 0 {2 * lr}a{lr} {lr} 0 1 1 0 {-2 * lr}" fill="none"/>'
              f'<g class="spin"><text class="mm" font-size="12" fill="{th["dim"]}">'
              f'<textPath href="#lr" xlink:href="#lr" textLength="{f1(circ - 9)}" lengthAdjust="spacing">'
              f'{t("MM", ring_text)}</textPath></text></g>'
              f'<text class="si" font-size="62" text-anchor="middle" fill="{th["ink"]}">'
              f'<tspan x="{cx}" y="{cy - 2}">{t("SI", "Sree")}</tspan>'
              f'<tspan x="{cx}" y="{cy + 50}">{t("SI", "Varshan")}</tspan></text>')

    total = sum(counts)
    active = sum(1 for c in counts if c)
    first, last, peak_day = days[0][0], days[-1][0], days[peak][0]

    def date(d):
        return f"{d.day} {MONTHS[d.month - 1]} {d.year}"

    def month(d):
        return f"{MONTHS[d.month - 1]} {d.year}"

    def stat(x, y, anchor, big, small):
        return (f'<text x="{x}" y="{y}" class="s" font-size="54" text-anchor="{anchor}" fill="{th["ink"]}">{t("S", big)}</text>'
                f'<text x="{x}" y="{y + 28}" class="m" font-size="13" letter-spacing="1.5" text-anchor="{anchor}" '
                f'fill="{th["dim"]}">{t("M", small)}</text>')

    notes = (f'<g class="ann">'
             f'<text x="40" y="70" class="si" font-size="38" fill="{th["ink"]}">{t("SI", "Fig. 1")}</text>'
             f'<text x="40" y="98" class="m" font-size="13" letter-spacing="1.5" fill="{th["dim"]}">{t("M", "ONE SPOKE PER DAY")}</text>'
             f'<text x="40" y="118" class="m" font-size="13" letter-spacing="1.5" fill="{th["dim"]}">'
             f'{t("M", month(first) + " – " + month(last))}</text>'
             + stat(960, 80, "end", f"{total:,}", "CONTRIBUTIONS")
             + stat(40, 618, "start", str(active), f"ACTIVE DAYS OF {n}")
             + stat(960, 618, "end", f"{counts[peak]:,}", "PEAK · " + date(peak_day))
             + '</g>')

    defs = (heat_gradient("heat", cx, cy, r0, R, th["heat"]) + f'<g id="sp">{"".join(spokes)}</g>'
            '<filter id="blur" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="6"/></filter>')
    glow = (f'<g class="glow" opacity="{th["glow"]}" stroke="url(#heat)" stroke-width="5" stroke-linecap="round" '
            f'filter="url(#blur)"><use href="#sp" xlink:href="#sp"/></g>') if th["glow"] else ""
    body = (f'<g fill="none" stroke="{th["faint"]}" stroke-width="0.8" stroke-dasharray="2 4">{"".join(g for g in grooves if g.startswith("<path"))}</g>'
            + "".join(g for g in grooves if g.startswith("<text"))
            + f'<g fill="{th["faint"]}">{"".join(dots)}</g>'
            + glow
            + f'<g stroke="url(#heat)" stroke-width="1.8" stroke-linecap="round"><use href="#sp" xlink:href="#sp"/></g>'
            + "".join(months) + marks + centre + notes)
    style = (f'#sp path{{animation:grow .9s cubic-bezier(.2,.8,.2,1) backwards;animation-delay:calc(var(--i) * 3ms + .15s)}}'
             '@keyframes grow{from{stroke-dasharray:1 1;stroke-dashoffset:1}to{stroke-dasharray:1 1;stroke-dashoffset:0}}'
             '.glow{animation:fade 1.4s ease-out 1.1s backwards}.ann{animation:fade 1s ease-out .5s backwards}'
             '@keyframes fade{from{opacity:0}}'
             f'.spin{{animation:spin 150s linear infinite;transform-origin:{cx}px {cy}px}}'
             '@keyframes spin{to{transform:rotate(360deg)}}')
    label = (f"Sree Varshan's last {n} days on GitHub drawn as a ring of {n} spokes, one per day, "
             f"longer and hotter on busier days: {total:,} contributions on {active} active days.")
    return svg(W, H, label, defs, body, style, t)


# ---------------------------------------------------------------- project cards

def build_tree(files):
    root = {"children": {}}
    for path, size in files:
        parts = path.split("/")
        node = root
        for p in parts[:-1]:
            node = node["children"].setdefault(p, {"children": {}})
        node["children"][parts[-1]] = {"size": size}
    return root


def lang_summary(langs):
    total = sum(langs.values()) or 1
    top = sorted(langs.items(), key=lambda kv: -kv[1])[:2]
    parts = [f"{k.upper()} {round(100 * v / total)}%" for i, (k, v) in enumerate(top) if i == 0 or v / total >= 0.08]
    return " · ".join(parts)


def ago(when, now):
    days = (now - when).days
    if days < 1:
        return "TODAY"
    if days < 2:
        return "YESTERDAY"
    if days < 14:
        return f"{days} DAYS AGO"
    if days < 60:
        return f"{days // 7} WEEKS AGO"
    return f"{days // 30} MONTHS AGO"


def render_card(index, name, tagline, data, theme, now):
    th, t = THEMES[theme], Type()
    W, H, cx, cy = 400, 520, 200, 220
    Rt, Ls = 112, 34

    root = build_tree(data["files"])
    leaves, nodes = [], []  # nodes: (depth, parent, node)

    def walk(node, depth, parent):
        nodes.append((depth, parent, node))
        kids = node.get("children")
        if kids is None:
            node["leaf"] = len(leaves)
            leaves.append(node)
            node["first"] = node["last"] = node["leaf"]
            return
        ordered = sorted(kids.items(), key=lambda kv: ("children" not in kv[1], kv[0].lower()))
        for _, child in ordered:
            walk(child, depth + 1, node)
        if ordered:
            node["first"], node["last"] = ordered[0][1]["first"], ordered[-1][1]["last"]
        else:
            node["first"] = node["last"] = len(leaves)

    walk(root, 0, None)
    n = max(len(leaves), 1)
    depth_max = max(d for d, _, _ in nodes) or 1
    # scale to the typical file, not the outliers, so one deep folder or one huge file
    # cannot squash everything else into the centre
    leaf_depths = sorted(d for d, _, nd in nodes if "leaf" in nd) or [1]
    depth_ref = max(2, leaf_depths[int(len(leaf_depths) * 0.9)])
    sizes = sorted(lf["size"] for lf in leaves) or [1]
    size_ref = max(1, sizes[int(len(sizes) * 0.95)])
    density = min(1.0, math.sqrt(60 / n))  # big trees get fainter strokes so they stay airy

    def angle(node):
        return -90 + 360 * ((node["first"] + node["last"]) / 2 + 0.5) / n

    def radius(depth):
        return Rt * min(1.0, depth / depth_ref) ** 0.85

    spike_w = min(3.2, max(0.6, 2 * math.pi * Rt / n * 0.5))
    branch_w = min(1.4, max(0.5, spike_w * 0.45))
    by_depth, spikes = {}, []
    for depth, parent, node in nodes:
        if parent is None:
            continue
        a_c, r_c = angle(node), radius(depth)
        r_p = radius(depth - 1)
        a_p = angle(parent) if depth > 1 else a_c
        rm = (r_p + r_c) / 2
        p0, c1, c2, p3 = pt(cx, cy, r_p, a_p), pt(cx, cy, rm, a_p), pt(cx, cy, rm, a_c), pt(cx, cy, r_c, a_c)
        by_depth.setdefault(depth, []).append(
            f"M{f1(p0[0])} {f1(p0[1])}C{f1(c1[0])} {f1(c1[1])} {f1(c2[0])} {f1(c2[1])} {f1(p3[0])} {f1(p3[1])}")
        if "leaf" in node:
            q = pt(cx, cy, r_c + 3 + Ls * min(1.0, math.sqrt(node["size"] / size_ref)), a_c)
            spikes.append(f"M{f1(p3[0])} {f1(p3[1])}L{f1(q[0])} {f1(q[1])}")

    branches = "".join(f'<path class="b" style="--d:{d}" d="{"".join(segs)}"/>' for d, segs in sorted(by_depth.items()))
    spike_path = f'<path class="k" style="--d:{depth_max + 1}" d="{"".join(spikes)}"/>'
    defs = (heat_gradient("heat", cx, cy, 0, Rt + Ls, th.get("card_heat", th["heat"]))
            + '<filter id="blur" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="4"/></filter>')
    glow = (f'<g class="glow" opacity="{th["glow"] * max(0.35, density):.2f}" fill="none" stroke="url(#heat)" stroke-width="{f1(spike_w + 2.5)}" '
            f'stroke-linecap="round" filter="url(#blur)"><path d="{"".join(spikes)}"/></g>') if th["glow"] else ""

    files = len(data["files"])
    meta = f"{files:,} FILES · PUSHED {ago(data['pushed'], now)}"
    text = (f'<text x="28" y="44" class="m" font-size="15" fill="{th["dim"]}">{t("M", f"{index:02d}")}</text>'
            f'<text x="372" y="44" class="m" font-size="15" letter-spacing="1" text-anchor="end" fill="{th["dim"]}">'
            f'{t("M", lang_summary(data["langs"]))}</text>'
            f'<text x="28" y="432" class="s" font-size="48" fill="{th["ink"]}">{t("S", name)}</text>'
            f'<text x="28" y="466" class="m" font-size="17" fill="{th["dim"]}">{t("M", tagline)}</text>'
            f'<text x="28" y="496" class="m" font-size="13" letter-spacing="1.2" fill="{th["dim"]}">'
            f'{t("M", meta)}</text>')
    body = (f'<g fill="none" stroke="{th["branch"]}" stroke-width="{f1(branch_w)}" stroke-opacity="{max(0.12, 0.65 * density):.2f}" stroke-linecap="round">{branches}</g>'
            + glow
            + f'<g fill="none" stroke="url(#heat)" stroke-width="{f1(spike_w)}" stroke-linecap="round">{spike_path}</g>'
            + f'<circle cx="{cx}" cy="{cy}" r="2.5" fill="{th["ink"]}"/>' + text)
    style = (f'.b,.k{{animation:bloom 1s cubic-bezier(.2,.8,.2,1) backwards;animation-delay:calc(var(--d) * 90ms);'
             f'transform-origin:{cx}px {cy}px}}'
             '@keyframes bloom{from{opacity:0;transform:scale(.82) rotate(-8deg)}}'
             f'.glow{{animation:fade 1.2s ease-out {(depth_max + 2) * 0.09:.2f}s backwards}}@keyframes fade{{from{{opacity:0}}}}')
    label = f"{name}: {tagline}. Its {files:,} files drawn as a radial tree, one spike per file, longer for larger files."
    return svg(W, H, label, defs, body, style, t)


# ---------------------------------------------------------------- main

def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "dist")
    out.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc)
    days = contribution_days()
    for theme in THEMES:
        (out / f"year-{theme}.svg").write_text(render_year(days, theme), encoding="utf-8")
    for i, (repo, name, tagline) in enumerate(PROJECTS, 1):
        data = repo_data(repo)
        for theme in THEMES:
            (out / f"card-{repo.lower()}-{theme}.svg").write_text(
                render_card(i, name, tagline, data, theme, now), encoding="utf-8")
    print(f"wrote {len(list(out.glob('*.svg')))} files to {out}")


if __name__ == "__main__":
    main()
