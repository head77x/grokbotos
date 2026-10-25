# Grok Bot OS design notes (2026-10-25)

Source studied: the official site https://x.ai/bot (its HTML and the CSS it ships). We follow the **concept** only.
We do not copy their logo or mark path, artwork, or fonts (CursorGothic, xVf, GeistMono, CursorIcons16).

## What the site does
- **Monochrome, dark-first chrome.** Named tokens (`--grok-bot-*`):
  - backgrounds: chrome #141414, editor #1c1c1c, elevated #262626
  - cards and hover: translucent white, #ffffff0f
  - borders: #ffffff1f
  - text: #f2f2f2 (primary), 58% white (secondary), 36% white (tertiary)
  - status colours: accent #64b5ff, success #4cc79b, warning #e8a33d, danger #ff6b5e
  - light theme: text #0a0a0a, accent #0a84ff
  - page colours: "jet" hsl(0 0% 4%) and white
- **Colour comes from the characters, not the chrome.** Each bot avatar wears a "coat" from a vivid palette: orange #F19D38, pink #EB4699, purple #885CF5, teal #54B9A6, red #EA4045, green #5BC67A, blue #3C82F6, and #ED712E. Fill colours animate (`transition: fill .6s`).
- **The character** is an SVG with a solid head shape and two eye cut-outs drawn in the background colour. It is simple and flat, with no outline. Expression comes from moving or reshaping the eyes in code. The footer uses an outline variant: 1.75px non-scaling stroke, no fill.
- **Motion:**
  - springy entry: `cubic-bezier(.2,.9,.3,1.15)`, 280ms, translateY(8px) scale(.97) → 1
  - other curves: `(.22,1,.36,1)` and `(.16,1,.3,1)`
  - typing dots: 1.3s opacity pulse
  - shimmer, border-beam and waveform effects
  - prefers-reduced-motion is respected everywhere
- **Type:** a geometric grotesk sans for UI and a mono for code. Large tight headlines, small quiet secondary text.
- **Shape and space:** radius .5rem for controls and 16px for cards. Generous whitespace, thin hairline borders and very soft elevation.

## Our take (original work)
- **"Bit", our own character.** A rounded square (squircle) head, two pill eyes and an optional small mouth line, all drawn in code: SVG for the web, cairo in the Dock and the consent prompt. Its silhouette is deliberately different from the site's mark.
- **Expressions:**
  - idle: random blink every 2–6s and occasional look-around
  - thinking: eyes look up, slow pulse
  - listening: eyes wide, mouth "o"
  - happy: arc eyes
  - error: x eyes, red coat
  - sleeping: closed lines, slow breathe
  - alert: wide eyes, amber, used for consent
- **State mapping:**
  - Grok Bot app running and busy (CPU) → thinking
  - microphone in use → listening
  - consent prompt → alert
  - low battery (≤15%, not charging) → sleepy, amber
  - offline → error-ish "sad"
  - otherwise idle
  - Files and Settings: empty state → idle, permission needed → alert, granted → happy
- **Tokens:** /usr/share/grokbot/design/tokens.css, served to every web app at `/_grokbot/` on its own origin, so it passes the CSP. Base components are in base.css; the character is in mascot.js.
- **Fonts:** Noto Sans CJK KR (already in the image) for UI, so Korean renders well; Noto Sans Mono for code. No proprietary fonts.
- **Contrast:** primary text ~18:1, secondary ≥7:1, tertiary is used only for hints (≥4.5:1 at 45%).
