"""Render the profile README cards into cards/.

    python render.py            animated cards
    STATIC=1 python render.py   final frame only, for screenshots

Contribution data comes from data/github.json (refreshed daily by .github/workflows/cards.yml).
"""
import base64
import datetime as dt
import html
import io
import itertools
import json
import math
import os
import random
import re
from collections import defaultdict
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

ROOT = Path(__file__).parent
STATIC = os.environ.get("STATIC") == "1"

# White and blue on a near-black night sheet
BG, LINE, INK, ACCENT = "#0b1020", "#1f2945", "#eef2ff", "#3b66ff"
LEVELS = {"NONE": "#161d33", "FIRST_QUARTILE": "#1e3170", "SECOND_QUARTILE": "#2949b3",
          "THIRD_QUARTILE": ACCENT, "FOURTH_QUARTILE": "#9db4ff"}
LANG_COLOURS = [ACCENT, INK, "#6f7a99", "#3a4466"]
FONTS = {"n": ROOT / "fonts/Nippo-Medium.woff2", "s": ROOT / "fonts/Satoshi-Variable.woff2",
         "m": ROOT / "fonts/JetBrainsMono-Regular.ttf"}

NAME = ("FILIP", "MIKAN")
ABOUT = ("Third-year Computer Science student at the Technical Faculty, University of Rijeka, and "
         "software developer at TRON. I build web apps and GIS tools, and spend the rest of my time "
         "on Linux, automation and LLM experiments.")
FACTS = [("Studying", "Computer Science, UNIRI"), ("Working", "Software developer, TRON"),
         ("Based", "Karlovac, Croatia")]
COORDS = "45.4929° N  15.5553° E"
TILES = [  # links live in README.md
    ("website", "Website", "fmikan.me", "Studio and client work"),
    ("linkedin", "LinkedIn", "filipmikan", "Experience and contact"),
    ("telegram", "Telegram", "@Filip_Mikan", "Fastest way to reach me"),
]
STACK = [
    ("Frontend", ["React", "Next.js", "TypeScript", "HTML", "CSS"]),
    ("Backend & data", ["C#", ".NET", "Java", "PostgreSQL"]),
    ("GIS", ["QGIS", "QField", "GDAL", "GeoPackage", "Spatial data processing"]),
    ("Infrastructure", ["Linux", "Docker", "Kubernetes", "Ansible", "Git", "GitHub", "VS Code", "Figma"]),
    ("Exploring", ["LLMs", "AI workflows", "Automation"]),
]
FEATURED = {  # repo name -> blurb (falls back to the GitHub description when empty)
    "TRON-GRAVE": "Reads gravestone photos with Claude Vision and turns the inscriptions into "
                  "clean CSV records for Croatian cemetery archives.",
    "Ri-Hack-2026": "StackOff, a ranked 1v1 IT quiz built in three days at Ri-Hack 4.0. "
                    "Every lost duel ends with a breakdown of what you got wrong.",
}

# One timeline across the page so the stack plays top to bottom (seconds)
T_HERO, T_TILES, T_STACK, T_CHART, T_REPOS = 0, 1.2, 1.6, 2.2, 3.0
T_GRAPH = T_REPOS + .25 * len(FEATURED) + .2

CSS = """.still{display:none}
.rise{animation:rise .8s cubic-bezier(.2,.8,.2,1) both}
.up{animation:up .8s cubic-bezier(.2,.8,.2,1) both}
.pop{transform-box:fill-box;transform-origin:center;animation:pop .55s cubic-bezier(.3,1.6,.5,1) both}
.draw{stroke-dasharray:1;animation:draw 1.6s cubic-bezier(.4,0,.2,1) both}
.ink{stroke-dasharray:1400;animation:ink 2.4s cubic-bezier(.4,0,.2,1) both}
.wipe{animation:wipe 1s cubic-bezier(.6,0,.2,1) both}
.roll{animation:roll 1.8s cubic-bezier(.2,.8,.1,1) both}
.march{animation:march 1.6s linear infinite}
@keyframes rise{from{opacity:0;transform:translateY(14px)}}
@keyframes up{from{transform:translateY(110px)}}
@keyframes pop{from{opacity:0;transform:scale(.2)}}
@keyframes draw{from{stroke-dashoffset:1}}
@keyframes ink{from{stroke-dashoffset:1400}}
@keyframes wipe{from{clip-path:inset(0 100% 0 0)}}
@keyframes roll{from{transform:translateY(0)}}
@keyframes march{to{stroke-dashoffset:-12}}"""
# Every element's resting style is its final frame, so switching animation off shows the end state.
# SMIL can't be stopped from CSS, so each SMIL element has a .still twin (or is decoration that just hides).
MOTION_OFF = "*{animation:none!important}.smil{display:none}.still{display:inline}"
CSS += MOTION_OFF if STATIC else f"@media (prefers-reduced-motion:reduce){{{MOTION_OFF}}}"


