"""
Generate the brainfilter logo, wordmark and site icon.

The BIDS mark (half brain and file tree), file and folder glyphs are
adapted from the BIDS logo
(github.com/bids-standard/bids-specification, CC BY 4.0).

Usage: python tools/artwork/make_logos.py [OUTDIR]   (default: docs/images)
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
OUT = sys.argv[1] if len(sys.argv) > 1 else str(HERE.parents[1] / 'docs' / 'images')
# BIDS mark without its lettering: half brain + file tree, 181.3 x 213.6
MARK = (HERE / 'bids_mark.txt').read_text().strip()
MARK_W, MARK_H = 181.32, 213.6
FILE = ('<polygon points="25.85 9.74 25.85 9.77 16.69 9.77 16.69 0 25.85 9.74"/>'
        '<polygon points="13.56 12.9 25.85 12.9 25.85 30.63 0 30.63 0 0 13.56 0 13.56 12.9"/>')
FILE_W, FILE_H = 25.85, 30.63
FOLDER = ('<path transform="translate(-105.6 -26.18)" d="M142.7,29.61H127.82l-.61-1.85A2.3,2.3,0,0,0,125,26.18H113.83a2.3,2.3,0,0,0-2.19,1.6l-.59,1.83h-1.83a3.65,3.65,0,0,0-3.65,3.64V55.31A3.65,3.65,0,0,0,109.22,59H142.7a3.63,3.63,0,0,0,3.63-3.64V33.25A3.63,3.63,0,0,0,142.7,29.61Zm-34.56,5.83,2.23-3H141.5l1.65,3Z"/>')
FOLDER_W, FOLDER_H = 40.73, 32.82

INK, CREMA, CREAM = '#2b1b13', '#c98b4e', '#f6ecdd'
PAPER, PAPER_DARK = '#f1e2cb', '#cfb28c'   # unbleached filter paper
GLASS, GLASS_DARK = '#e6eceb', '#2a3438'   # coffee server
COFFEE = '#6b3e26'
ATTR = ('<!-- BIDS mark, file and folder glyphs adapted from the BIDS logo '
        '(github.com/bids-standard/bids-specification, CC BY 4.0). -->')


def mark(cx: float, cy: float, h: float, cls: str) -> str:
    """Draw the BIDS mark, centred on (cx, cy), h high."""
    s = h / MARK_H
    x, y = cx - MARK_W * s / 2, cy - h / 2
    return (f'<g class="{cls}" transform="translate({x:.2f} {y:.2f}) '
            f'scale({s:.4f})">{MARK}</g>')


def glyph(kind: str, cx: float, cy: float, w: float, cls: str, rot: float = 0) -> str:
    """Draw a BIDS file or folder glyph, centred on (cx, cy), w wide."""
    body, gw, gh = (FILE, FILE_W, FILE_H) if kind == 'file' else (FOLDER, FOLDER_W, FOLDER_H)
    s = w / gw
    return (f'<g class="{cls}" transform="translate({cx:.1f} {cy:.1f}) rotate({rot}) '
            f'scale({s:.4f}) translate({-gw/2:.2f} {-gh/2:.2f})">{body}</g>')

def drop(cx: float, cy: float, h: float, cls: str) -> str:
    """Draw a teardrop (a circle with a pointed top), centred on (cx, cy), h high."""
    r = h * 0.36
    return (f'<path class="{cls}" d="M{cx} {cy - h/2} '
            f'C{cx + r*0.35} {cy - h/2 + h*0.28} {cx + r} {cy + h/2 - 1.55*r} {cx + r} {cy + h/2 - r} '
            f'A{r} {r} 0 0 1 {cx - r} {cy + h/2 - r} '
            f'C{cx - r} {cy + h/2 - 1.55*r} {cx - r*0.35} {cy - h/2 + h*0.28} {cx} {cy - h/2}Z"/>')

DARK = f'''@media (prefers-color-scheme: dark) {{
      .ink{{fill:{CREAM}}} .ink-s{{stroke:{CREAM}}} .cream{{fill:{INK}}} .paper{{fill:{PAPER_DARK}}}
      .glass{{fill:{GLASS_DARK}}}
    }}'''

def style(extra: str = '', themed: bool = True) -> str:
    """Return the palette as a <style> element (themed: swap it in dark mode)."""
    return f'''<style>
    .ink{{fill:{INK}}} .ink-s{{fill:none;stroke:{INK}}}
    .cream{{fill:{CREAM}}} .paper{{fill:{PAPER}}} .crema{{fill:{CREMA}}} .fixed-ink{{fill:{INK}}}
    .glass{{fill:{GLASS}}} .coffee{{fill:{COFFEE}}}
    {DARK if themed else ''}{extra}
  </style>'''


# ---------------------------------------------------------------- brainfilter
def brainfilter(themed: bool = True) -> str:
    """Draw the logo: a pour-over dripper on a glass coffee server."""
    cx = 248
    # dripper
    rim_y, base_y = 70, 236
    rt, bt = 148, 40             # half widths of the cone at rim / base
    cone = (f'M{cx-rt} {rim_y} L{cx+rt} {rim_y} L{cx+bt} {base_y} '
            f'L{cx-bt} {base_y} Z')
    pw, n = rt - 12, 12          # pinked top edge of the paper filter
    pts = [f'{cx - pw + 2 * pw * i / n:.1f} {30 if i % 2 == 0 else 43}'
           for i in range(n + 1)]
    paper = f'M{cx-pw+5} {rim_y} L' + ' L'.join(pts) + f' L{cx+pw-5} {rim_y} Z'

    def wall(y: float) -> float:  # x of the right wall of the cone at height y
        return cx + rt - (rt - bt) * (y - rim_y) / (base_y - rim_y)
    y1, y2 = rim_y + 28, rim_y + 104
    handle = (f'M{wall(y1)-6:.1f} {y1} C{wall(y1)+58:.1f} {y1-6} '
              f'{wall(y1)+62:.1f} {y2-8} {wall(y2)-4:.1f} {y2}')
    # server (glass coffee pot) the dripper sits on
    mt, bb = 258, 484            # mouth / bottom
    m, b = 80, 124               # half widths of the mouth / the belly
    server = (f'M{cx-m} {mt} C{cx-b-4} {mt+46} {cx-b-12} {mt+116} '
              f'{cx-b} {bb-40} C{cx-b+4} {bb-10} {cx-b+24} {bb} {cx-b+56} {bb} '
              f'H{cx+b-56} C{cx+b-24} {bb} {cx+b-4} {bb-10} {cx+b} {bb-40} '
              f'C{cx+b+12} {mt+116} {cx+b+4} {mt+46} {cx+m} {mt} Z')
    lip = (f'M{cx-m-26} {mt+2} L{cx-m-4} {mt-8} H{cx+m+6} '
           f'a9 9 0 0 1 0 18 H{cx-m-4} Z')
    level = bb - 62              # coffee level
    s_handle = (f'M{cx+m+30} {mt+34} C{cx+b+58} {mt+30} {cx+b+62} {mt+150} '
                f'{cx+b+2} {mt+156}')
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512" role="img" aria-labelledby="title">
  <title id="title">brainfilter</title>
  {ATTR}
  {style(themed=themed)}
  <defs>
    <clipPath id="server-inside"><path d="{server}"/></clipPath>
  </defs>
  <g stroke-linejoin="round">
    <!-- server: handle, glass, coffee -->
    <path class="ink-s" stroke-width="22" stroke-linecap="round" d="{s_handle}"/>
    <path class="glass" d="{server}"/>
    <g clip-path="url(#server-inside)">
      <rect class="coffee" x="{cx-b-20}" y="{level}" width="{2*b+40}" height="{bb-level+10}"/>
      <rect class="crema" x="{cx-b-20}" y="{level}" width="{2*b+40}" height="9"/>
    </g>
    <path class="ink-s" stroke-width="14" d="{server}"/>
    <path d="M{cx-b+26} {mt+64} C{cx-b+16} {mt+96} {cx-b+16} {mt+130} {cx-b+26} {mt+156}"
          fill="none" stroke="#fff" stroke-width="9" stroke-linecap="round" opacity=".75"/>
    <!-- what drips through, inside the glass: coffee, files, folders -->
    {drop(cx, mt+26, 22, "crema")}
    {glyph("file", cx-20, mt+64, 24, "ink", -10)}
    {drop(cx+22, mt+92, 18, "crema")}
    {glyph("folder", cx-2, mt+128, 34, "ink", 7)}
    <path class="ink" d="{lip}"/>
    <!-- dripper: handle, paper filter, cone, rim, base -->
    <path class="ink-s" stroke-width="20" stroke-linecap="round" d="{handle}"/>
    <path class="paper" d="{cone}"/>
    <path class="paper" d="{paper}"/>
    <path class="ink-s" stroke-width="9" d="{paper}"/>
    <path class="ink-s" stroke-width="14" d="{cone}"/>
    <rect class="ink" x="{cx-rt-12}" y="{rim_y-10}" width="{2*rt+24}" height="20" rx="10"/>
    <rect class="ink" x="{cx-bt-34}" y="{base_y-4}" width="{2*bt+68}" height="18" rx="9"/>
    <!-- BIDS mark, printed on the filter -->
    {mark(cx, rim_y + 76, 96, "fixed-ink")}
  </g>
</svg>
'''


# ------------------------------------------------------------------ site icons
# Glyph-style icons (one colour, solid shapes, a few knock-outs, as in
# Font Awesome) that read at 16-32 px. Shapes are drawn white in a mask
# and knock-outs black, so that gaps show whatever is behind the icon.
def _glyph_svg(title: str, shapes: str, themed: bool) -> str:
    """Wrap mask shapes (white: ink, black: knock-out) into a glyph SVG."""
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512" role="img" aria-labelledby="title">
  <title id="title">{title}</title>
  {style(themed=themed)}
  <defs>
    <mask id="glyph" maskUnits="userSpaceOnUse" x="0" y="0" width="512" height="512">
      {shapes}
    </mask>
  </defs>
  <rect class="ink" width="512" height="512" mask="url(#glyph)"/>
</svg>
'''


def _theme_icon(name: str, shapes: str, crop: str) -> str:
    """
    Wrap mask shapes into a theme icon (overrides/.icons/).

    The theme inlines it in its pages and colours it with the text around
    it, so it has no style of its own (fill: currentColor), no fixed size,
    a mask id of its own, and a view cropped to the drawing.
    """
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="{crop}">
  <defs>
    <mask id="{name}-icon" maskUnits="userSpaceOnUse" x="0" y="0" width="512" height="512">
      {shapes}
    </mask>
  </defs>
  <rect width="512" height="512" fill="currentColor" mask="url(#{name}-icon)"/>
</svg>
'''


def brainfilter_icon(themed: bool = True, theme_icon: bool = False) -> str:
    """Draw the site icon: a dripper with its paper filter, handle and a drop."""
    cx, rim_y, base_y, rt, bt = 240, 140, 346, 194, 56
    cone = (f'M{cx-rt} {rim_y} L{cx+rt} {rim_y} L{cx+bt} {base_y} '
            f'L{cx-bt} {base_y} Z')
    pw, n = rt - 26, 8           # pinked edge of the paper, above the rim
    pts = [f'{cx - pw + 2 * pw * i / n:.1f} {40 if i % 2 == 0 else 66}'
           for i in range(n + 1)]
    paper = f'M{cx-pw+10} 92 L' + ' L'.join(pts) + f' L{cx+pw-10} 92 Z'

    def wall(y: float) -> float:
        return cx + rt - (rt - bt) * (y - rim_y) / (base_y - rim_y)
    y1, y2 = rim_y + 38, rim_y + 136
    handle = (f'M{wall(y1)-10:.1f} {y1} C{wall(y1)+96:.1f} {y1-10} '
              f'{wall(y1)+102:.1f} {y2-12} {wall(y2)-8:.1f} {y2}')
    W, K = 'fill="#fff"', 'fill="#000"'
    r, h = 26, 70                # the drop
    dy = 494 - h / 2
    drop = (f'M{cx} {dy-h/2} C{cx+r*.35} {dy-h/2+h*.28} {cx+r} {dy+h/2-1.55*r} '
            f'{cx+r} {dy+h/2-r} A{r} {r} 0 0 1 {cx-r} {dy+h/2-r} '
            f'C{cx-r} {dy+h/2-1.55*r} {cx-r*.35} {dy-h/2+h*.28} {cx} {dy-h/2}Z')
    shapes = f'''<path d="{paper}" {W} stroke="#fff" stroke-width="16" stroke-linejoin="round"/>
      <path d="{handle}" fill="none" stroke="#fff" stroke-width="44" stroke-linecap="round"/>
      <path d="{cone}" {K} stroke="#000" stroke-width="60" stroke-linejoin="round"/>
      <path d="{cone}" {W} stroke="#fff" stroke-width="20" stroke-linejoin="round"/>
      <rect x="{cx-rt-30}" y="{rim_y-26}" width="{2*rt+60}" height="44" rx="22" {W}/>
      <rect x="{cx-bt-58}" y="{base_y+18}" width="{2*bt+116}" height="36" rx="18" {W}/>
      <path d="{drop}" {W}/>'''
    if theme_icon:
        return _theme_icon('brainfilter', shapes, '8 24 496 478')
    return _glyph_svg('brainfilter', shapes, themed)


# ------------------------------------------------------------------- wordmark
def _wordmark_text(text: str) -> tuple[int, float, list[float], str]:
    """Return the outlines of `text` in Inter ExtraBold (see outline_text.py)."""
    for line in (HERE / "wordmark.txt").read_text().splitlines():
        name, upm, advance, bounds, d = line.split("\t")
        if name == text:
            return int(upm), float(advance), [float(v) for v in bounds.split()], d
    raise KeyError(text)


def brainfilter_wordmark(themed: bool = True) -> str:
    """Draw the logo, and "brainfilter" in the ink of the logo."""
    # the logo, cropped to its drawing (paper filter to server)
    lx, ly, lw, lh = 80, 22, 356, 484
    H = 240                                  # height of the logo
    logo_w = lw * H / lh
    logo = brainfilter(themed=False)
    logo = logo.replace('viewBox="0 0 512 512" width="512" height="512"',
                        f'viewBox="{lx} {ly} {lw} {lh}" x="0" y="0" '
                        f'width="{logo_w:.1f}" height="{H}"', 1)
    logo = logo.replace('id="server-inside"', 'id="wm-server-inside"')
    logo = logo.replace("url(#server-inside)", "url(#wm-server-inside)")
    logo = logo.replace(' role="img" aria-labelledby="title"', "")
    logo = re.sub(r'<title id="title">[^<]*</title>', "", logo)
    if themed:                               # the logo follows the palette
        logo = re.sub(r"<style>.*?</style>", "", logo, flags=re.S)
    # the name, as large as in the brainspresso wordmark
    upm, advance, (x0, y0, x1, y1), d = _wordmark_text("brainfilter")
    size = 116                               # font size
    k = size / upm
    gap = 26
    # the lowest point of the lettering (the overshoot of its round letters,
    # y1 below the baseline) on the bottom of the server (484, plus half its
    # 14 px outline): the name has no descenders, both stand on one line
    base = (484 + 7 - ly) * H / lh - y1 * k
    tx = logo_w + gap - x0 * k
    width = tx + x1 * k + 8
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.0f} {H}" width="{width:.0f}" height="{H}" role="img" aria-labelledby="title">
  <title id="title">brainfilter</title>
  {ATTR}
  <!-- Lettering: Inter ExtraBold (rsms.me/inter, SIL OFL 1.1), as outlines. -->
  {style(themed=themed)}
  {logo}
  <path class="ink" transform="translate({tx:.2f} {base:.2f}) scale({k:.5f})" d="{d}"/>
</svg>
'''


if __name__ == "__main__":
    for name, make in (("brainfilter-logo", brainfilter),
                       ("brainfilter-wordmark", brainfilter_wordmark),
                       ("brainfilter-icon", brainfilter_icon)):
        (Path(OUT) / f"{name}.svg").write_text(make())
    # the site icon as a theme icon, used as the logo of the docs header
    icons = HERE.parents[1] / "overrides" / ".icons" / "brainfilter"
    icons.mkdir(parents=True, exist_ok=True)
    (icons / "icon.svg").write_text(brainfilter_icon(theme_icon=True))

