# Making a stylized website that needs little adjustment

Lessons from building a two-theme site with generated media. Apply them before the first build story, not after the first review.

## Facts before copy
- Put the owner's product facts in the brief: which products are live (with their real addresses) and which are beta. Never write "coming soon" for something live, and update the tests that encoded an old assumption.

## One visual language
- Pick one style per kind of picture and state it in DESIGN.md. Hero, cards and vignettes are all photographic stills from one world, or all illustration; never a mix. Generate the hero still first, approve it, then give it to every other slot as the style reference and say "same world as the hero image" in each prompt.
- Cards are 16:9 across the top of the card, not squares. Clips are wide establishing shots; a close-up or macro clip reads as a crop of rust. An ambient loop is a low-opacity blended texture over a still, never the picture itself.

## Layout rules that broke before
- Never set an inline background-image without also setting size, position and repeat: it replaces the whole stack of layers a theme draws.
- A grid's row template must follow its content. Do not hard-code a row count; let rows come from the children and span the art across them.
- Theme sheets set display on the same classes a responsive rule hides, so the hide must outrank them (for example `:root[data-theme] .plaque`).
- Decorative pieces that sit beside the nav (plaques, taglines) hide below the width where the brand column stops fitting them, measured not guessed.
- A rail, shadow or pseudo-element wider than its column adds sideways scroll on a phone; contain it when the layout is one column.
- A label above a heading is a block, not an inline-block, or the heading slides up beside it.

## Check before asking for approval
- Widths 1440, 1280, 1100, 1024, 768, 600, 390 and 360, both themes, every page: no sideways scroll, no overlapping header pieces, nothing past the viewport edge, art filling its box. Do this in the preview and fix before the person looks.
