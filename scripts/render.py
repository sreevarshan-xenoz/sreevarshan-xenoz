#!/usr/bin/env python3
"""Draws the animated artwork on my GitHub profile.

  year-{theme}.svg          the last 365 days of contributions as a ring, one spoke per day
  band-{theme}.svg          a kinetic type band and a ticker of my latest public commits
  card-{repo}-{theme}.svg   a featured repository's file tree, drawn radially

Every image plays a reveal when it loads and keeps some ambient motion after;
with reduced motion requested they show the finished still. Data comes from
the GitHub API using GITHUB_TOKEN.

Display type is set as outlines (HarfBuzz shaping, fontTools outlines) so it can
be animated glyph by glyph; small mono text embeds a subset font.
Fonts: Instrument Serif and IBM Plex Mono, SIL Open Font License 1.1.

Usage: GITHUB_TOKEN=... python scripts/render.py [out_dir]
"""
import base64
import datetime as dt
import html
import io
import json
import math
import os
import random
import sys
import time
import urllib.request
from pathlib import Path

import uharfbuzz as hb
from fontTools import subset
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFilter

USER = "sreevarshan-xenoz"
PROJECTS = [  # public repos only: repo, display name, tagline (under ~33 characters)
    ("xencode", "xencode", "local-first AI coding agent"),
    ("Pocketdesk", "Pocketdesk", "your desktop, on your phone"),
    ("codehalo", "CodeHalo", "a HUD for AI coding agents"),
    ("metapak", "metapak", "one TUI for every package manager"),
    ("Research-agent", "Research Agent", "research agent that writes LaTeX"),
    ("LedgerMind", "LedgerMind", "finance-ops reconciliation agent"),
]
BAND_WORDS = ["Local-first", "Rust", "Coding agents", "On-device AI", "Remote desktops", "Wayland", "Open source"]
SKIP_DIRS = {"node_modules", "target", "dist", "build", "vendor", ".git", "__pycache__", ".next", ".venv"}

THEMES = {
    "dark": {
        "ink": "#f0f6fc", "dim": "#9198a1", "faint": "#3d444d", "branch": "#6e7681",
        "hot": "#fff7ed", "trace": "#fbbf24", "spark": "#fde68a", "beam": "#fff1d6", "glow": 0.5,
        "heat": ["#7f1d1d", "#c2410c", "#f97316", "#fbbf24", "#fff7ed"],
        "molten": ["#fff7ed", "#fde68a", "#fb923c", "#c2410c"], "pour": "#fbbf24",
    },
    "light": {
        "ink": "#1f2328", "dim": "#59636e", "faint": "#d1d9e0", "branch": "#8c959f",
        "hot": "#2a0f05", "trace": "#c2410c", "spark": "#c2410c", "beam": "#7c2d12", "glow": 0,
        "heat": ["#fdba74", "#f97316", "#ea580c", "#9a3412", "#431407"],
        "card_heat": ["#f97316", "#ea580c", "#c2410c", "#7c2d12", "#431407"],  # thin strokes need deeper ink
        "molten": ["#7c2d12", "#c2410c", "#ea580c", "#fb923c"], "pour": "#ea580c",
    },
}

FONT_DIR = Path(__file__).parent / "fonts"
SERIF = "instrument-serif-latin-400-normal.woff2"
SERIF_ITALIC = "instrument-serif-latin-400-italic.woff2"
MONO_FILES = {"M": "ibm-plex-mono-latin-400-normal.woff2", "MM": "ibm-plex-mono-latin-500-normal.woff2"}
MONTHS = "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split()

OUT = "cubic-bezier(.16,1,.3,1)"     # fast start, long settle
INOUT = "cubic-bezier(.65,0,.35,1)"

# Shared keyframes. Every element's resting style is its finished state, so with
# animation switched off (reduced motion) each image is a complete still.
BASE_CSS = (
    "@keyframes fade{from{opacity:0}}"
    "@keyframes rise{from{opacity:0;transform:translateY(16px)}}"
    "@keyframes grow{from{stroke-dasharray:1 2;stroke-dashoffset:1.02}to{stroke-dasharray:1 2;stroke-dashoffset:0}}"
    "@keyframes ping{0%{opacity:.9;transform:scale(.3)}100%{opacity:0;transform:scale(4.5)}}"
    "@keyframes spin{to{transform:rotate(360deg)}}"
    "@keyframes type{from{transform:scaleX(0)}}"
    "@keyframes odo{from{transform:translateY(0)}}"
    ".fd{animation:fade .8s ease-out var(--t) backwards}"
    ".tw{transform-box:fill-box;transform-origin:0 0;animation-name:type;animation-fill-mode:backwards}"
    ".odo{animation-name:odo;animation-timing-function:cubic-bezier(.12,.8,.18,1);animation-fill-mode:backwards}"
    f".ping{{opacity:0;transform-box:fill-box;transform-origin:center;animation:ping 1.3s {OUT} var(--t)}}"
    # .run is the animated copy (masks, spinning strips) and removes itself at --e;
    # .done is the plain copy that takes over, so finished effects stop costing anything.
    # (An element that rests at display:none never starts its animations, so .run rests visible.)
    ".run{animation:fin var(--e) linear forwards}@keyframes fin{0%,99.9%{display:inline}100%{display:none}}"
    ".done{animation:off var(--e) linear backwards}@keyframes off{from,to{display:none}}"
)
REDUCED = "@media (prefers-reduced-motion:reduce){*{animation:none!important}}"


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


def recent_commits(limit=8):
    """Latest commits I authored on my public repos (this endpoint only lists public ones)."""
    found = []
    for r in api(f"users/{USER}/repos?sort=pushed&per_page=12&type=owner"):
        if r["fork"] or r.get("private") or r["name"].lower() == USER.lower():
            continue
        try:
            commits = api(f"repos/{USER}/{r['name']}/commits?per_page=4")
        except OSError:
            continue
        mine = [c for c in commits if (c.get("author") or {}).get("login") == USER and len(c["parents"]) == 1][:2]
        for c in mine:
            msg = " ".join(c["commit"]["message"].splitlines()[0].split())
            msg = "".join(ch for ch in msg if ch.isprintable())
            if len(msg) > 54:
                msg = msg[:53].rstrip() + "…"
            when = dt.datetime.fromisoformat(c["commit"]["author"]["date"].replace("Z", "+00:00"))
            found.append((when, r["name"], msg))
        if len(found) >= limit:
            break
    found.sort(reverse=True)
    return found[:limit]


# ---------------------------------------------------------------- type

