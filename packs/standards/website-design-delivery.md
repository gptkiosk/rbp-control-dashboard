# Making a stylized website that needs little adjustment

Lessons from a two-theme site with generated media. Apply before the first build story.

## Facts before copy
- Put the owner's product facts in the brief: which products are live (real addresses) and which are beta. Never write "coming soon" for a live product; fix tests that encode it.

## One visual language
- Pick one style per kind of picture and state it in DESIGN.md. Hero, cards and every vignette (about, contact too) are photographic stills from one world, or all illustration; never a mix. Drawn SVGs are fallbacks only. Generate the hero still first, approve it, then give it to every other slot as the style reference and say "same world as the hero image" in each prompt.
- Cards are 16:9 across the top, not squares. Clips are wide establishing shots; a close-up or macro clip reads as a crop of rust. An ambient loop is a low-opacity blended texture over a still, never the picture itself.

## Layout rules that broke before
- Never set an inline background-image without also setting size, position and repeat: it replaces the whole stack of layers a theme draws.
- A grid's row template must follow its content. Do not hard-code a row count; let rows come from the children and span the art across them.
- Theme sheets set display on the same classes a responsive rule hides, so the hide must outrank them (for example `:root[data-theme] .plaque`).
- Keep the header to wordmark, menu and one control. Plaques and taglines that repeat the hero are dropped, or hidden below the measured width where they stop fitting. Between phone and wide desktop the menu takes its own row.
- Theme crossings run about 1.5 seconds; 1 second reads as rushed.
- A rail, shadow or pseudo-element wider than its column adds sideways scroll on a phone; contain it when the layout is one column.
- Labels above headings are blocks, not inline-blocks. Card buttons sit on the card's bottom edge (flex column, margin-top:auto) so rows line up.

## Check before asking for approval
- Widths 1440, 1280, 1100, 1024, 768, 600, 390 and 360, both themes, every page: no sideways scroll, no overlapping header pieces, nothing past the viewport edge, art filling its box. Fix before the person looks.