def _metrics(key, **axes):
    f = TTFont(FONTS[key])
    if axes:
        f = instantiateVariableFont(f, axes)
    return f.getBestCmap(), f["hmtx"], f["head"].unitsPerEm


METRICS = {"s": _metrics("s", wght=500), "n": _metrics("n"), "m": _metrics("m")}
_ids = itertools.count()


def uid(prefix):
    return f"{prefix}{next(_ids)}"


def width(s, size, font="s"):
    cmap, hmtx, upm = METRICS[font]
    return sum(hmtx[cmap.get(ord(c), ".notdef")][0] for c in s) * size / upm


def wrap(s, size, max_w):
    lines = [""]
    for word in s.split():
        trial = f"{lines[-1]} {word}".strip()
        if width(trial, size) <= max_w or not lines[-1]:
            lines[-1] = trial
        else:
            lines.append(word)
    return lines


def el(tag, body=None, **kw):
    a = "".join(f' {k.rstrip("_").replace("_", "-")}="{v}"' for k, v in kw.items() if v is not None)
    return f"<{tag}{a}/>" if body is None else f"<{tag}{a}>{body}</{tag}>"


def txt(s, x, y, size=16, font="s", op=None, fill=INK, **kw):
    return el("text", html.escape(s), x=x, y=y, font_family=font, font_size=size, fill=fill,
              fill_opacity=op, **kw)


def label(s, x, y, op=.55, **kw):
    return txt(s.upper(), x, y, 11, "m", op=op, letter_spacing=".1em", **kw)


def label_width(s):
    return width(s.upper(), 11, "m") + len(s) * 1.1


def delay(s):
    return f"animation-delay:{s:.2f}s"


def tween(attr, start, end, wait, dur=.9):
    """SMIL tween that holds `start` for `wait` seconds (SMIL has no backwards fill), then eases to `end`."""
    k = wait / (wait + dur)
    return el("animate", attributeName=attr, values=f"{start};{start};{end}", keyTimes=f"0;{k:.3f};1",
              calcMode="spline", keySplines="0 0 1 1;.2 .8 .2 1", dur=f"{wait + dur:.2f}s", fill="freeze")


def grow(x, y, w, h, wait, **kw):
    """Rect growing upward. SMIL, not CSS scale, so the rounded corners stay round."""
    return (el("rect", x=x, y=y, width=w, height=h, class_="still", **kw)
            + el("rect", tween("height", 0, h, wait) + tween("y", y + h, y, wait),
                 x=x, y=y + h, width=w, height=0, class_="smil", **kw))


def odometer(s, x, y, size, wait, font="n"):
    """Digits roll into place like a mechanical counter; everything else in `s` stays put."""
    lh, out, cx = size * 1.1, "", x
    for i, c in enumerate(s):
        w = width(c, size, font)
        if c.isdigit():
            n = int(c) + 10  # roll through one full turn before landing
            strip = "".join(txt(str(k % 10), round(cx + w / 2, 1), round(y + k * lh, 1), size, font,
                                text_anchor="middle") for k in range(n + 1))
            out += el("g", strip, class_="roll",
                      style=f"transform:translateY(-{n * lh:.1f}px);animation-delay:{wait + .07 * i:.2f}s")
        else:
            out += txt(c, round(cx, 1), y, size, font)
        cx += w
    cid = uid("o")
    clip = el("rect", x=round(x - 4), y=round(y - size), width=round(cx - x + 8), height=round(size * 1.25))
    return el("clipPath", clip, id=cid) + el("g", out, clip_path=f"url(#{cid})")


