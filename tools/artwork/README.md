# Artwork

Sources of the brainfilter artwork. The generated files are in
`docs/images/` and `overrides/.icons/`.

| File | What |
|------|------|
| `docs/images/brainfilter-logo.svg` | The logo: a pour-over with the BIDS mark on its filter |
| `docs/images/brainfilter-wordmark.svg` | The logo and the name (the heading of the README) |
| `docs/images/brainfilter-wordmark-light.svg`, `-dark.svg` | The wordmark in one palette each: the title of the docs home page, which shows the one of its palette (`#only-light` / `#only-dark`) |
| `docs/images/brainfilter-icon.svg` | The site icon, the favicon of the docs site (one colour, legible at 16-32 px) |
| `docs/images/brainfilter-favicon-32.png`, `brainfilter-icon-180.png` | PNG fallbacks of the site icon (favicon, Apple touch icon) |
| `overrides/.icons/brainfilter/icon.svg` | The site icon as a theme icon, the logo of the docs header (`brainfilter/icon`) |

The SVGs in `docs/images/` follow `prefers-color-scheme` (light-on-dark in
dark mode), except the `-light` and `-dark` wordmarks: the palette toggle of
the docs site does not follow `prefers-color-scheme`. The theme icon takes
the colour of the text around it.

## Regenerating

* `python tools/artwork/make_logos.py`: the logo, wordmark, site icon and
  theme icon;
* `node tools/artwork/render_pngs.js`: the PNGs (needs Node and Playwright);
* `python tools/artwork/outline_text.py`: the outlines of the lettering
  (`wordmark.txt`; needs fontTools and Inter), only to change the name or
  the font.

## Credits

* The BIDS mark (half brain and file tree), file and folder glyphs are
  adapted from the [BIDS logo](https://github.com/bids-standard/bids-specification/tree/master/BIDS_logo)
  ([CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)).
* The lettering is [Inter](https://rsms.me/inter/) ExtraBold
  ([SIL OFL 1.1](https://openfontlicense.org)), as outlines.
