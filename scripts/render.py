#!/usr/bin/env python3
"""Draws the animated artwork on my GitHub profile.

  year-{theme}.svg          Fig. 1: the last 365 days of contributions as a ring, one spoke per day
  band-{theme}.svg          Fig. 2: a kinetic type band over a ticker of my latest public commits
  rule-{name}-{theme}.svg   section headers: a hairline with a spark that runs along it
  card-{repo}-{theme}.svg   Fig. 3: each featured repository's file tree, drawn radially
  ridge-{theme}.svg         Fig. 4: my public commits by week and hour of day, as ridgelines
  fin-{theme}.svg           the closing card
  year.stl                  Fig. 5: the last 52 weeks as towers on a ring, for GitHub's 3D viewer;
                            with --readme, it is also written into the README between markers

Every image plays a reveal when it loads and keeps some ambient motion after; with
reduced motion requested they show the finished still. Effects that only matter
during a reveal remove themselves when done, so the page stays light.
Data comes from the GitHub API using GITHUB_TOKEN.

Display type is set as outlines (HarfBuzz shaping, fontTools outlines) so it can be
animated glyph by glyph; small mono text embeds a subset font.
Fonts: Instrument Serif and IBM Plex Mono, SIL Open Font License 1.1.

Usage: GITHUB_TOKEN=... python scripts/render.py [out_dir] [--readme README.md]
"""
import base64
import collections
import datetime as dt
import html
import io
import json
import math
import os
import random
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import uharfbuzz as hb
from fontTools import subset
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFilter

USER = "sreevarshan-xenoz"
TZ = dt.timezone(dt.timedelta(hours=5, minutes=30))  # my local time (IST), for the hour-of-day figure
PROJECTS = [  # public repos only: repo, display name, tagline (under ~33 characters)
    ("xencode", "xencode", "local-first AI coding agent"),
    ("Pocketdesk", "Pocketdesk", "your desktop, on your phone"),
    ("codehalo", "CodeHalo", "a HUD for AI coding agents"),
    ("metapak", "metapak", "one TUI for every package manager"),
    ("Research-agent", "Research Agent", "research agent that writes LaTeX"),
    ("LedgerMind", "LedgerMind", "finance-ops reconciliation agent"),
]
BAND_WORDS = ["Local-first", "Rust", "Coding agents", "On-device AI", "Remote desktops", "Wayland", "Open source"]
RULES = {  # section headers: name -> (label, note, when its spark first runs)
    "work": ("FIG. 3 · SELECTED WORK", "SIX PUBLIC PROJECTS, EACH DRAWN FROM ITS OWN FILE TREE", 4.0),
    "ship": ("FIG. 4 · WHEN I SHIP", "MY PUBLIC COMMITS, WEEK BY WEEK AND HOUR BY HOUR", 6.5),
    "spin": ("FIG. 5 · THE YEAR IN 3D", "52 WEEKS AS TOWERS · DRAG TO SPIN, SCROLL TO ZOOM", 9.0),
}
STL_START, STL_END = "<!-- year-3d:start -->", "<!-- year-3d:end -->"
SKIP_DIRS = {"node_modules", "target", "dist", "build", "vendor", ".git", "__pycache__", ".next", ".venv"}

THEMES = {
    "dark": {
        "bg": "#0d1117", "ink": "#f0f6fc", "dim": "#9198a1", "faint": "#3d444d", "branch": "#6e7681",
        "hot": "#fff7ed", "trace": "#fbbf24", "spark": "#fde68a", "beam": "#fff1d6", "glow": 0.5,
        "heat": ["#7f1d1d", "#c2410c", "#f97316", "#fbbf24", "#fff7ed"],
        "molten": ["#fff7ed", "#fde68a", "#fb923c", "#c2410c"], "pour": "#fbbf24",
        "ridge": ["#3d444d", "#f97316", "#fde68a"],
    },
    "light": {
        "bg": "#ffffff", "ink": "#1f2328", "dim": "#59636e", "faint": "#d1d9e0", "branch": "#8c959f",
        "hot": "#2a0f05", "trace": "#c2410c", "spark": "#c2410c", "beam": "#7c2d12", "glow": 0,
        "heat": ["#fdba74", "#f97316", "#ea580c", "#9a3412", "#431407"],
        "card_heat": ["#f97316", "#ea580c", "#c2410c", "#7c2d12", "#431407"],  # thin strokes need deeper ink
        "molten": ["#7c2d12", "#c2410c", "#ea580c", "#fb923c"], "pour": "#ea580c",
        "ridge": ["#c9d1d9", "#ea580c", "#7c2d12"],
    },
}

FONT_DIR = Path(__file__).parent / "fonts"
SERIF = "instrument-serif-latin-400-normal.woff2"
SERIF_ITALIC = "instrument-serif-latin-400-italic.woff2"
MONO_FILES = {"M": "ibm-plex-mono-latin-400-normal.woff2", "MM": "ibm-plex-mono-latin-500-normal.woff2"}
MONTHS = "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split()
WEEKDAYS = "Monday Tuesday Wednesday Thursday Friday Saturday Sunday".split()

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
        except urllib.error.HTTPError as e:
            if e.code < 500 and e.code not in (403, 429):  # a real answer, not a hiccup
                raise
            if attempt == 5:
                raise
            time.sleep(2 + attempt * 2)
        except OSError:
            if attempt == 5:
                raise
            time.sleep(2 + attempt * 2)
    raise RuntimeError(f"no data from {url}")


def api(path):
    return _request(f"https://api.github.com/{path}")


