# Template store icons

Each template in **Settings → Template store** shows a square icon at the top left of its card. Until an icon file exists the
card shows a monogram placeholder (two letters on a dashed tile, for example **UC** for upubhub class). Hovering the placeholder
names the file it is waiting for.

## Where the files go

Put one file per template in `apps/web/src/assets/template-icons/`, named after the template id. PNG, WebP, SVG or JPG all
work; the build picks the file up by name, so there is nothing else to edit. Copy the same files into the other dashboard
(MCD and RCD each carry their own copy).

| Template | Category on the card | File | Placeholder now |
| --- | --- | --- | --- |
| GCP hosted app | Cloud app | `gcp-hosted-app.png` | GA |
| GCP hosted website | Cloud website | `gcp-hosted-website.png` | GW |
| Local website | Website | `local-website.png` | LW |
| Other | General | `other.png` | O |
| Packaged app | Desktop app | `packaged-app.png` | PA |
| upubhub class | Teaching | `upubhub-class.png` | UC |

A community template with no file keeps its monogram, so a missing icon is never an error. Category words live in
`apps/web/src/lib/templateStore.ts`; an id not listed there shows **Template**.

## Size and format

- 512 × 512 pixels, square, full bleed (no transparent margin and no rounded corners: the card rounds them).
- Shown at 48 × 48 CSS pixels on dark and light themes, so it must read at that size: one subject, bold shapes, few details,
  no text or letters.
- Keep each file under 60 KB (WebP or an optimised PNG).

## Shared style (paste before every subject)

> App store icon, square 1:1, full-bleed background, a single centred subject in bold simplified shapes with soft depth and a
> gentle top-left light, rich but limited palette of 3 to 4 colours, smooth gradient background, clean vector-like finish,
> no text, no letters, no logos, no border, no rounded corners, no drop shadow outside the square, readable at 48 pixels.

## Subjects

**gcp-hosted-app.png** (Cloud app)
> Subject: a small stack of three rounded container blocks floating on a soft cloud, one block glowing with a play-triangle
> light, a thin rising arrow behind them suggesting deployment. Background gradient deep blue to teal. Accent colour warm
> yellow on the glowing block.

**gcp-hosted-website.png** (Cloud website)
> Subject: a browser window with a simple illustrated landscape on its page, resting on a soft cloud, a few small sparkles
> around the picture. Background gradient indigo to sky blue. Accent colour coral on the illustration's sun.

**local-website.png** (Website)
> Subject: a browser window with a simple illustrated page standing on a small desk-like base, a tiny house-shaped home marker
> on its corner to suggest "on this machine". Background gradient forest green to mint. Accent colour soft orange.

**other.png** (General)
> Subject: a puzzle piece fitting partly into a dashed outline, a small compass needle on the piece to suggest finding the
> closest fit. Background gradient slate grey to lavender. Accent colour bright violet on the piece.

**packaged-app.png** (Desktop app)
> Subject: a closed cardboard-style package box with a small ribbon seal and a downward arrow landing into an open laptop
> lid behind it, suggesting install from a release. Background gradient charcoal to warm amber. Accent colour bright amber
> on the seal.

**upubhub-class.png** (Teaching)
> Subject: an open textbook with a small graduation cap resting on its pages and a speech bubble rising from the book,
> suggesting lessons and discussion. Background gradient deep purple to rose. Accent colour gold on the cap tassel.

## After adding the files

Run `npm run build` in `apps/web` (or the dev server) and open Settings → Template store: each card should show its image and
no dashed placeholder. The web test `PipelinePacksPanel.spec.ts` checks the placeholder for an id without a file, so it keeps
passing when real icons are added.
