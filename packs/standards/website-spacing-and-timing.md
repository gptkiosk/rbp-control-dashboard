# Spacing, sizing and timing settings for a stylized website

Starting values from a two-theme site. Put them in DESIGN.md as tokens on day one.

## Timing
- Theme crossing: 1500 ms (allowed 700 to 1800). 1000 ms read as rushed. Keyframe offsets are fractions of one duration constant, so a single number retimes the whole sequence.
- Reduced motion: crossfade of 150 ms or less, no parallax or loops; hide video when data saving is on.
- Hover and focus: 180 to 250 ms for colour, underline and lift. Swinging or settling pieces: about 900 ms, damped.
- Overlay safety timer: crossing time plus 800 ms.
- Ambient loop: opacity 0.3 (dark, screen blend) to 0.45 (light, soft-light) over a still.

## Header
- Minimum height 96 px. At least 16 px between wordmark, menu and controls. Only wordmark, menu and one control.
- Menu 1.15 rem with 0.4 by 0.65 rem link padding from 1280 px wide; smaller below.
- Side plaque: 14 px text, one line, shown from 1440 px only.
- 760 to 1099 px: wordmark and control on row one, menu centred on row two. Below 760: menu in a two-by-two grid, no hamburger.

## Layout
- Smallest text 14 px. Section gap 56 px between card rows; card padding 1.5 rem.
- Cards: two per row from 1100 px, picture 16:9 across the top; one per row below, picture beside the words from 900 to 1099 px; single column under 600 px.
- A frame drawn behind content takes its inset from one variable, and the content padding is that variable plus 1.5 rem, so all four gaps match at every width.
- Contain any rail or shadow that is wider than its column when the layout is one column.

## Menus and resizing
- Below 760 px the menu collapses behind a 44 px round button beside the other control, with `aria-expanded`, `aria-controls`, Escape and outside-click to close, and opens as one full-width column of 48 px rows. Without script the button stays hidden and the links stay visible.
- Write media queries in em (px divided by 16) so layouts follow the reader's text-size setting. Text in rem and clamp(); never disable zoom; the wordmark yields to the buttons however large the text is.

## Always measure
- Run the audit at 1920, 1440, 1280, 1100, 1024, 768, 600, 390 and 360 px in both themes: sideways scroll, overlapping header boxes, anything past the edge.