def contribution_weeks():
    """Every day GitHub counts for me over the last year, in calendar weeks: [[(date, count)]]."""
    query = """query($login: String!) { user(login: $login) { contributionsCollection {
      contributionCalendar { weeks { contributionDays { date contributionCount } } } } } }"""
    res = _request("https://api.github.com/graphql", {"query": query, "variables": {"login": USER}})
    return [[(dt.date.fromisoformat(d["date"]), d["contributionCount"]) for d in w["contributionDays"]]
            for w in res["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]]


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


def commit_times(days=365, max_pages=30):
    """When I committed to my public repos over the last year, as UTC datetimes."""
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    repos = [r for r in api(f"users/{USER}/repos?type=owner&sort=pushed&per_page=100")
             if not r["fork"] and r["pushed_at"] >= since]
    seen, out = set(), []
    for r in repos:
        for page in range(1, max_pages + 1):
            try:
                commits = api(f"repos/{USER}/{r['name']}/commits?author={USER}&since={since}&per_page=100&page={page}")
            except urllib.error.HTTPError:  # an empty repository answers 409
                break
            for c in commits:
                if c["sha"] not in seen:
                    seen.add(c["sha"])
                    out.append(dt.datetime.fromisoformat(c["commit"]["author"]["date"].replace("Z", "+00:00")))
            if len(commits) < 100:
                break
    return out


# ---------------------------------------------------------------- type and path helpers

def f1(v):
    s = f"{v:.1f}"
    s = s[:-2] if s.endswith(".0") else s
    return "0" if s == "-0" else s


def nums(*vals):
    """Numbers for path data, dropping the spaces SVG allows you to drop before a minus sign."""
    out = ""
    for v in vals:
        s = f1(v)
        out += s if not out or s[0] == "-" else " " + s
    return out


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
        """[(glyph, x, character index, advance)], width."""
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        hb.shape(self.hb, buf, {"kern": True, "liga": True})
        s, x, out = size / self.upem, 0, []
        for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
            out.append((self.order[info.codepoint], (x + pos.x_offset) * s, info.cluster, pos.x_advance * s))
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
        """Glyph outlines for a line of text: [(path, left x, character index)], width, start x."""
        glyphs, width = self.shape(text, size)
        x0 = x - width if anchor == "end" else x - width / 2 if anchor == "middle" else x
        out = []
        for g, gx, cl, _ in glyphs:
            d = self.path(g, x0 + gx, y, size)
            if d:
                out.append((d, x0 + gx, cl))
        return out, width, x0

    def words(self, text, x, y, size, doc, anchor="middle"):
        """Glyphs grouped by word, each a <use> of a shared definition:
        [(word, [elements], left, right)], width, start x."""
        glyphs, width = self.shape(text, size)
        x0 = x - width if anchor == "end" else x - width / 2 if anchor == "middle" else x
        s = size / self.upem
        out, start = [], 0
        for word in text.split(" "):
            end = start + len(word)
            mine = [(g, gx, adv) for g, gx, cl, adv in glyphs if start <= cl < end]
            uses = [f'<use href="#{doc.glyph(self, g)}" transform="translate({nums(x0 + gx, y)})scale({s:.4f} {-s:.4f})"/>'
                    for g, gx, _ in mine if self.units(g)]
            out.append((word, uses, x0 + mine[0][1], x0 + mine[-1][1] + mine[-1][2]))
            start = end + 1
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
        """A glyph defined once in font units, for <use> wherever it repeats."""
        gid = f"{face.key}-{glyph}".replace(".", "_")
        if gid not in self._glyphs:
            self._glyphs.add(gid)
            self.defs.append(f'<path id="{gid}" d="{face.units(glyph)}" pathLength="1"/>')
        return gid

    def render(self, label):
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" viewBox="0 0 {self.w} {self.h}" '
                f'role="img" aria-label="{html.escape(label)}"><style>{self.mono.css()}{BASE_CSS}{"".join(self.css)}{REDUCED}</style>'
                f'<defs>{"".join(self.defs)}</defs>{"".join(self.body)}</svg>\n')


def typed(doc, text, x, y, size, fill, start, ls=0.0, family="M", anchor="start", cps=48):
    """Mono text that types itself out, one character per step."""
    adv = 0.6 * size + ls
    n = max(len(text), 1)
    w = n * adv
    x0 = x - w if anchor == "end" else x - w / 2 if anchor == "middle" else x
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
            for j in range(final + 1):  # in the scaled group below: font units, y up
                dch = str(j % 10)
                dx = (w - face.advance(dch, size)) / 2 / s
                strip.append(f'<use href="#{doc.glyph(face, face.cmap[ord(dch)])}" x="{dx:.0f}" y="{-j * line / s:.0f}"/>')
            out.append(f'<g mask="url(#{mid})"><g class="odo" fill="{fill}" style="transform:translateY({f1(-final * line)}px);'
                       f'animation-duration:{1.5 + col * 0.15:.2f}s;animation-delay:{start + col * 0.06:.2f}s">'
                       f'<g transform="translate({nums(cx, y)})scale({s:.4f} {-s:.4f})">{"".join(strip)}</g></g></g>')
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
    return (f"M{nums(x1, y1)}L{nums(x2, y2)}A{nums(r2, r2)} 0 0 1 {nums(x3, y3)}"
            f"L{nums(x4, y4)}A{nums(r1, r1)} 0 0 0 {nums(x1, y1)}Z")


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


def mix(c1, c2, k):
    return "#%02x%02x%02x" % tuple(round(a + (b - a) * k) for a, b in zip(hex_rgb(c1), hex_rgb(c2)))


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
    rgb.save(buf, "WEBP", quality=60, method=6)
    return base64.b64encode(buf.getvalue()).decode()


def circle_path(cx, cy, r):
    return f"M{nums(cx, cy - r)}A{nums(r, r)} 0 1 1 {nums(cx, cy + r)}A{nums(r, r)} 0 1 1 {nums(cx, cy - r)}"


def day(d):
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def glint(doc, clip_id, shapes, x0, x1, y0, y1, color, period, delay):
    """A bar of light that passes over some glyphs (the `shapes` markup) every `period` seconds."""
    gid = doc.uid("gg")
    travel = x1 - x0 + 160
    doc.defs += [f'<clipPath id="{clip_id}">{shapes}</clipPath>',
                 f'<linearGradient id="{gid}" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="{color}" stop-opacity="0"/>'
                 f'<stop offset=".5" stop-color="{color}"/><stop offset="1" stop-color="{color}" stop-opacity="0"/></linearGradient>']
    doc.css.append(f".{gid}{{transform:translateX({f1(travel)}px);animation:{gid} {period}s {INOUT} {delay:.2f}s infinite}}"
                   f"@keyframes {gid}{{0%{{transform:translateX(0);visibility:visible}}13%{{transform:translateX({f1(travel)}px);visibility:hidden}}"
                   f"100%{{transform:translateX({f1(travel)}px);visibility:hidden}}}}")
    h = y1 - y0
    return (f'<g clip-path="url(#{clip_id})"><path class="{gid}" d="M{nums(x0 - 80, y0)}h46l{nums(-h * 0.35, h)}h-46z" '
            f'fill="url(#{gid})"/></g>')


# ---------------------------------------------------------------- Fig. 1, the year ring

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

    stops = [(r0 + L * f, hex_rgb(c)) for f, c in zip((0, 0.3, 0.58, 0.82, 1), th["heat"])]

    def heat_at(r):
        for (ra, ca), (rb, cb) in zip(stops, stops[1:]):
            if r <= rb:
                k = (r - ra) / (rb - ra)
                return tuple(round(a + (b - a) * k) for a, b in zip(ca, cb))
        return stops[-1][1]

    # spokes: a heat layer that stays, and a white-hot copy that cools away and flashes when the beam passes
    spokes, hots, dots, glow_lines = [], [], [], []
    for i, (_, c) in enumerate(days):
        a = ang(i)
        if c:
            (x1, y1), (x2, y2) = pt(cx, cy, r0, a), pt(cx, cy, r0 + reach(c), a)
            d = f'd="M{nums(x1, y1)}l{nums(x2 - x1, y2 - y1)}" pathLength="1"'
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
        grooves.append(f'<path class="gv" style="--t:{0.35 + k * 0.12:.2f}s" d="M{nums(sx, sy)}A{nums(r, r)} 0 1 1 {nums(ex, ey)}"/>')
        groove_labels.append(f'<text class="m fd" style="--t:{0.5 + k * 0.12:.2f}s" x="{cx}" y="{f1(cy - r)}" font-size="10" text-anchor="middle" '
                             f'dominant-baseline="central" fill="{th["dim"]}">{doc.mono("M", str(v))}</text>')

    months = []
    for i, (d, _) in enumerate(days):
        a = ang(i) - (360 - gap) / n / 2
        if d.day != 1 or min(a + 90, 270 - a) < 9:  # leave the seam to the NOW marker
            continue
        (tx1, ty1), (tx2, ty2) = pt(cx, cy, r0 - 12, a), pt(cx, cy, r0 - 4, a)
        months.append(f'<path class="fd" style="--t:{born(i):.2f}s" d="M{nums(tx1, ty1)}L{nums(tx2, ty2)}" stroke="{th["faint"]}"/>')
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
    hot_days = sorted(range(n), key=lambda i: -counts[i])[:24]
    for k in range(30):
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
    sn = size / italic.upem
    lines, uses = [], []
    for word, base_y in (("Sree", cy - 2), ("Varshan", cy + 50)):
        glyphs, width = italic.shape(word, size)
        left = cx - width / 2
        lines.append((left, width))
        uses += [f'<use href="#{doc.glyph(italic, g)}" transform="translate({nums(left + gx, base_y)})scale({sn:.4f} {-sn:.4f})"'
                 for g, gx, _, _ in glyphs if italic.units(g)]
    (x1, w1), (x2, w2) = lines
    name_paths = "".join(u + "/>" for u in uses)
    trace_paths = "".join(u + f' style="--k:{k}"/>' for k, u in enumerate(uses))  # dash settings inherit into each glyph
    nx0, nx1 = min(x1, x2) - 12, max(x1 + w1, x2 + w2) + 12
    ny0, ny1 = cy - 2 - size * 0.82, cy + 50 + size * 0.28
    flood_h = ny1 - ny0 + 30

    # corner notes
    total, active = sum(counts), sum(1 for c in counts if c)
    fig, _, _ = italic.run("Fig. 1", 40, 70, 38)
    span = f"{MONTHS[days[0][0].month - 1]} {days[0][0].year} – {MONTHS[days[-1][0].month - 1]} {days[-1][0].year}"
    notes = ["".join(f'<path class="fg" style="--k:{k}" d="{d}" fill="{th["ink"]}"/>' for k, (d, *_) in enumerate(fig)),
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
        f'<mask id="flood" maskUnits="userSpaceOnUse" x="{f1(nx0)}" y="{f1(ny0 - 30)}" width="{f1(nx1 - nx0)}" height="{f1(flood_h)}">'
        f'<rect class="fl" x="{f1(nx0)}" y="{f1(ny0 - 30)}" width="{f1(nx1 - nx0)}" height="{f1(flood_h)}" fill="url(#floodg)"/></mask>',
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
        f'<path d="M{nums(lx1, ly1)}L{nums(lx2, ly2)}" stroke="{th["beam"]}" stroke-width="1.4" stroke-linecap="round"/></g>',
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
        f'<g class="rt"><g class="spin"><text class="mm" font-size="12" fill="{th["dim"]}"><textPath href="#lr" '
        f'textLength="{f1(2 * math.pi * lr - 9)}" lengthAdjust="spacing">{doc.mono("MM", ring_text)}</textPath></text></g></g>',
        # the name
        '<use class="nmglow" href="#nm" fill="#f97316" filter="url(#blur)"/>' if th["glow"] else "",
        f'<g class="run" style="--e:3.9s" mask="url(#flood)"><use class="nmf" href="#nm" fill="{th["ink"]}"/></g>',
        f'<use class="done" style="--e:3.9s" href="#nm" fill="{th["ink"]}"/>',
        f'<g class="trace" fill="none" stroke="{th["trace"]}" stroke-width="{f1(1.1 / sn)}">{trace_paths}</g>',
        glint(doc, "nmc", name_paths, nx0, nx1, ny0 - 10, ny1 + 10, th["pour"], 9, 3.7),
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
        f".trace use{{animation:grow 1.2s {INOUT} backwards;animation-delay:calc(.95s + var(--k) * 70ms)}}"
        ".trace{opacity:0;animation:trace 3.3s linear .95s}"
        "@keyframes trace{0%{opacity:1}62%{opacity:1}100%{opacity:0}}"
        f".fl{{animation:flood 1.1s {INOUT} 1.85s backwards}}"
        f"@keyframes flood{{from{{transform:translateY({f1(flood_h)}px)}}}}"
        ".nmf{animation:pour 2s ease-out 1.85s backwards}"
        f"@keyframes pour{{from{{fill:{th['pour']}}}}}"
        ".nmglow{opacity:0;animation:flare 2.2s ease-out 1.9s backwards,fin 4.1s linear forwards}"  # removed once done, so its blur stops costing
        "@keyframes flare{0%{opacity:0}30%{opacity:.75}100%{opacity:0}}"
        f".sw{{opacity:0;transform-box:fill-box;transform-origin:center;animation:shock 1.9s {OUT} 2.6s}}"
        ".sw2{animation-delay:2.78s}"
        "@keyframes shock{0%{opacity:.7;transform:scale(1)}100%{opacity:0;transform:scale(4.6)}}"
        f".fg{{animation:rise .8s {OUT} backwards;animation-delay:calc(2.2s + var(--k) * 45ms)}}"
    )
    label = (f"Sree Varshan's last {n} days on GitHub drawn as a glowing ring of {n} spokes, one per day, "
             f"longer and hotter on busier days: {total:,} contributions on {active} active days.")
    return doc.render(label)


# ---------------------------------------------------------------- Fig. 2, the kinetic band

def render_band(commits, theme, italic, now):
    th = THEMES[theme]
    doc = Doc(1000, 220)
    size, base = 76, 128
    s = size / italic.upem

    # row one: big outlined words that turn molten as they cross the spotlight.
    # Each letter is defined once and reused, which keeps this file small.
    parts, x = [], 0.0
    for w in BAND_WORDS:
        glyphs, width = italic.shape(w, size)
        for g, gx, _, _ in glyphs:
            if italic.units(g):
                parts.append(f'<use href="#{doc.glyph(italic, g)}" transform="translate({nums(x + gx, base)})scale({s:.4f} {-s:.4f})"/>')
        x += width + 30
        parts.append(f'<circle cx="{f1(x)}" cy="{f1(base - size * 0.26)}" r="4.5" stroke-width="1"/>')
        x += 30
    wc = x
    doc.defs += [
        f'<g id="r1">{"".join(parts)}</g>',
        # the glyphs are drawn by reference in font units (y up), so the gradient is set in those units too
        '<linearGradient id="molten" gradientUnits="userSpaceOnUse" x1="0" y1="760" x2="0" y2="-220">'
        + "".join(f'<stop offset="{o}" stop-color="{c}"/>' for o, c in zip((0, 0.35, 0.7, 1), th["molten"])) + "</linearGradient>",
        '<radialGradient id="spotg"><stop offset="0" stop-color="#fff"/><stop offset=".55" stop-color="#fff" stop-opacity=".85"/>'
        '<stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient>',
        '<mask id="spot" maskUnits="userSpaceOnUse" x="0" y="0" width="1000" height="220"><ellipse cx="500" cy="104" rx="250" ry="120" fill="url(#spotg)"/></mask>',
        '<linearGradient id="edgeg"><stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset=".1" stop-color="#fff"/>'
        '<stop offset=".9" stop-color="#fff"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>',
        '<mask id="edge" maskUnits="userSpaceOnUse" x="0" y="0" width="1000" height="220"><rect width="1000" height="220" fill="url(#edgeg)"/></mask>',
    ]
    uses = f'<use href="#r1"/><use href="#r1" x="{f1(wc)}"/>'
    row1 = (f'<g class="r1in"><g class="mq1" fill="none" stroke="{th["dim"]}" stroke-width="{f1(1 / s)}" stroke-opacity=".75">{uses}</g>'
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
            + "".join(f'<use href="#r2" x="{f1(wf * k)}"/>' for k in range(1, copies)) + "</g></g>")

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


# ---------------------------------------------------------------- section headers

def render_rule(label, note, theme, spark_at):
    """A section header: the label types itself, a hairline draws across, and every
    ten seconds a spark runs the length of it like a lit fuse."""
    th = THEMES[theme]
    doc = Doc(1000, 56)
    doc.defs.append(f'<linearGradient id="trail" gradientUnits="userSpaceOnUse" x1="-90" y1="0" x2="0" y2="0">'
                    f'<stop offset="0" stop-color="{th["trace"]}" stop-opacity="0"/><stop offset="1" stop-color="{th["trace"]}"/></linearGradient>')
    doc.body = [
        typed(doc, label, 0, 22, 12, th["ink"], 0.9, 1.5, family="MM"),
        typed(doc, note, 1000, 22, 12, th["dim"], 1.3, 1.5, anchor="end", cps=80),
        f'<path class="hl" d="M0 40H1000" stroke="{th["faint"]}"/>',
        f'<g class="fuse"><path d="M-90 40h90" stroke="url(#trail)" stroke-width="2" stroke-linecap="round"/>'
        f'<circle cy="40" r="7" fill="{th["trace"]}" fill-opacity=".22"/><circle cy="40" r="2.4" fill="{th["hot"]}"/></g>',
    ]
    doc.css.append(
        f".hl{{transform-origin:0 0;animation:hl 1.6s {OUT} .6s backwards}}@keyframes hl{{from{{transform:scaleX(0)}}}}"
        f".fuse{{transform:translateX(-100px);animation:fuse 10s cubic-bezier(.45,.05,.25,1) {spark_at:.2f}s infinite}}"
        "@keyframes fuse{0%{transform:translateX(-100px)}26%{transform:translateX(1100px)}100%{transform:translateX(1100px)}}"
    )
    return doc.render(f"{label.title()}: {note.lower()}.")


# ---------------------------------------------------------------- Fig. 3, project cards

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


PULSE_START, PULSE_EVERY, PULSE_STEP = 5.6, 9.0, 0.55  # a pulse ripples across the gallery card by card


def render_card(index, name, tagline, data, theme, now, serif):
    th = THEMES[theme]
    doc = Doc(400, 520)
    cx, cy = 200, 220
    Rt, Ls = 112, 34
    D = 2.7 + 0.16 * (index - 1)
    pulse0 = PULSE_START + PULSE_STEP * (index - 1)

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
        by_depth.setdefault(depth, []).append(
            f"M{nums(*p0)}c{nums(c1[0] - p0[0], c1[1] - p0[1], c2[0] - p0[0], c2[1] - p0[1], p3[0] - p0[0], p3[1] - p0[1])}")
        route[id(node)] = route[id(parent)] + f"C{nums(*c1, *c2, *p3)}"
        if "children" not in node:
            q = pt(cx, cy, r_c + 3 + Ls * min(1.0, math.sqrt(node["size"] / size_ref)), a_c)
            node["spike"] = f"M{nums(*p3)}l{nums(q[0] - p3[0], q[1] - p3[1])}"
            node["route"] = route[id(node)] + f"L{nums(*q)}"
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
    doc.defs += [
        heat_gradient("heat", cx, cy, 0, Rt + Ls, th.get("card_heat", th["heat"])),
        f'<path id="sk" d="{"".join(spikes)}"/>',  # every spike, drawn three times below by reference
        '<radialGradient id="ring"><stop offset=".7" stop-color="#fff" stop-opacity="0"/><stop offset=".9" stop-color="#fff"/>'
        '<stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient>',
        f'<mask id="hf" maskUnits="userSpaceOnUse" x="0" y="0" width="400" height="520"><circle class="hfm" cx="{cx}" cy="{cy}" r="{rfull}" fill="url(#ring)"/></mask>',
        '<clipPath id="nc"><rect x="0" y="372" width="400" height="76"/></clipPath>',
    ]
    pulses = "".join(f'<path class="hw" pathLength="1" style="--g:{pulse0 + k * 0.14:.2f}s" d="{lf["route"]}"/>' for k, lf in enumerate(picked))
    flashes = "".join(f'<path class="lf" style="--g:{pulse0 + k * 0.14:.2f}s" d="{lf["spike"]}"/>' for k, lf in enumerate(picked))

    title, tw, _ = serif.run(name, 28, 432, 48)
    files = len(data["files"])
    meta = f"{files:,} FILES · PUSHED {ago(data['pushed'], now)}"
    type_start, cps = D + 0.85, 38
    doc.body = [
        f'<g class="tree"><g fill="none" stroke="{th["branch"]}" stroke-width="{f1(branch_w)}" stroke-opacity="{max(0.12, 0.65 * density):.2f}" '
        f'stroke-linecap="round">{branches}</g>'
        f'<use href="#sk" fill="none" stroke="url(#heat)" stroke-width="{f1(spike_w + 3)}" stroke-opacity="{0.16 if th["glow"] else 0.08}" stroke-linecap="round"/>'
        f'<use href="#sk" fill="none" stroke="url(#heat)" stroke-width="{f1(spike_w)}" stroke-linecap="round"/></g>',
        f'<g class="front" mask="url(#hf)"><use href="#sk" fill="none" stroke="{th["hot"]}" stroke-width="{f1(spike_w + 0.6)}" stroke-linecap="round"/></g>',
        f'<g fill="none" stroke="{th["hot"]}" stroke-width="2.2" stroke-linecap="round">{pulses}</g>',
        f'<g fill="none" stroke="{th["hot"]}" stroke-width="{f1(spike_w + 1.2)}" stroke-linecap="round">{flashes}</g>',
        f'<circle class="fd" style="--t:{D:.2f}s" cx="{cx}" cy="{cy}" r="2.5" fill="{th["ink"]}"/>',
        f'<circle class="ping" style="--t:{D:.2f}s" cx="{cx}" cy="{cy}" r="5" fill="none" stroke="{th["trace"]}" stroke-width="1.4"/>',
        f'<circle class="rp" cx="{cx}" cy="{cy}" r="5" fill="none" stroke="{th["trace"]}" stroke-width="1.2"/>',
        f'<text class="m fd" style="--t:{D:.2f}s" x="28" y="44" font-size="15" fill="{th["dim"]}">{doc.mono("M", f"{index:02d}")}</text>',
        typed(doc, lang_summary(data["langs"]), 372, 44, 15, th["dim"], D + 0.2, 1, anchor="end", cps=60),
        '<g clip-path="url(#nc)">' + "".join(f'<path class="nr" style="--k:{k}" d="{d}" fill="{th["ink"]}"/>' for k, (d, *_) in enumerate(title)) + "</g>",
        # when the pulse reaches the files, a glint runs across the name
        glint(doc, "tc", "".join(f'<path d="{d}"/>' for d, *_ in title), 28, 28 + tw, 380, 446, th["pour"], PULSE_EVERY, pulse0 + 1.3),
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
        f".rp{{opacity:0;transform-box:fill-box;transform-origin:center;animation:rping {PULSE_EVERY}s linear {pulse0 - 0.1:.2f}s infinite}}"
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


# ---------------------------------------------------------------- Fig. 4, when I ship

def render_ridge(times, theme, serif, italic, now):
    """One ridge per week, oldest at the back, tracing my public commits across the
    hours of the day. Quiet weeks stay grey; busy weeks run hot."""
    th = THEMES[theme]
    doc = Doc(1000, 620)
    rows, bins = 52, 48
    end = now.astimezone(TZ).date()
    local = [t.astimezone(TZ) for t in times]
    grid = [[0] * bins for _ in range(rows)]
    for t in local:
        back = (end - t.date()).days // 7  # whole weeks ago
        if 0 <= back < rows:
            grid[rows - 1 - back][(t.hour * 60 + t.minute) * bins // 1440] += 1
    kern = [math.exp(-0.5 * (d / 1.3) ** 2) for d in range(-4, 5)]
    smooth = [[sum(r[(i + d) % bins] * kern[d + 4] for d in range(-4, 5)) for i in range(bins)] for r in grid]  # midnight wraps
    # each ridge shows the shape of its week's day (height), while its colour carries how
    # busy the week was; weeks quieter than the median stay proportionally small
    row_peaks = sorted(max(r) for r in smooth if max(r) > 0) or [1]
    floor = row_peaks[len(row_peaks) // 2]
    totals = [sum(r) for r in grid]
    busiest = max(totals) or 1
    x0, x1, top_y, step, A = 292, 708, 168, 7.4, 70
    quiet, warm, hot = th["ridge"]

    def colour(k):
        i = math.sqrt(totals[k] / busiest)
        return mix(quiet, warm, i / 0.7) if i <= 0.7 else mix(warm, hot, (i - 0.7) / 0.3)

    comet_rows = sorted((k for k in range(rows) if totals[k]), key=lambda k: -totals[k])[:9]
    ridges = []
    for k in range(rows):
        base = top_y + k * step
        vals = smooth[k] + smooth[k][:1]  # 24:00 meets 00:00
        scale = max(max(smooth[k]), floor)
        pts = [(round(x0 + (x1 - x0) * i / bins, 1), round(base - A * (v / scale) ** 0.7, 1)) for i, v in enumerate(vals)]
        trace, flat = [], 0.0
        for (xa, ya), (xb, yb) in zip(pts, pts[1:]):
            if abs(yb - ya) < 0.05:
                flat += xb - xa
                continue
            if flat:
                trace.append("h" + f1(flat))
                flat = 0.0
            trace.append("l" + nums(xb - xa, yb - ya))
        if flat:
            trace.append("h" + f1(flat))
        trace = "".join(trace)
        # short S-curves in and out, so a ridge rises from its baseline instead of starting at a wall
        (ax, ay), (bx, by) = pts[0], pts[-1]
        lead = f"M{nums(ax - 22, base)}c{nums(11, 0, 11, ay - base, 22, ay - base)}"
        tail = f"c{nums(11, 0, 11, base - by, 22, base - by)}"
        body = f'<path d="{lead}{trace}{tail}Z" fill="{th["bg"]}" stroke="{colour(k)}"/>'
        if k in comet_rows:  # an occasional signal runs along the busiest weeks
            body += (f'<path class="cm" pathLength="1" style="--g:{4.6 + comet_rows.index(k) * 3:.1f}s" '
                     f'd="{lead}{trace}{tail}" fill="none" stroke="{th["hot"]}" stroke-width="1.8"/>')
        ridges.append(f'<g class="rw" style="--k:{k}">{body}</g>')

    # axis: hours along the bottom, a few months down the side
    axis = []
    for h in (0, 6, 12, 18, 24):
        x = x0 + (x1 - x0) * h / 24
        axis.append(f'<path d="M{f1(x)} 562v6" stroke="{th["faint"]}"/>'
                    f'<text x="{f1(x)}" y="584" class="m" font-size="11" letter-spacing="1" text-anchor="middle" fill="{th["dim"]}">{doc.mono("M", f"{h:02d}:00")}</text>')
    for k in range(rows):
        newest = end - dt.timedelta(days=7 * (rows - 1 - k))
        week = [newest - dt.timedelta(days=j) for j in range(7)]
        first = next((d for d in week if d.day == 1 and d.month in (1, 4, 7, 10)), None)
        if first:
            label = MONTHS[first.month - 1] + (f" {first.year}" if first.month == 1 else "")
            y = top_y + k * step
            axis.append(f'<path d="M{x0 - 32} {f1(y)}h6" stroke="{th["faint"]}"/>'
                        f'<text x="{x0 - 38}" y="{f1(y + 3.5)}" class="m" font-size="10" letter-spacing="1" text-anchor="end" fill="{th["dim"]}">{doc.mono("M", label)}</text>')
    for k, text in ((0, "A YEAR AGO"), (rows - 1, "THIS WEEK")):
        axis.append(f'<text x="{x1 + 32}" y="{f1(top_y + k * step + 3.5)}" class="m" font-size="10" letter-spacing="1" fill="{th["dim"]}">{doc.mono("M", text)}</text>')

    # the numbers
    hours = collections.Counter(t.hour for t in local)
    peak_hour = max(range(24), key=lambda h: hours[h]) if local else 0
    weekday = WEEKDAYS[collections.Counter(t.weekday() for t in local).most_common(1)[0][0]] if local else "—"
    after_dark = round(100 * sum(hours[h] for h in (22, 23, 0, 1, 2, 3, 4)) / max(1, len(local)))
    title, _, _ = italic.run("When I ship", 40, 100, 44)
    hour_txt, _, _ = serif.run(f"{peak_hour:02d}:00", 960, 243, 46, "end")
    day_txt, _, _ = italic.run(weekday, 960, 368, 46, "end")
    stats = [
        odometer(doc, serif, f"{len(local):,}", 960, 118, 46, "end", 1.4, th["ink"]),
        typed(doc, "PUBLIC COMMITS", 960, 144, 12, th["dim"], 2.2, 1.5, anchor="end"),
        "".join(f'<path class="fg" style="--k:{k};--b:1.7s" d="{d}" fill="{th["ink"]}"/>' for k, (d, *_) in enumerate(hour_txt)),
        typed(doc, "BUSIEST HOUR", 960, 269, 12, th["dim"], 2.4, 1.5, anchor="end"),
        "".join(f'<path class="fg" style="--k:{k};--b:2s" d="{d}" fill="{th["ink"]}"/>' for k, (d, *_) in enumerate(day_txt)),
        typed(doc, "BUSIEST DAY", 960, 394, 12, th["dim"], 2.6, 1.5, anchor="end"),
        odometer(doc, serif, f"{after_dark}%", 960, 493, 46, "end", 2.3, th["ink"]),
        typed(doc, "AFTER DARK", 960, 519, 12, th["dim"], 3.1, 1.5, anchor="end"),
    ]
    heading = ["".join(f'<path class="fg" style="--k:{k};--b:.6s" d="{d}" fill="{th["ink"]}"/>' for k, (d, *_) in enumerate(title)),
               typed(doc, "BY HOUR · IST", 40, 128, 12, th["dim"], 1.0, 1.5),
               typed(doc, "ONE RIDGE PER WEEK", 40, 147, 12, th["dim"], 1.3, 1.5)]

    doc.defs += [FEATHER,
                 f'<linearGradient id="scang" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{th["trace"]}" stop-opacity="0"/>'
                 f'<stop offset=".5" stop-color="{th["trace"]}"/><stop offset="1" stop-color="{th["trace"]}" stop-opacity="0"/></linearGradient>']
    doc.body = heading + axis + [f'<g stroke-width="1.2" stroke-linejoin="round">{"".join(ridges)}</g>',
                                 f'<rect class="scan" x="{x0 - 1}" y="60" width="2" height="500" fill="url(#scang)"/>'] + stats
    doc.css.append(
        ".rw{animation:wipe 1s cubic-bezier(.3,0,.2,1) backwards;animation-delay:calc(.9s + var(--k) * 45ms)}"
        "@keyframes wipe{from{clip-path:inset(-40px 100% -40px 0)}to{clip-path:inset(-40px 0 -40px 0)}}"
        ".cm{stroke-dasharray:.05 2;stroke-dashoffset:.06;animation:comet 27s linear var(--g) infinite}"
        "@keyframes comet{0%{stroke-dashoffset:.06}9%{stroke-dashoffset:-1.01}100%{stroke-dashoffset:-1.01}}"
        f".scan{{opacity:0;animation:scan 12s {INOUT} 5.2s infinite}}"
        f"@keyframes scan{{0%{{opacity:0;transform:translateX(0)}}3%{{opacity:.7}}21%{{opacity:.7}}24%{{opacity:0;transform:translateX({x1 - x0}px)}}"
        f"100%{{opacity:0;transform:translateX({x1 - x0}px)}}}}"
        f".fg{{animation:rise .8s {OUT} backwards;animation-delay:calc(var(--b) + var(--k) * 45ms)}}"
    )
    label = (f"A ridgeline of my public commits over the last year, one ridge per week with the oldest at the back, "
             f"across the 24 hours of the day: {len(local):,} commits, busiest at {peak_hour:02d}:00 and on {weekday}s, "
             f"{after_dark}% of them after dark, between 22:00 and 05:00.")
    return doc.render(label)


# ---------------------------------------------------------------- the closing card

def render_fin(theme, italic, now):
    th = THEMES[theme]
    doc = Doc(1000, 330)
    size = 60
    line1, _, _ = italic.words("Let’s build something", 500, 112, size, doc)
    line2, w2, _ = italic.words("that runs on your machine", 500 - 9, 186, size, doc)  # leaves room for the ember full stop
    hot_words = {"your", "machine"}
    k, words = 0, []
    for line, top in ((line1, 112), (line2, 186)):
        clip = doc.uid("lc")
        doc.defs.append(f'<clipPath id="{clip}"><rect x="0" y="{top - size}" width="1000" height="{size * 1.32:.0f}"/></clipPath>')
        groups = []
        for word, paths, _, _ in line:
            fill = "url(#fmolten)" if word in hot_words else th["ink"]
            groups.append(f'<g class="wd" style="--k:{k}" fill="{fill}">{"".join(paths)}</g>')
            k += 1
        words.append(f'<g clip-path="url(#{clip})">{"".join(groups)}</g>')

    ua, ub = line2[-2][2], line2[-1][3]  # "your" to the end of "machine"
    under = f"M{nums(ua, 204)}Q{nums((ua + ub) / 2, 212, ub, 202)}"
    ex, ey = ub + 13, 181
    email = "SREEVARSHAN1511@GMAIL.COM"
    doc.defs += [
        '<linearGradient id="fmolten" gradientUnits="userSpaceOnUse" x1="0" y1="760" x2="0" y2="-220">'
        + "".join(f'<stop offset="{o}" stop-color="{c}"/>' for o, c in zip((0, 0.35, 0.7, 1), th["molten"])) + "</linearGradient>",
        f'<radialGradient id="emb"><stop offset="0" stop-color="{th["trace"]}" stop-opacity=".55"/><stop offset="1" stop-color="{th["trace"]}" stop-opacity="0"/></radialGradient>',
    ]
    fin, _, _ = italic.run("Fin.", 1000, 314, 30, "end")
    doc.body = words + [
        f'<path class="ul" d="{under}" pathLength="1" fill="none" stroke="{th["pour"]}" stroke-width="2.4" stroke-linecap="round"/>',
        f'<path class="uc" d="{under}" pathLength="1" fill="none" stroke="{th["hot"]}" stroke-width="3" stroke-linecap="round"/>',
        f'<g class="em"><circle class="eh" cx="{f1(ex)}" cy="{ey}" r="22" fill="url(#emb)"/><circle cx="{f1(ex)}" cy="{ey}" r="5.5" fill="{th["trace"]}"/></g>',
        f'<circle class="ping" style="--t:2.05s" cx="{f1(ex)}" cy="{ey}" r="6" fill="none" stroke="{th["trace"]}" stroke-width="1.4"/>',
        typed(doc, email, 500, 262, 14, th["ink"], 2.6, 2.5, family="MM", anchor="middle", cps=36),
        typed(doc, "REDRAWN NIGHTLY FROM LIVE GITHUB DATA · " + day(now.date()), 0, 312, 11, th["dim"], 3.2, 1.2, cps=90),
        "".join(f'<path class="fg" style="--k:{k}" d="{d}" fill="{th["ink"]}"/>' for k, (d, *_) in enumerate(fin)),
    ]
    doc.css.append(
        f".wd{{animation:wrise 1s {OUT} backwards;animation-delay:calc(.7s + var(--k) * 85ms)}}@keyframes wrise{{from{{transform:translateY({size + 20}px)}}}}"
        f".ul{{animation:grow 1.1s {INOUT} 1.6s backwards}}"
        ".uc{stroke-dasharray:.12 3;stroke-dashoffset:.13;animation:fuse2 8s linear 3.6s infinite}"
        "@keyframes fuse2{0%{stroke-dashoffset:.13}16%{stroke-dashoffset:-1.01}100%{stroke-dashoffset:-1.01}}"
        f".em{{transform-box:fill-box;transform-origin:center;animation:rise .6s {OUT} 1.95s backwards}}"
        ".eh{transform-box:fill-box;transform-origin:center;animation:breathe 2.6s ease-in-out 2.6s infinite}"
        "@keyframes breathe{0%,100%{transform:scale(1);opacity:1}50%{transform:scale(1.35);opacity:.55}}"
        f".fg{{animation:rise .8s {OUT} backwards;animation-delay:calc(3.6s + var(--k) * 60ms)}}"
    )
    return doc.render(f"Let's build something that runs on your machine. {email.lower()}")


# ---------------------------------------------------------------- Fig. 5, the year in 3D

def year_stl(weeks):
    """The last 52 complete weeks as towers standing on a ring, clockwise from the top like
    Fig. 1, as an ASCII STL that GitHub renders with its 3D viewer."""
    sums = [sum(c for _, c in w) for w in weeks]
    n, top = len(sums), math.log1p(max(sums)) or 1
    r1, r2 = 46, 70  # tower footprint
    facets = []

    def g(v, digits=1):
        out = f"{v:.{digits}f}".rstrip("0").rstrip(".")
        return "0" if out in ("", "-0") else out

    def P(r, a, z):
        return r * math.cos(math.radians(a)), r * math.sin(math.radians(a)), z

    def quad(pts, inside):
        """Two triangles, wound so the face points away from `inside`."""
        a, b, c = pts[:3]
        u, v = [b[i] - a[i] for i in range(3)], [c[i] - a[i] for i in range(3)]
        nrm = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]]
        centre = [sum(p[i] for p in pts) / 4 for i in range(3)]
        if sum(nrm[i] * (centre[i] - inside[i]) for i in range(3)) < 0:
            pts, nrm = pts[::-1], [-x for x in nrm]
        length = math.sqrt(sum(x * x for x in nrm)) or 1
        normal = " ".join(g(x / length, 2) for x in nrm)
        for tri in ((pts[0], pts[1], pts[2]), (pts[0], pts[2], pts[3])):
            facets.append(f"facet normal {normal}\nouter loop\n"
                          + "".join(f"vertex {g(x)} {g(y)} {g(z)}\n" for x, y, z in tri) + "endloop\nendfacet\n")

    for k, total in enumerate(sums):
        if not total:
            continue
        h = 4 + 66 * math.log1p(total) / top
        a1, a2 = 90 - (k + 0.12) * 360 / n, 90 - (k + 0.88) * 360 / n
        inside = P((r1 + r2) / 2, (a1 + a2) / 2, h / 2)
        b = [P(r1, a1, 0), P(r2, a1, 0), P(r2, a2, 0), P(r1, a2, 0)]
        t = [(x, y, h) for x, y, _ in b]
        for face in (t, [b[1], b[2], t[2], t[1]], [b[0], b[3], t[3], t[0]], [b[0], b[1], t[1], t[0]], [b[3], b[2], t[2], t[3]]):
            quad(face, inside)
    for j in range(n):  # the plinth they stand on
        a1, a2 = 90 - j * 360 / n, 90 - (j + 1) * 360 / n
        inside = P(58, (a1 + a2) / 2, -1.5)
        for face in ([P(40, a1, 0), P(76, a1, 0), P(76, a2, 0), P(40, a2, 0)],
                     [P(40, a1, -3), P(76, a1, -3), P(76, a2, -3), P(40, a2, -3)],
                     [P(76, a1, -3), P(76, a2, -3), P(76, a2, 0), P(76, a1, 0)],
                     [P(40, a1, -3), P(40, a2, -3), P(40, a2, 0), P(40, a1, 0)]):
            quad(face, inside)
    return "solid year\n" + "".join(facets) + "endsolid year\n"


def update_readme(path, stl):
    """Put the model between the README's markers. Returns True if the README changed."""
    text = Path(path).read_text(encoding="utf-8")
    a, b = text.find(STL_START), text.find(STL_END)
    if a < 0 or b < a:
        return False
    new = text[:a + len(STL_START)] + "\n\n```stl\n" + stl + "```\n\n" + text[b:]
    if new == text:
        return False
    Path(path).write_text(new, encoding="utf-8", newline="\n")
    return True


# ---------------------------------------------------------------- main

def main():
    args = sys.argv[1:]
    readme = None
    if "--readme" in args:
        i = args.index("--readme")
        readme = args[i + 1]
        del args[i:i + 2]
    out = Path(args[0] if args else "dist")
    out.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc)
    serif, italic = Face(SERIF), Face(SERIF_ITALIC)
    weeks = contribution_weeks()
    days = [d for w in weeks for d in w][-365:]
    stl = year_stl([w for w in weeks if len(w) == 7][-52:])  # complete weeks only, so it changes once a week
    (out / "year.stl").write_text(stl, encoding="utf-8")
    if readme and update_readme(readme, stl):
        print(f"updated the 3D year in {readme}")
    commits = recent_commits()
    times = commit_times()
    for theme in THEMES:
        (out / f"year-{theme}.svg").write_text(render_year(days, theme, serif, italic), encoding="utf-8")
        (out / f"band-{theme}.svg").write_text(render_band(commits, theme, italic, now), encoding="utf-8")
        (out / f"ridge-{theme}.svg").write_text(render_ridge(times, theme, serif, italic, now), encoding="utf-8")
        (out / f"fin-{theme}.svg").write_text(render_fin(theme, italic, now), encoding="utf-8")
        for name, (label, note, spark_at) in RULES.items():
            (out / f"rule-{name}-{theme}.svg").write_text(render_rule(label, note, theme, spark_at), encoding="utf-8")
    for i, (repo, name, tagline) in enumerate(PROJECTS, 1):
        data = repo_data(repo)
        for theme in THEMES:
            (out / f"card-{repo.lower()}-{theme}.svg").write_text(
                render_card(i, name, tagline, data, theme, now, serif), encoding="utf-8")
    print(f"wrote {len(list(out.glob('*.svg')))} files to {out}")


if __name__ == "__main__":
    main()