def f1(v):
    s = f"{v:.1f}"
    s = s[:-2] if s.endswith(".0") else s
    return "0" if s == "-0" else s


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class Face:
    """A font for display type: HarfBuzz for shaping and kerning, fontTools for outlines."""

    def __init__(self, file):
        tt = TTFont(FONT_DIR / file)
        tt.flavor = None
        raw = io.BytesIO()
        tt.save(raw)
        self.hb = hb.Font(hb.Face(raw.getvalue()))
        self.upem = tt["head"].unitsPerEm
        self.order = tt.getGlyphOrder()
        self.glyphs = tt.getGlyphSet()
        self.cmap = tt.getBestCmap()
        self.hmtx = tt["hmtx"]
        self.key = "si" if "italic" in file else "sn"

    def shape(self, text, size):
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        hb.shape(self.hb, buf, {"kern": True, "liga": True})
        s, x, out = size / self.upem, 0, []
        for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
            out.append((self.order[info.codepoint], (x + pos.x_offset) * s))
            x += pos.x_advance
        return out, x * s

    def path(self, glyph, x, y, size):
        s = size / self.upem
        pen = SVGPathPen(self.glyphs, ntos=f1)
        self.glyphs[glyph].draw(TransformPen(pen, (s, 0, 0, -s, x, y)))
        return pen.getCommands()

    def units(self, glyph):
        pen = SVGPathPen(self.glyphs, ntos=lambda v: str(round(v)))
        self.glyphs[glyph].draw(pen)
        return pen.getCommands()

    def advance(self, ch, size):
        return self.hmtx[self.cmap[ord(ch)]][0] * size / self.upem

    def run(self, text, x, y, size, anchor="start"):
        """Glyph outlines for a line of text: [(path, left x)], width, start x."""
        glyphs, width = self.shape(text, size)
        x0 = x - width if anchor == "end" else x - width / 2 if anchor == "middle" else x
        out = []
        for g, gx in glyphs:
            d = self.path(g, x0 + gx, y, size)
            if d:
                out.append((d, x0 + gx))
        return out, width, x0


class Mono:
    """Small text stays real <text> in an embedded IBM Plex Mono, subset to what is drawn."""

    def __init__(self):
        self.used = {k: set() for k in MONO_FILES}

    def __call__(self, family, s):
        self.used[family].update(s)
        return esc(s)

    def css(self):
        out = []
        for fam, file in MONO_FILES.items():
            if not self.used[fam]:
                continue
            font = TTFont(FONT_DIR / file)
            opts = subset.Options()
            opts.flavor = "woff2"
            sub = subset.Subsetter(opts)
            sub.populate(text="".join(self.used[fam] | {" "}))
            sub.subset(font)
            buf = io.BytesIO()
            font.flavor = "woff2"
            font.save(buf)
            b64 = base64.b64encode(buf.getvalue()).decode()
            out.append(f"@font-face{{font-family:'{fam}';src:url(data:font/woff2;base64,{b64}) format('woff2')}}"
                       f".{fam.lower()}{{font-family:'{fam}',ui-monospace,monospace}}")
        return "".join(out)


class Doc:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.defs, self.css, self.body = [], [], []
        self.mono = Mono()
        self._n = 0
        self._glyphs = set()

    def uid(self, prefix):
        self._n += 1
        return f"{prefix}{self._n}"

    def glyph(self, face, glyph):
        gid = f"{face.key}-{glyph}".replace(".", "_")
        if gid not in self._glyphs:
            self._glyphs.add(gid)
            self.defs.append(f'<path id="{gid}" d="{face.units(glyph)}"/>')
        return gid

    def render(self, label):
        return (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
                f'width="{self.w}" height="{self.h}" viewBox="0 0 {self.w} {self.h}" role="img" '
                f'aria-label="{html.escape(label)}"><style>{self.mono.css()}{BASE_CSS}{"".join(self.css)}{REDUCED}</style>'
                f'<defs>{"".join(self.defs)}</defs>{"".join(self.body)}</svg>\n')


def typed(doc, text, x, y, size, fill, start, ls=0.0, family="M", anchor="start", cps=48):
    """Mono text that types itself out, one character per step."""
    adv = 0.6 * size + ls
    n = max(len(text), 1)
    w = n * adv
    x0 = x - w if anchor == "end" else x
    mid = doc.uid("tm")
    box = f'x="{f1(x0 - 2)}" y="{f1(y - size * 1.1)}" width="{f1(w + 4)}" height="{f1(size * 1.6)}"'
    doc.defs.append(f'<mask id="{mid}" maskUnits="userSpaceOnUse" {box}><rect class="tw" {box} fill="#fff" '
                    f'style="animation-duration:{n / cps:.2f}s;animation-delay:{start:.2f}s;animation-timing-function:steps({n})"/></mask>')
    attrs = f'x="{f1(x0)}" y="{f1(y)}" font-size="{size}" letter-spacing="{ls}" fill="{fill}" style="--e:{start + n / cps + 0.05:.2f}s"'
    body = doc.mono(family, text)
    return (f'<text class="{family.lower()} run" {attrs} mask="url(#{mid})">{body}</text>'
            f'<text class="{family.lower()} done" {attrs}>{body}</text>')


def odometer(doc, face, text, x, y, size, anchor, start, fill):
    """A number whose digits spin into place like a mechanical counter."""
    advs = [face.advance(ch, size) for ch in text]
    left = x - sum(advs) if anchor == "end" else x
    s = size / face.upem
    line = size * 1.08
    digits = [i for i, ch in enumerate(text) if ch.isdigit()]
    end = start + (len(digits) - 1) * 0.06 + 1.5 + (len(digits) - 1) * 0.15 + 0.05
    still = "".join(f'<path d="{face.path(face.cmap[ord(ch)], left + sum(advs[:i]), y, size)}"/>' for i, ch in enumerate(text))
    out, cx = [], left
    for i, ch in enumerate(text):
        w = advs[i]
        if ch.isdigit():
            col = digits.index(i)
            final = (1 + col) * 10 + int(ch)  # columns further right spin further
            mid = doc.uid("om")
            top, bottom = y - size * 0.82, y + size * 0.2
            box = f'x="{f1(cx - 4)}" y="{f1(top)}" width="{f1(w + 8)}" height="{f1(bottom - top)}"'
            doc.defs.append(f'<mask id="{mid}" maskUnits="userSpaceOnUse" {box}><rect {box} fill="url(#feather)"/></mask>')
            strip = []
            for j in range(final + 1):
                dch = str(j % 10)
                gx = cx + (w - face.advance(dch, size)) / 2
                gid = doc.glyph(face, face.cmap[ord(dch)])
                strip.append(f'<use href="#{gid}" xlink:href="#{gid}" transform="translate({f1(gx)} {f1(y + j * line)}) scale({s:.4f} {-s:.4f})"/>')
            out.append(f'<g mask="url(#{mid})"><g class="odo" fill="{fill}" style="transform:translateY({f1(-final * line)}px);'
                       f'animation-duration:{1.5 + col * 0.15:.2f}s;animation-delay:{start + col * 0.06:.2f}s">{"".join(strip)}</g></g>')
        else:
            d = face.path(face.cmap[ord(ch)], cx, y, size)
            if d:
                out.append(f'<path class="fd" style="--t:{start + 0.3:.2f}s" d="{d}" fill="{fill}"/>')
        cx += w
    return (f'<g class="fd" style="--t:{start:.2f}s"><g class="run" style="--e:{end:.2f}s">{"".join(out)}</g>'
            f'<g class="done" style="--e:{end:.2f}s" fill="{fill}">{still}</g></g>')