def topo(cx, cy, rings, gap, seed, wait, stroke=INK):
    """Contour lines of a made-up hill. Every fifth is an index contour, heavier, as on survey maps."""
    rnd = random.Random(seed)
    waves = [(rnd.uniform(.04, .12), rnd.randint(2, 5), rnd.uniform(0, 2 * math.pi)) for _ in range(3)]
    out = ""
    for k in range(1, rings + 1):
        pts = []
        for i in range(48):
            t = 2 * math.pi * i / 48
            r = gap * k * (1 + sum(a * math.sin(n * t + p + .25 * k) for a, n, p in waves))
            pts.append((cx + r * math.cos(t), cy + r * .75 * math.sin(t)))
        mids = [((x1 + x2) / 2, (y1 + y2) / 2) for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1])]
        d = f"M{mids[-1][0]:.1f} {mids[-1][1]:.1f}" + "".join(
            f"Q{x:.1f} {y:.1f} {mx:.1f} {my:.1f}" for (x, y), (mx, my) in zip(pts, mids)) + "Z"
        index = k % 5 == 0
        out += el("path", d=d, fill="none", stroke=stroke, stroke_opacity=.24 if index else .1,
                  stroke_width=1.4 if index else 1, pathLength=1, class_="draw", style=delay(wait + .07 * k))
    return out


def font_face(key, text):
    font = TTFont(FONTS[key], recalcTimestamp=False)  # same input, same bytes: no daily no-op commits
    s = subset.Subsetter(subset.Options(hinting=False))  # pyftsubset's engine
    s.populate(text=text)
    s.subset(font)
    font.flavor = "woff"
    buf = io.BytesIO()
    font.save(buf)
    weight = "font-weight:300 900;" if key == "s" else ""
    uri = "data:font/woff;base64," + base64.b64encode(buf.getvalue()).decode()
    return f'@font-face{{font-family:{key};{weight}src:url({uri}) format("woff")}}'


def card(name, w, h, body, title, bg=BG):
    text = html.unescape("".join(re.findall(r">([^<]+)<", body)))
    faces = "".join(font_face(k, text) for k in FONTS if f'font-family="{k}"' in body)
    title = html.escape(title)
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
           f'role="img" aria-label="{title}"><title>{title}</title><style>{faces}{CSS}</style>'
           f'<clipPath id="card"><rect width="{w}" height="{h}" rx="20"/></clipPath>'
           f'<rect x=".5" y=".5" width="{w - 1}" height="{h - 1}" rx="20" fill="{bg}" stroke="{LINE}"/>'
           f'<g clip-path="url(#card)">{body}</g></svg>')
    (ROOT / "cards" / f"{name}.svg").write_text(svg)


def date(iso):
    d = dt.date.fromisoformat(iso[:10])
    return f"{d.day} {d:%b %Y}"


def plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def stats(days):
    counts = [d["contributionCount"] for d in days]
    run = longest = 0
    for c in counts:
        run = run + 1 if c else 0
        longest = max(longest, run)

    def trailing(cs):
        return next((i for i, c in enumerate(reversed(cs)) if not c), len(cs))

    months = defaultdict(int)
    for d in days:
        months[d["date"][:7]] += d["contributionCount"]
    return {
        "current": trailing(counts) or trailing(counts[:-1]),  # today may simply not have started yet
        "longest": longest,
        "active": sum(map(bool, counts)),
        "busiest": max(days, key=lambda d: d["contributionCount"]),
        "months": list(months.items())[-12:],
    }