def pt(cx, cy, r, deg):
    a = math.radians(deg)
    return cx + r * math.cos(a), cy + r * math.sin(a)


def sector(cx, cy, r1, r2, a1, a2):
    (x1, y1), (x2, y2) = pt(cx, cy, r1, a1), pt(cx, cy, r2, a1)
    (x3, y3), (x4, y4) = pt(cx, cy, r2, a2), pt(cx, cy, r1, a2)
    return (f"M{f1(x1)} {f1(y1)}L{f1(x2)} {f1(y2)}A{f1(r2)} {f1(r2)} 0 0 1 {f1(x3)} {f1(y3)}"
            f"L{f1(x4)} {f1(y4)}A{f1(r1)} {f1(r1)} 0 0 0 {f1(x1)} {f1(y1)}Z")


def wedge(cx, cy, r1, r2, lead, span, slices, color, peak):
    """A beam: bright at its leading edge, fading out behind it."""
    out = []
    for k in range(slices):
        a2, a1 = lead - span * k / slices, lead - span * (k + 1) / slices
        op = peak * (1 - k / slices) ** 1.8
        out.append(f'<path d="{sector(cx, cy, r1, r2, a1, a2 + 0.2)}" fill="{color}" fill-opacity="{op:.3f}"/>')
    return "".join(out)


def heat_gradient(gid, cx, cy, r_in, r_out, colors):
    """Radial gradient so a stroke gets hotter the further it reaches from the centre."""
    span = r_out - r_in
    stops = [(r_in, colors[0]), (r_in + span * 0.3, colors[1]), (r_in + span * 0.58, colors[2]),
             (r_in + span * 0.82, colors[3]), (r_out, colors[4])]
    s = "".join(f'<stop offset="{r / r_out:.3f}" stop-color="{c}"/>' for r, c in stops)
    return f'<radialGradient id="{gid}" gradientUnits="userSpaceOnUse" cx="{cx}" cy="{cy}" r="{f1(r_out)}">{s}</radialGradient>'


FEATHER = ('<linearGradient id="feather" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity="0"/>'
           '<stop offset=".16" stop-color="#fff"/><stop offset=".84" stop-color="#fff"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>')


def hex_rgb(c):
    return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))


def glow_image(lines, w, h, width=5.0, sigma=6.0, scale=0.5, gain=1.7):
    """A blurred glow rendered once as a small WebP, so the browser composites a picture
    instead of running a blur filter on every animation frame."""
    W, H = round(w * scale), round(h * scale)
    rgb, alpha = Image.new("RGB", (W, H)), Image.new("L", (W, H))
    draw_rgb, draw_a = ImageDraw.Draw(rgb), ImageDraw.Draw(alpha)
    lw = max(1, round(width * scale))
    for x1, y1, x2, y2, color in lines:
        seg = [(x1 * scale, y1 * scale), (x2 * scale, y2 * scale)]
        draw_rgb.line(seg, fill=color, width=lw)
        draw_a.line(seg, fill=255, width=lw)
    alpha = alpha.filter(ImageFilter.GaussianBlur(sigma * scale)).point(lambda v: min(255, int(v * gain)))
    for _ in range(3):  # spread colour outwards so the soft edges keep their hue
        rgb = rgb.filter(ImageFilter.MaxFilter(7))
    rgb = rgb.filter(ImageFilter.GaussianBlur(2))
    rgb.putalpha(alpha)
    buf = io.BytesIO()
    rgb.save(buf, "WEBP", quality=72, method=6)
    return base64.b64encode(buf.getvalue()).decode()


def circle_path(cx, cy, r):
    return f"M{f1(cx)} {f1(cy - r)}A{f1(r)} {f1(r)} 0 1 1 {f1(cx)} {f1(cy + r)}A{f1(r)} {f1(r)} 0 1 1 {f1(cx)} {f1(cy - r)}"


def day(d):
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


# ---------------------------------------------------------------- the year ring

def render_year(days, theme, serif, italic):
    th = THEMES[theme]
    doc = Doc(1000, 700)
    cx, cy = 500, 350
    r0, L, gap = 132, 168, 8
    R = r0 + L
    n = len(days)
    counts = [c for _, c in days]
    peak = max(range(n), key=lambda i: counts[i])
    top = math.log1p(counts[peak]) or 1
    T0, TS = 0.6, 1.5   # the eruption: a beam sweeps once and each day bursts out as it passes
    S, P = 4.4, 14.0    # afterwards a slower beam keeps circling, one turn every P seconds
    a_start = -90 + gap / 2
    rng = random.Random(7)

    def ang(i):
        return a_start + (360 - gap) * (i + 0.5) / n

    def reach(c):
        return 6 + (L - 6) * math.log1p(c) / top

    def born(i):
        return T0 + TS * (i + 0.5) / n

    def passes(a):
        return S + P * (((a + 90) % 360) / 360)

    # spokes: a heat layer that stays, and a white-hot copy that cools away
    stops = [(r0 + L * f, hex_rgb(c)) for f, c in zip((0, 0.3, 0.58, 0.82, 1), th["heat"])]

    def heat_at(r):
        for (ra, ca), (rb, cb) in zip(stops, stops[1:]):
            if r <= rb:
                k = (r - ra) / (rb - ra)
                return tuple(round(a + (b - a) * k) for a, b in zip(ca, cb))
        return stops[-1][1]

    spokes, hots, dots, glow_lines = [], [], [], []
    for i, (_, c) in enumerate(days):
        a = ang(i)
        if c:
            (x1, y1), (x2, y2) = pt(cx, cy, r0, a), pt(cx, cy, r0 + reach(c), a)
            d = f'd="M{f1(x1)} {f1(y1)}L{f1(x2)} {f1(y2)}" pathLength="1"'
            spokes.append(f'<path {d} style="--t:{born(i):.3f}s"/>')
            hots.append(f'<path {d} style="--t:{born(i):.3f}s;--h:{passes(a):.2f}s"/>')
            for k in range(5):
                ra, rb = r0 + reach(c) * k / 5, r0 + reach(c) * (k + 1) / 5
                (gx1, gy1), (gx2, gy2) = pt(cx, cy, ra, a), pt(cx, cy, rb, a)
                glow_lines.append((gx1, gy1, gx2, gy2, heat_at((ra + rb) / 2)))
        else:
            x, y = pt(cx, cy, r0 + 1.5, a)
            dots.append(f'<circle cx="{f1(x)}" cy="{f1(y)}" r="1.1" style="--t:{born(i):.3f}s"/>')

    grooves, groove_labels = [], []
    for k, v in enumerate((1, 10, 100)):
        if v > counts[peak]:
            continue
        r = r0 + reach(v)
        (sx, sy), (ex, ey) = pt(cx, cy, r, a_start), pt(cx, cy, r, 270 - gap / 2)
        grooves.append(f'<path class="gv" style="--t:{0.35 + k * 0.12:.2f}s" d="M{f1(sx)} {f1(sy)}A{f1(r)} {f1(r)} 0 1 1 {f1(ex)} {f1(ey)}"/>')
        groove_labels.append(f'<text class="m fd" style="--t:{0.5 + k * 0.12:.2f}s" x="{cx}" y="{f1(cy - r)}" font-size="10" text-anchor="middle" '
                             f'dominant-baseline="central" fill="{th["dim"]}">{doc.mono("M", str(v))}</text>')

    months = []
    for i, (d, _) in enumerate(days):
        a = ang(i) - (360 - gap) / n / 2
        if d.day != 1 or min(a + 90, 270 - a) < 9:  # leave the seam to the NOW marker
            continue
        (tx1, ty1), (tx2, ty2) = pt(cx, cy, r0 - 12, a), pt(cx, cy, r0 - 4, a)
        months.append(f'<path class="fd" style="--t:{born(i):.2f}s" d="M{f1(tx1)} {f1(ty1)}L{f1(tx2)} {f1(ty2)}" stroke="{th["faint"]}"/>')
        lx, ly = pt(cx, cy, R + 34, a)
        name = MONTHS[d.month - 1] + (f" {d.year}" if d.month == 1 else "")
        months.append(f'<text class="m ml" style="--t:{born(i):.2f}s;--g:{passes(a):.2f}s" x="{f1(lx)}" y="{f1(ly)}" font-size="12" '
                      f'letter-spacing="1.5" text-anchor="middle" dominant-baseline="central" fill="{th["dim"]}">{doc.mono("M", name)}</text>')

    # pings: the peak lands with a big one; the busiest days blip whenever the beam finds them
    px, py = pt(cx, cy, r0 + reach(counts[peak]) + 9, ang(peak))
    pings = [f'<circle class="fd" style="--t:{born(peak):.2f}s" cx="{f1(px)}" cy="{f1(py)}" r="4.5" fill="none" stroke="{th["ink"]}" stroke-width="1.2"/>',
             f'<circle class="ping" style="--t:{born(peak):.2f}s" cx="{f1(px)}" cy="{f1(py)}" r="6" fill="none" stroke="{th["trace"]}" stroke-width="1.5"/>']
    for i in sorted(range(n), key=lambda i: -counts[i])[:6]:
        x, y = pt(cx, cy, r0 + reach(counts[i]) + 2, ang(i))
        pings.append(f'<circle class="ap" style="--g:{passes(ang(i)) - 0.05:.2f}s" cx="{f1(x)}" cy="{f1(y)}" r="4" fill="none" '
                     f'stroke="{th["trace"]}" stroke-width="1.2"/>')

    # embers drifting off the hottest days
    sparks = []
    hot_days = sorted(range(n), key=lambda i: -counts[i])[:26]
    for k in range(34):
        i = hot_days[k % len(hot_days)]
        a = ang(i) + rng.uniform(-9, 9)
        x, y = pt(cx, cy, r0 + reach(counts[i]) + 3, ang(i))
        dist = rng.uniform(26, 70)
        dx, dy = pt(0, 0, dist, a)
        mx, my = pt(0, 0, dist * 0.5, a + rng.uniform(-14, 14))
        sparks.append(f'<circle cx="{f1(x)}" cy="{f1(y)}" r="{rng.uniform(0.7, 1.7):.1f}" style="--dx:{f1(dx)}px;--dy:{f1(dy)}px;'
                      f'--mx:{f1(mx)}px;--my:{f1(my)}px;animation-duration:{rng.uniform(2.6, 5.6):.2f}s;'
                      f'animation-delay:{3.6 + rng.uniform(0, 6):.2f}s"/>')

    # the name: outlines trace in, molten fill pours up through them, a glint passes now and then
    size = 62
    line1, w1, x1 = italic.run("Sree", cx, cy - 2, size, "middle")
    line2, w2, x2 = italic.run("Varshan", cx, cy + 50, size, "middle")
    name_paths = "".join(f'<path d="{d}"/>' for d, _ in line1 + line2)
    trace_paths = "".join(f'<path d="{d}" pathLength="1" style="--k:{k}"/>' for k, (d, _) in enumerate(line1 + line2))
    nx0, nx1 = min(x1, x2) - 12, max(x1 + w1, x2 + w2) + 12
    ny0, ny1 = cy - 2 - size * 0.82, cy + 50 + size * 0.28
    flood_h = ny1 - ny0 + 30
    glint_x = nx1 - nx0 + 200

    # corner notes
    total, active = sum(counts), sum(1 for c in counts if c)
    fig, _, _ = italic.run("Fig. 1", 40, 70, 38)
    span = f"{MONTHS[days[0][0].month - 1]} {days[0][0].year} – {MONTHS[days[-1][0].month - 1]} {days[-1][0].year}"
    notes = ["".join(f'<path class="fg" style="--k:{k}" d="{d}" fill="{th["ink"]}"/>' for k, (d, _) in enumerate(fig)),
             typed(doc, "ONE SPOKE PER DAY", 40, 98, 13, th["dim"], 2.5, 1.5),
             typed(doc, span, 40, 118, 13, th["dim"], 2.8, 1.5),
             odometer(doc, serif, f"{total:,}", 960, 80, 54, "end", 2.35, th["ink"]),
             typed(doc, "CONTRIBUTIONS", 960, 108, 13, th["dim"], 3.4, 1.5, anchor="end"),
             odometer(doc, serif, str(active), 40, 618, 54, "start", 2.5, th["ink"]),
             typed(doc, f"ACTIVE DAYS OF {n}", 40, 646, 13, th["dim"], 3.55, 1.5),
             odometer(doc, serif, f"{counts[peak]:,}", 960, 618, 54, "end", 2.65, th["ink"]),
             typed(doc, "PEAK · " + day(days[peak][0]), 960, 646, 13, th["dim"], 3.7, 1.5, anchor="end")]

    lr = 112
    ring_text = "SYSTEMS & AI ENGINEER · LOCAL-FIRST SOFTWARE · RUST · PYTHON · TYPESCRIPT · GO · "
    b1, b2 = r0 - 6, R + 14
    (lx1, ly1), (lx2, ly2) = pt(cx, cy, b1, a_start), pt(cx, cy, b2, a_start)

    doc.defs += [
        heat_gradient("heat", cx, cy, r0, R, th["heat"]), FEATHER,
        f'<g id="nm">{name_paths}</g>',
        '<filter id="blur" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="6"/></filter>',
        f'<radialGradient id="halo"><stop offset="0" stop-color="{th["hot"]}"/><stop offset=".18" stop-color="{th["trace"]}" stop-opacity=".55"/>'
        f'<stop offset=".5" stop-color="{th["trace"]}" stop-opacity=".12"/><stop offset="1" stop-color="{th["trace"]}" stop-opacity="0"/></radialGradient>',
        '<linearGradient id="floodg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset=".12" stop-color="#fff"/></linearGradient>',
        f'<linearGradient id="glintg" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="{th["pour"]}" stop-opacity="0"/>'
        f'<stop offset=".5" stop-color="{th["pour"]}"/><stop offset="1" stop-color="{th["pour"]}" stop-opacity="0"/></linearGradient>',
        f'<mask id="flood" maskUnits="userSpaceOnUse" x="{f1(nx0)}" y="{f1(ny0 - 30)}" width="{f1(nx1 - nx0)}" height="{f1(flood_h)}">'
        f'<rect class="fl" x="{f1(nx0)}" y="{f1(ny0 - 30)}" width="{f1(nx1 - nx0)}" height="{f1(flood_h)}" fill="url(#floodg)"/></mask>',
        f'<clipPath id="nmc">{name_paths}</clipPath>',
        f'<path id="lr" d="{circle_path(cx, cy, lr)}" fill="none"/>',
    ]

    doc.body = [
        # ignition
        f'<circle class="ch" cx="{cx}" cy="{cy}" r="90" fill="url(#halo)"/>',
        f'<circle class="cs" cx="{cx}" cy="{cy}" r="3.5" fill="{th["hot"]}"/>',
        f'<path class="ir" d="{circle_path(cx, cy, r0 - 4)}" pathLength="1" fill="none" stroke="{th["faint"]}" stroke-width="1"/>',
        f'<g fill="none" stroke="{th["faint"]}" stroke-width="0.8" stroke-dasharray="2 4">{"".join(grooves)}</g>',
        "".join(groove_labels),
        f'<g class="dz" fill="{th["faint"]}">{"".join(dots)}</g>',
        # the intro scanner makes one fast turn while the days burst out behind it
        f'<g class="beam0">{wedge(cx, cy, b1, b2, a_start, 30, 10, th["beam"], 0.16)}'
        f'<path d="M{f1(lx1)} {f1(ly1)}L{f1(lx2)} {f1(ly2)}" stroke="{th["beam"]}" stroke-width="1.4" stroke-linecap="round"/></g>',
        (f'<image class="glow" opacity="{th["glow"] * 1.1:.2f}" x="0" y="0" width="1000" height="700" '
         f'href="data:image/webp;base64,{glow_image(glow_lines, 1000, 700)}"/>') if th["glow"] else "",
        f'<g id="sp" stroke="url(#heat)" stroke-width="1.8" stroke-linecap="round">{"".join(spokes)}</g>',
        f'<g id="hot" stroke="{th["hot"]}" stroke-width="1.8" stroke-linecap="round">{"".join(hots)}</g>',
        # the slow beam; each spoke flashes on its own as it passes (see #hot)
        f'<g class="sweep">{wedge(cx, cy, b1, b2, -90, 40, 12, th["beam"], 0.06)}</g>',
        "".join(months),
        f'<g class="fd" style="--t:.5s"><text x="{cx}" y="{cy - R - 26}" class="mm" font-size="11" letter-spacing="2" text-anchor="middle" '
        f'fill="{th["ink"]}">{doc.mono("MM", "NOW")}</text><path d="M{cx} {cy - R - 18}V{cy - R - 6}" stroke="{th["ink"]}"/></g>',
        f'<g class="ember" fill="{th["spark"]}">{"".join(sparks)}</g>',
        "".join(pings),
        f'<g class="rt"><g class="spin"><text class="mm" font-size="12" fill="{th["dim"]}"><textPath href="#lr" xlink:href="#lr" '
        f'textLength="{f1(2 * math.pi * lr - 9)}" lengthAdjust="spacing">{doc.mono("MM", ring_text)}</textPath></text></g></g>',
        # the name
        '<use class="nmglow" href="#nm" xlink:href="#nm" fill="#f97316" filter="url(#blur)"/>' if th["glow"] else "",
        f'<g class="run" style="--e:3.9s" mask="url(#flood)"><use class="nmf" href="#nm" xlink:href="#nm" fill="{th["ink"]}"/></g>',
        f'<use class="done" style="--e:3.9s" href="#nm" xlink:href="#nm" fill="{th["ink"]}"/>',
        f'<g class="trace" fill="none" stroke="{th["trace"]}" stroke-width="1.1">{trace_paths}</g>',
        f'<g clip-path="url(#nmc)"><path class="gl" d="M{f1(nx0 - 90)} {f1(ny0 - 10)}h46l-50 {f1(ny1 - ny0 + 20)}h-46z" fill="url(#glintg)"/></g>',
        f'<circle class="sw" cx="{cx}" cy="{cy}" r="{r0}" fill="none" stroke="{th["trace"]}" stroke-width="1.4"/>',
        f'<circle class="sw sw2" cx="{cx}" cy="{cy}" r="{r0}" fill="none" stroke="{th["trace"]}" stroke-width=".8"/>',
    ] + notes

    doc.css.append(
        f"#sp path{{animation:grow .6s {OUT} var(--t) backwards}}"
        f"#hot path{{opacity:0;visibility:hidden;animation-name:grow,cool,hit;animation-duration:.6s,1.5s,{P}s;"
        f"animation-timing-function:{OUT},ease-out,linear;animation-delay:var(--t),var(--t),var(--h);"
        "animation-iteration-count:1,1,infinite;animation-fill-mode:backwards,backwards,none}"
        "@keyframes cool{from{opacity:1;stroke-width:3.6px;visibility:visible}to{opacity:0;stroke-width:1.8px;visibility:hidden}}"
        "@keyframes hit{0%{opacity:.85;visibility:visible}10%{opacity:0;visibility:hidden}100%{opacity:0;visibility:hidden}}"
        ".dz circle{animation:fade .5s ease-out var(--t) backwards}"
        f".cs{{opacity:0;transform-box:fill-box;transform-origin:center;animation:spark 1.3s {OUT} .05s}}"
        "@keyframes spark{0%{opacity:0;transform:scale(0)}12%{opacity:1;transform:scale(2.6)}55%{opacity:1;transform:scale(1)}100%{opacity:0;transform:scale(.4)}}"
        f".ch{{opacity:0;transform-box:fill-box;transform-origin:center;animation:halo 1.2s {OUT} .05s}}"
        "@keyframes halo{0%{opacity:0;transform:scale(.05)}14%{opacity:1;transform:scale(.6)}100%{opacity:0;transform:scale(1.5)}}"
        f".ir{{animation:grow 1s {INOUT} .25s backwards}}"
        f".gv{{transform-origin:{cx}px {cy}px;animation:groove 1.4s {OUT} var(--t) backwards}}"
        "@keyframes groove{from{opacity:0;transform:rotate(-50deg)}}"
        f".beam0{{opacity:0;transform-origin:{cx}px {cy}px;animation-name:turn,beam;animation-duration:{TS}s,{TS}s;"
        f"animation-timing-function:linear,linear;animation-delay:{T0}s,{T0}s}}"
        f"@keyframes turn{{to{{transform:rotate({360 - gap}deg)}}}}"
        "@keyframes beam{0%{opacity:0}6%{opacity:1}88%{opacity:1}100%{opacity:0}}"
        ".glow{animation:fade 1.8s ease-out 1.9s backwards}"
        f".sweep{{opacity:0;transform-origin:{cx}px {cy}px;animation-name:spin,show;animation-duration:{P}s,1.4s;"
        f"animation-timing-function:linear,ease-out;animation-delay:{S}s,{S}s;animation-iteration-count:infinite,1;animation-fill-mode:none,forwards}}"
        "@keyframes show{to{opacity:1}}"
        f".ml{{animation-name:fade,glint;animation-duration:.6s,{P}s;animation-timing-function:ease-out,linear;"
        "animation-delay:var(--t),var(--g);animation-iteration-count:1,infinite;animation-fill-mode:backwards,none}"
        f"@keyframes glint{{0%{{fill:{th['ink']}}}9%{{fill:{th['dim']}}}100%{{fill:{th['dim']}}}}}"
        f".ap{{opacity:0;transform-box:fill-box;transform-origin:center;animation:aping {P}s linear var(--g) infinite}}"
        "@keyframes aping{0%{opacity:.95;transform:scale(.4)}7%{opacity:0;transform:scale(3.6)}100%{opacity:0;transform:scale(3.6)}}"
        ".ember circle{opacity:0;animation-name:ember;animation-timing-function:ease-out;animation-iteration-count:infinite}"
        "@keyframes ember{0%{opacity:0;transform:translate(0,0)}15%{opacity:1}55%{transform:translate(var(--mx),var(--my))}"
        "100%{opacity:0;transform:translate(var(--dx),var(--dy))}}"
        ".rt{animation:fade 1.4s ease-out 1.3s backwards}"
        f".spin{{transform-origin:{cx}px {cy}px;animation:spin 150s steps(1800) infinite}}"  # 12 steps a second is plenty this slow
        f".trace path{{animation:grow 1.2s {INOUT} backwards;animation-delay:calc(.95s + var(--k) * 70ms)}}"
        ".trace{opacity:0;animation:trace 3.3s linear .95s}"
        "@keyframes trace{0%{opacity:1}62%{opacity:1}100%{opacity:0}}"
        f".fl{{animation:flood 1.1s {INOUT} 1.85s backwards}}"
        f"@keyframes flood{{from{{transform:translateY({f1(flood_h)}px)}}}}"
        ".nmf{animation:pour 2s ease-out 1.85s backwards}"
        f"@keyframes pour{{from{{fill:{th['pour']}}}}}"
        ".nmglow{opacity:0;animation:flare 2.2s ease-out 1.9s backwards,fin 4.1s linear forwards}"  # removed once done, so its blur stops costing
        "@keyframes flare{0%{opacity:0}30%{opacity:.75}100%{opacity:0}}"
        f".gl{{transform:translateX({f1(glint_x)}px);animation:sheen 9s {INOUT} 3.7s infinite}}"
        f"@keyframes sheen{{0%{{transform:translateX(0);visibility:visible}}13%{{transform:translateX({f1(glint_x)}px);visibility:hidden}}"
        f"100%{{transform:translateX({f1(glint_x)}px);visibility:hidden}}}}"
        f".sw{{opacity:0;transform-box:fill-box;transform-origin:center;animation:shock 1.9s {OUT} 2.6s}}"
        ".sw2{animation-delay:2.78s}"
        "@keyframes shock{0%{opacity:.7;transform:scale(1)}100%{opacity:0;transform:scale(4.6)}}"
        f".fg{{animation:rise .8s {OUT} backwards;animation-delay:calc(2.2s + var(--k) * 45ms)}}"
    )
    label = (f"Sree Varshan's last {n} days on GitHub drawn as a glowing ring of {n} spokes, one per day, "
             f"longer and hotter on busier days: {total:,} contributions on {active} active days.")
    return doc.render(label)