def marker(x, y, wait):
    """Summit of the hero map: the portrait if there is one (keep it small, it is embedded as-is), else a dot."""
    portrait = next(ROOT.glob("portrait.*"), None)
    if portrait:
        r, cid = 76, uid("p")
        mime = {"jpg": "jpeg"}.get(portrait.suffix[1:].lower(), portrait.suffix[1:].lower())
        uri = f"data:image/{mime};base64," + base64.b64encode(portrait.read_bytes()).decode()
        out = el("clipPath", el("circle", cx=x, cy=y, r=r), id=cid) + el(
            "image", href=uri, x=x - r, y=y - r, width=2 * r, height=2 * r, clip_path=f"url(#{cid})",
            preserveAspectRatio="xMidYMid slice", class_="pop", style=delay(wait))
    else:
        r = 6
        out = el("circle", cx=x, cy=y, r=r, fill=ACCENT, class_="pop", style=delay(wait))
    pulse = (el("animate", attributeName="r", values=f"{r};{r + 26}", dur="2.4s", begin=f"{wait + .5}s",
                repeatCount="indefinite")
             + el("animate", attributeName="stroke-opacity", values=".9;0", dur="2.4s", begin=f"{wait + .5}s",
                  repeatCount="indefinite"))
    out += el("circle", pulse, cx=x, cy=y, r=r, fill="none", stroke=ACCENT, stroke_width=1.5, stroke_opacity=0,
              class_="smil")
    return out + label("Karlovac, HR", x, y + r + 26, text_anchor="middle", class_="rise", style=delay(wait + .2))


def hero():
    W, size = 840, 104
    b = topo(640, 200, 12, 24, seed=7, wait=T_HERO) + marker(640, 200, T_HERO + 1)
    b += el("g", txt("</MIKI>", 48, 60, 18, "n") + label(COORDS, W - 48, 60, text_anchor="end"),
            class_="rise", style=delay(T_HERO))
    for i, (word, y) in enumerate([(NAME[0], 184), (NAME[1], 288)]):
        x, letters = 48, ""
        for j, c in enumerate(word):
            letters += txt(c, round(x, 1), y, size, "n", class_="up", style=delay(T_HERO + .2 + .25 * i + .05 * j))
            x += width(c, size, "n")
        cid = uid("l")
        b += el("clipPath", el("rect", x=0, y=y - size * .8, width=W, height=size * .9), id=cid)
        b += el("g", letters, clip_path=f"url(#{cid})")
    b += txt(".", round(x, 1), 288, size, "n", fill=ACCENT, class_="pop", style=delay(T_HERO + .9))
    lines = wrap(ABOUT, 19, 520)
    b += el("g", "".join(txt(s, 48, 344 + 28 * i, 19, op=.72) for i, s in enumerate(lines)),
            class_="rise", style=delay(T_HERO + .8))
    y = 344 + 28 * (len(lines) - 1) + 40
    b += el("line", x1=48, x2=W - 48, y1=y + .5, y2=y + .5, stroke=LINE, class_="wipe", style=delay(T_HERO + 1))
    for i, (k, v) in enumerate(FACTS):
        b += el("g", label(k, 48 + 256 * i, y + 32) + txt(v, 48 + 256 * i, y + 56, 15, op=.92),
                class_="rise", style=delay(T_HERO + 1.1 + .1 * i))
    card("hero", W, y + 84, b, f"{' '.join(NAME).title()}. {ABOUT}")


def tile(i, key, name, value, note):
    d = T_TILES + .12 * i
    b = topo(262, 176, 6, 14, seed=11 + i, wait=d)
    b += el("path", d="M232 44 L248 28 M234 28 H248 V42", fill="none", stroke=ACCENT, stroke_width=2,
            stroke_linecap="round", stroke_linejoin="round", pathLength=1, class_="draw", style=delay(d + .3))
    b += el("g", label(name, 24, 40) + txt(value, 24, 108, 26, "n") + txt(note, 24, 136, 14, op=.6),
            class_="rise", style=delay(d))
    card(f"tile-{key}", 272, 168, b, f"{name}: {value}")