# ---------------------------------------------------------------- the kinetic band

def render_band(commits, theme, italic, now):
    th = THEMES[theme]
    doc = Doc(1000, 220)
    size, base = 76, 128

    # row one: big outlined words that turn molten as they cross the spotlight
    parts, x = [], 0.0
    for w in BAND_WORDS:
        glyphs, width, _ = italic.run(w, x, base, size)
        parts += [f'<path d="{d}"/>' for d, _ in glyphs]
        x += width + 30
        parts.append(f'<circle cx="{f1(x)}" cy="{f1(base - size * 0.26)}" r="4.5"/>')
        x += 30
    wc = x
    doc.defs += [
        f'<g id="r1">{"".join(parts)}</g>',
        f'<linearGradient id="molten" gradientUnits="userSpaceOnUse" x1="0" y1="{f1(base - size * 0.75)}" x2="0" y2="{f1(base + size * 0.2)}">'
        + "".join(f'<stop offset="{o}" stop-color="{c}"/>' for o, c in zip((0, 0.35, 0.7, 1), th["molten"])) + "</linearGradient>",
        '<radialGradient id="spotg"><stop offset="0" stop-color="#fff"/><stop offset=".55" stop-color="#fff" stop-opacity=".85"/>'
        '<stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient>',
        '<mask id="spot" maskUnits="userSpaceOnUse" x="0" y="0" width="1000" height="220"><ellipse cx="500" cy="104" rx="250" ry="120" fill="url(#spotg)"/></mask>',
        '<linearGradient id="edgeg"><stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset=".1" stop-color="#fff"/>'
        '<stop offset=".9" stop-color="#fff"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>',
        '<mask id="edge" maskUnits="userSpaceOnUse" x="0" y="0" width="1000" height="220"><rect width="1000" height="220" fill="url(#edgeg)"/></mask>',
    ]
    uses = f'<use href="#r1" xlink:href="#r1"/><use href="#r1" xlink:href="#r1" x="{f1(wc)}"/>'
    row1 = (f'<g class="r1in"><g class="mq1" fill="none" stroke="{th["dim"]}" stroke-width="1" stroke-opacity=".75">{uses}</g>'
            f'<g mask="url(#spot)"><g class="mq1" fill="url(#molten)">{uses}</g></g></g>')

    # row two: a ticker of my latest public commits, newest first, running the other way
    adv = 0.6 * 13 + 1.2
    items = [(name.upper(), msg, f"{when.day} {MONTHS[when.month - 1]}") for when, name, msg in commits]
    if not items:
        items = [(name.upper(), tagline, "") for _, name, tagline in PROJECTS]
    texts, x = [], 0.0
    for repo, msg, date in items:
        for text, fam, fill in ((repo, "MM", th["ink"]), (msg, "M", th["dim"]), (date, "M", th["dim"])):
            if text:
                texts.append(f'<text x="{f1(x)}" y="186" class="{fam.lower()}" font-size="13" letter-spacing="1.2" fill="{fill}">{doc.mono(fam, text)}</text>')
                x += (len(text) + 3) * adv
        texts.append(f'<circle cx="{f1(x + adv)}" cy="181.5" r="2" fill="{th["trace"]}"/>')
        x += 6 * adv
    wf = x
    copies = math.ceil(1000 / wf) + 1
    row2 = (f'<g class="r2in"><g class="mq2"><g id="r2">{"".join(texts)}</g>'
            + "".join(f'<use href="#r2" xlink:href="#r2" x="{f1(wf * k)}"/>' for k in range(1, copies)) + "</g></g>")

    caption = "FIG. 2 · LATEST PUBLIC COMMITS"
    doc.body = [
        typed(doc, caption, 24, 28, 12, th["dim"], 2.1, 1.5),
        f'<circle class="live" cx="{f1(24 + len(caption) * (0.6 * 12 + 1.5) + 8)}" cy="24" r="3" fill="{th["trace"]}"/>',
        typed(doc, "UPDATED " + day(now.date()), 976, 28, 12, th["dim"], 2.3, 1.5, anchor="end"),
        f'<path class="hl" d="M0 42H1000" stroke="{th["faint"]}"/>',
        f'<path class="hl" d="M0 208H1000" stroke="{th["faint"]}"/>',
        f'<g mask="url(#edge)">{row1}{row2}</g>',
    ]
    doc.css.append(
        f".mq1{{animation:mq1 {wc / 44:.1f}s linear infinite}}@keyframes mq1{{from{{transform:translateX({f1(-wc)}px)}}}}"
        f".mq2{{animation:mq2 {wf / 30:.1f}s linear infinite}}@keyframes mq2{{to{{transform:translateX({f1(-wf)}px)}}}}"
        f".r1in{{animation:rise 1.2s {OUT} 1.95s backwards}}.r2in{{animation:fade 1.2s ease-out 2.4s backwards}}"
        f".hl{{transform-origin:500px 0;animation:hl 1.4s {OUT} 1.7s backwards}}@keyframes hl{{from{{transform:scaleX(0)}}}}"
        ".live{animation:fade .4s ease-out 3.1s backwards,live 1.8s ease-in-out 3.5s infinite}"
        "@keyframes live{0%,100%{opacity:1}50%{opacity:.2}}"
    )
    label = ("A band of slowly scrolling words, " + ", ".join(BAND_WORDS) + ", above a ticker of my latest public commits: "
             + "; ".join(f"{r}: {m}" for r, m, _ in items[:4]) + ".")
    return doc.render(label)


# ---------------------------------------------------------------- project cards

def build_tree(files):
    root = {"children": {}}
    for path, size in files:
        parts = path.split("/")
        node = root
        for p in parts[:-1]:
            node = node["children"].setdefault(p, {"children": {}})
        node["children"][parts[-1]] = {"size": size, "top": parts[0] if len(parts) > 1 else ""}
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


PULSE_START, PULSE_EVERY = 5.6, 9.0  # every card fires its pulses together, so the gallery beats as one


def render_card(index, name, tagline, data, theme, now, serif):
    th = THEMES[theme]
    doc = Doc(400, 520)
    cx, cy = 200, 220
    Rt, Ls = 112, 34
    D = 2.7 + 0.16 * (index - 1)

    root = build_tree(data["files"])
    leaves, nodes = [], []  # nodes: (depth, parent, node)

    def walk(node, depth, parent):
        nodes.append((depth, parent, node))
        kids = node.get("children")
        if kids is None:
            node["first"] = node["last"] = len(leaves)
            leaves.append(node)
            return
        ordered = sorted(kids.items(), key=lambda kv: ("children" not in kv[1], kv[0].lower()))
        for _, child in ordered:
            walk(child, depth + 1, node)
        node["first"] = ordered[0][1]["first"] if ordered else len(leaves)
        node["last"] = ordered[-1][1]["last"] if ordered else len(leaves)

    walk(root, 0, None)
    n = max(len(leaves), 1)
    # scale to the typical file, not the outliers, so one deep folder or one huge file
    # cannot squash everything else into the centre
    leaf_depths = sorted(d for d, _, nd in nodes if "children" not in nd) or [1]
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
    by_depth, spikes, route = {}, [], {}
    for depth, parent, node in nodes:
        if parent is None:
            route[id(node)] = f"M{cx} {cy}"
            continue
        a_c, r_c = angle(node), radius(depth)
        r_p = radius(depth - 1)
        a_p = angle(parent) if depth > 1 else a_c
        rm = (r_p + r_c) / 2
        p0, c1, c2, p3 = pt(cx, cy, r_p, a_p), pt(cx, cy, rm, a_p), pt(cx, cy, rm, a_c), pt(cx, cy, r_c, a_c)
        curve = f"C{f1(c1[0])} {f1(c1[1])} {f1(c2[0])} {f1(c2[1])} {f1(p3[0])} {f1(p3[1])}"
        by_depth.setdefault(depth, []).append(f"M{f1(p0[0])} {f1(p0[1])}{curve}")
        route[id(node)] = route[id(parent)] + curve
        if "children" not in node:
            q = pt(cx, cy, r_c + 3 + Ls * min(1.0, math.sqrt(node["size"] / size_ref)), a_c)
            node["spike"] = f"M{f1(p3[0])} {f1(p3[1])}L{f1(q[0])} {f1(q[1])}"
            node["route"] = route[id(node)] + f"L{f1(q[0])} {f1(q[1])}"
            spikes.append(node["spike"])

    # highways: the routes a pulse takes from the root out to big files in different folders
    ranked = sorted(leaves, key=lambda lf: -lf["size"])
    picked, seen = [], set()
    for lf in ranked:
        if lf["top"] not in seen:
            picked.append(lf)
            seen.add(lf["top"])
        if len(picked) == 7:
            break
    for lf in ranked:
        if len(picked) >= 7:
            break
        if all(lf is not p for p in picked):
            picked.append(lf)

    rfull = Rt + Ls + 10
    branches = "".join(f'<path d="{"".join(segs)}"/>' for _, segs in sorted(by_depth.items()))
    spike_d = "".join(spikes)
    doc.defs += [
        heat_gradient("heat", cx, cy, 0, Rt + Ls, th.get("card_heat", th["heat"])),
        '<radialGradient id="ring"><stop offset=".7" stop-color="#fff" stop-opacity="0"/><stop offset=".9" stop-color="#fff"/>'
        '<stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient>',
        f'<mask id="hf" maskUnits="userSpaceOnUse" x="0" y="0" width="400" height="520"><circle class="hfm" cx="{cx}" cy="{cy}" r="{rfull}" fill="url(#ring)"/></mask>',
        '<clipPath id="nc"><rect x="0" y="372" width="400" height="76"/></clipPath>',
    ]
    pulses = "".join(f'<path class="hw" pathLength="1" style="--g:{PULSE_START + k * 0.14:.2f}s" d="{lf["route"]}"/>' for k, lf in enumerate(picked))
    flashes = "".join(f'<path class="lf" style="--g:{PULSE_START + k * 0.14:.2f}s" d="{lf["spike"]}"/>' for k, lf in enumerate(picked))

    title, _, _ = serif.run(name, 28, 432, 48)
    files = len(data["files"])
    meta = f"{files:,} FILES · PUSHED {ago(data['pushed'], now)}"
    type_start, cps = D + 0.85, 38
    doc.body = [
        f'<g class="tree"><g fill="none" stroke="{th["branch"]}" stroke-width="{f1(branch_w)}" stroke-opacity="{max(0.12, 0.65 * density):.2f}" '
        f'stroke-linecap="round">{branches}</g>'
        f'<path d="{spike_d}" fill="none" stroke="url(#heat)" stroke-width="{f1(spike_w + 3)}" stroke-opacity="{0.16 if th["glow"] else 0.08}" stroke-linecap="round"/>'
        f'<path d="{spike_d}" fill="none" stroke="url(#heat)" stroke-width="{f1(spike_w)}" stroke-linecap="round"/></g>',
        f'<g class="front" mask="url(#hf)"><path d="{spike_d}" fill="none" stroke="{th["hot"]}" stroke-width="{f1(spike_w + 0.6)}" stroke-linecap="round"/></g>',
        f'<g fill="none" stroke="{th["hot"]}" stroke-width="2.2" stroke-linecap="round">{pulses}</g>',
        f'<g fill="none" stroke="{th["hot"]}" stroke-width="{f1(spike_w + 1.2)}" stroke-linecap="round">{flashes}</g>',
        f'<circle class="fd" style="--t:{D:.2f}s" cx="{cx}" cy="{cy}" r="2.5" fill="{th["ink"]}"/>',
        f'<circle class="ping" style="--t:{D:.2f}s" cx="{cx}" cy="{cy}" r="5" fill="none" stroke="{th["trace"]}" stroke-width="1.4"/>',
        f'<circle class="rp" cx="{cx}" cy="{cy}" r="5" fill="none" stroke="{th["trace"]}" stroke-width="1.2"/>',
        f'<text class="m fd" style="--t:{D:.2f}s" x="28" y="44" font-size="15" fill="{th["dim"]}">{doc.mono("M", f"{index:02d}")}</text>',
        typed(doc, lang_summary(data["langs"]), 372, 44, 15, th["dim"], D + 0.2, 1, anchor="end", cps=60),
        '<g clip-path="url(#nc)">' + "".join(f'<path class="nr" style="--k:{k}" d="{d}" fill="{th["ink"]}"/>' for k, (d, _) in enumerate(title)) + "</g>",
        typed(doc, tagline, 28, 466, 17, th["dim"], type_start, 0, cps=cps),
        f'<rect class="cur" x="28" y="452" width="9" height="17" fill="{th["trace"]}" '
        f'style="--n:{f1(len(tagline) * 0.6 * 17)}px;--s:{len(tagline)};--d:{len(tagline) / cps:.2f}s;--t:{type_start:.2f}s"/>',
        f'<text class="m fd" style="--t:{D + 1.5:.2f}s" x="28" y="496" font-size="13" letter-spacing="1.2" fill="{th["dim"]}">{doc.mono("M", meta)}</text>',
    ]
    doc.css.append(
        f".tree{{animation:gm 1.8s cubic-bezier(.3,0,.2,1) {D + 0.1:.2f}s backwards}}"
        f"@keyframes gm{{from{{clip-path:circle(0px at {cx}px {cy}px) view-box}}to{{clip-path:circle({rfull}px at {cx}px {cy}px) view-box}}}}"
        f".front{{animation:fin {D + 1.95:.2f}s linear forwards}}"
        f".hfm{{opacity:0;transform-origin:{cx}px {cy}px;animation:hf 1.8s cubic-bezier(.3,0,.2,1) {D + 0.1:.2f}s}}"
        "@keyframes hf{0%{opacity:1;transform:scale(0)}75%{opacity:1}100%{opacity:0;transform:scale(1)}}"
        f".hw{{stroke-dasharray:.1 3;stroke-dashoffset:.11;animation:pulse {PULSE_EVERY}s linear var(--g) infinite}}"
        "@keyframes pulse{0%{stroke-dashoffset:.11}17%{stroke-dashoffset:-1.01}100%{stroke-dashoffset:-1.01}}"
        f".lf{{opacity:0;animation:flash {PULSE_EVERY}s linear var(--g) infinite}}"
        "@keyframes flash{0%,15%{opacity:0}17%{opacity:1}30%{opacity:0}100%{opacity:0}}"
        f".rp{{opacity:0;transform-box:fill-box;transform-origin:center;animation:rping {PULSE_EVERY}s linear {PULSE_START - 0.1:.2f}s infinite}}"
        "@keyframes rping{0%{opacity:.8;transform:scale(.6)}7%{opacity:0;transform:scale(5)}100%{opacity:0;transform:scale(5)}}"
        f".nr{{animation:nrise .9s {OUT} backwards;animation-delay:calc({D + 0.35:.2f}s + var(--k) * 38ms)}}"
        "@keyframes nrise{from{transform:translateY(64px)}}"
        ".cur{opacity:0;animation-name:cmove,cblink;animation-duration:var(--d),.55s;animation-timing-function:steps(var(--s)),step-end;"
        "animation-delay:var(--t),calc(var(--t) + var(--d));animation-iteration-count:1,4;animation-fill-mode:forwards,forwards}"
        "@keyframes cmove{from{opacity:1;transform:translateX(0)}to{opacity:1;transform:translateX(var(--n))}}"
        "@keyframes cblink{0%{opacity:1}50%{opacity:0}100%{opacity:0}}"
    )
    label = f"{name}: {tagline}. Its {files:,} files drawn as a radial tree, one spike per file, longer for larger files."
    return doc.render(label)


# ---------------------------------------------------------------- main

def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "dist")
    out.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc)
    serif, italic = Face(SERIF), Face(SERIF_ITALIC)
    days = contribution_days()
    commits = recent_commits()
    for theme in THEMES:
        (out / f"year-{theme}.svg").write_text(render_year(days, theme, serif, italic), encoding="utf-8")
        (out / f"band-{theme}.svg").write_text(render_band(commits, theme, italic, now), encoding="utf-8")
    for i, (repo, name, tagline) in enumerate(PROJECTS, 1):
        data = repo_data(repo)
        for theme in THEMES:
            (out / f"card-{repo.lower()}-{theme}.svg").write_text(
                render_card(i, name, tagline, data, theme, now, serif), encoding="utf-8")
    print(f"wrote {len(list(out.glob('*.svg')))} files to {out}")


if __name__ == "__main__":
    main()