def stack():
    W, X0 = 840, 208
    tools = sum(len(t) for _, t in STACK)
    b = el("g", label("Tech stack", 40, 56) + label(f"{tools} tools / {len(STACK)} areas", W - 40, 56,
                                                   text_anchor="end"), class_="rise", style=delay(T_STACK))
    y = 80
    for i, (group, names) in enumerate(STACK):
        d = T_STACK + .15 + .12 * i
        exploring = group == "Exploring"  # dashed, still being learned
        b += el("line", x1=40, x2=W - 40, y1=y + .5, y2=y + .5, stroke=LINE, class_="wipe", style=delay(d))
        b += el("g", label(f"{i + 1:02d}", 40, y + 36, op=None, fill=ACCENT) + label(group, 72, y + 36),
                class_="rise", style=delay(d))
        x, top = X0, y + 16
        for j, tool in enumerate(names):
            w = width(tool, 14) + 22
            if x + w > W - 40:
                x, top = X0, top + 40
            chip = el("rect", x=round(x, 1), y=top, width=round(w, 1), height=30, rx=15, fill="none", stroke=INK,
                      stroke_opacity=.3, stroke_dasharray="3 3" if exploring else None,
                      class_="march" if exploring else None)
            b += el("g", chip + txt(tool, round(x + w / 2, 1), top + 20, 14, font_weight=500, text_anchor="middle"),
                    class_="pop", style=delay(d + .1 + .035 * j))
            x += w + 8
        y = top + 46
    b += el("line", x1=40, x2=W - 40, y1=y + .5, y2=y + .5, stroke=LINE, class_="wipe", style=delay(T_STACK + .8))
    card("stack", W, y + 32, b, "Tech stack. " + ". ".join(f"{g}: {', '.join(n)}" for g, n in STACK))


def contributions(days, total):
    s = stats(days)
    W, base, top = 840, 330, 200
    peak = max(v for _, v in s["months"]) or 1
    b = el("g", label("Contributions per month", 40, 56) + label("Last 12 months", W - 40, 56, text_anchor="end")
           + txt("contributions in the last year", 40, 160, 16, op=.6), class_="rise", style=delay(T_CHART))
    b += odometer(f"{total:,}", 40, 128, 56, T_CHART + .1)
    b += el("clipPath", el("rect", x=0, y=0, width=W, height=base), id="plot")
    b += el("line", x1=40, x2=W - 40, y1=base + .5, y2=base + .5, stroke=LINE)
    slot = (W - 80) / 12
    bars = labels = ""
    for i, (month, v) in enumerate(s["months"]):
        cx = 40 + slot * (i + .5)
        wait = T_CHART + .4 + .06 * i
        h = max(4, round(v / peak * (base - top))) if v else 0
        if h:
            bars += grow(round(cx - 12), base - h, 24, h + 4, wait, rx=4, fill=ACCENT)
        name = dt.date.fromisoformat(month + "-01").strftime("%b")
        labels += label(name, round(cx), base + 26, op=None if v == peak else .55, text_anchor="middle")
        if v == peak:
            labels += txt(str(v), round(cx), base - h - 10, 13, font_weight=700, text_anchor="middle",
                          class_="rise", style=delay(wait + .7))
    b += el("g", bars, clip_path="url(#plot)") + el("g", labels, class_="rise", style=delay(T_CHART + .3))
    b += el("line", x1=40, x2=W - 40, y1=382.5, y2=382.5, stroke=LINE, class_="wipe", style=delay(T_CHART + .9))
    busy = s["busiest"]
    current = f"Current streak {plural(s['current'], 'day')}" if s["current"] else "Over the last year"
    for i, (name, value, sub) in enumerate([
        ("Longest streak", plural(s["longest"], "day"), current),
        ("Active days", str(s["active"]), f"of the last {len(days)}"),
        ("Busiest day", date(busy["date"]), plural(busy["contributionCount"], "contribution")),
    ]):
        x, d = 40 + 260 * i, T_CHART + 1 + .15 * i
        b += el("g", label(name, x, 418) + txt(sub, x, 486, 14, op=.6), class_="rise", style=delay(d))
        b += odometer(value, x, 458, 30, d + .1)
    card("contributions", W, 520, b, f"{total} contributions in the last year, streak, active days and busiest day")


def repo(i, r, blurb):
    W, d = 840, T_REPOS + .25 * i
    lines = wrap(blurb or r["description"] or "", 17, 540)
    y = 176 + 26 * len(lines) + 4  # language bar
    b = txt(f"{i + 1:02d}", W - 40, y - 24, 180, "n", fill="none", stroke=INK, stroke_opacity=.2, stroke_width=1.2,
            text_anchor="end", class_="ink", style=delay(d))
    meta = f"{plural(r['stargazerCount'], 'star')} / updated {date(r['pushedAt'])}"
    b += el("g", label("Featured repository", 40, 56) + txt(r["name"], 40, 112, 38, "n") + label(meta, 40, 140),
            class_="rise", style=delay(d))
    b += el("g", "".join(txt(s, 40, 176 + 26 * j, 17, op=.72) for j, s in enumerate(lines)),
            class_="rise", style=delay(d + .1))
    langs = r["languages"]
    total = langs["totalSize"] or 1
    bar = legend = ""
    x, lx = 40.0, 40.0
    for e, colour in zip(langs["edges"], LANG_COLOURS):
        share = e["size"] / total
        w = max(2, share * (W - 80) - 2)  # 2px surface gap between segments
        bar += el("rect", x=round(x, 1), y=y, width=round(w, 1), height=8, rx=4, fill=colour)
        x += w + 2
        text = f"{e['node']['name']} {share:.0%}" if share >= .005 else f"{e['node']['name']} <1%"
        legend += el("rect", x=round(lx), y=y + 30, width=8, height=8, rx=2, fill=colour)
        legend += txt(text, round(lx) + 14, y + 38, 13, op=.6)
        lx += 14 + width(text, 13) + 24
    b += el("g", bar, class_="wipe", style=delay(d + .3)) + el("g", legend, class_="rise", style=delay(d + .6))
    card(f"repo-{r['name']}", W, y + 70, b, f"{r['name']}: {' '.join(lines)}")


def graph(weeks):
    W, step, y0 = 840, 14, 88
    x0 = (W - len(weeks) * step + 3) / 2
    end = round(W - 40 - label_width("More") - 8)  # right edge of the legend swatches
    b = el("g", label("Contribution graph", 40, 48)
           + label("Less", end - 5 * step - 5, 48, text_anchor="end")
           + "".join(el("rect", x=end - (5 - i) * step + 3, y=38, width=11, height=11, rx=2, fill=c)
                     for i, c in enumerate(LEVELS.values()))
           + label("More", W - 40, 48, text_anchor="end"), class_="rise", style=delay(T_GRAPH))
    busiest = max((d for w in weeks for d in w), key=lambda d: d["contributionCount"])
    last_month, last_x, cells = None, -99, ""
    for c, week in enumerate(weeks):
        x = round(x0 + c * step, 1)
        month = week[0]["date"][:7]
        if month != last_month and x - last_x > 32:
            b += label(dt.date.fromisoformat(week[0]["date"]).strftime("%b"), x, y0 - 12,
                       class_="rise", style=delay(T_GRAPH))
            last_x = x
        last_month = month
        for d in week:
            row = (dt.date.fromisoformat(d["date"]).weekday() + 1) % 7  # Sunday first, like GitHub
            y = y0 + row * step
            cells += el("rect", x=x, y=y, width=11, height=11, rx=2, fill=LEVELS[d["contributionLevel"]],
                        class_="pop", style=delay(T_GRAPH + .2 + .012 * (c + 3 * row)))  # diagonal wave
            if d is busiest and d["contributionCount"]:
                cells += el("rect", x=x - 2, y=y - 2, width=15, height=15, rx=3, fill="none", stroke=INK,
                            stroke_width=1.5, class_="pop", style=delay(T_GRAPH + 1.2))
    card("graph", W, y0 + 7 * step + 29, b + cells, "Contribution graph for the last 12 months")


def main():
    user = json.loads((ROOT / "data/github.json").read_text())["data"]["user"]
    cal = user["contributionsCollection"]["contributionCalendar"]
    weeks = [w["contributionDays"] for w in cal["weeks"]]
    repos = {r["name"]: r for r in user["repositories"]["nodes"]}
    (ROOT / "cards").mkdir(exist_ok=True)
    hero()
    for i, t in enumerate(TILES):
        tile(i, *t)
    stack()
    contributions([d for w in weeks for d in w], cal["totalContributions"])
    for i, (name, blurb) in enumerate(FEATURED.items()):
        repo(i, repos[name], blurb)
    graph(weeks)


if __name__ == "__main__":
    main()
