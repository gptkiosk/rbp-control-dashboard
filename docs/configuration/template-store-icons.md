# Template store icons

Each template in **Settings → Template store** shows a square icon at the top left of its card. The eight official templates
have icons (512 × 512 WebP, added 2026-10-31). A template without an icon file, such as a new community
template, shows a monogram placeholder (two letters on a dashed tile). Hovering the placeholder names the file it is waiting
for.

## Where the files go

Cards show the full summary, not a three-line clipped description. Installed
cards prefer their installed manifest summary (also used for search offline),
then the catalog and finally the label tagline. Keeping an older template does
not silently display a newer version's capabilities as installed. Summary edits
ship in the signed pack release; icon assets ship with dashboard 0.6.91.

Put one file per template in `apps/web/src/assets/template-icons/`, named after the template id. PNG, WebP, SVG or JPG all
work; the build picks the file up by name, so there is nothing else to edit. Keep one file per id: two files for the same id
(say `other.png` and `other.webp`) leave it unclear which one shows. Copy the same files into the other dashboard
(MCD and RCD each carry their own copy).

| Template | Category on the card | File | Monogram without a file |
| --- | --- | --- | --- |
| GCP hosted app | Cloud app | `gcp-hosted-app.webp` | GA |
| GCP hosted website | Cloud website | `gcp-hosted-website.webp` | GW |
| Local website | Website | `local-website.webp` | LW |
| Other | General | `other.webp` | O |
| Packaged app | Desktop app | `packaged-app.webp` | PA |
| upubhub class | Teaching | `upubhub-class.webp` | UC |
| upubhub textbook | Teaching | `upubhub-textbook.webp` | UT |
| upubhub lesson plan | Teaching | `upubhub-lesson-plan.webp` | UP |

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

The textbook and lesson-plan images were generated with the built-in image tool
on 2026-11-02 using the class icon as a style reference, then resized to 512 × 512
WebP. Both dashboards carry byte-identical copies. They depict an open textbook
with a chart/chat bubble, and a lesson clipboard with a clock, respectively.
They contain no lettering; the card label supplies the accessible name.

Generation prompts used the shared style above. Textbook subject: an open
teal-bound textbook with ivory pages, a blue chart, an ivory speech bubble and
a gold bookmark, on deep-blue-to-cyan background. Lesson-plan subject: an ivory
clipboard with teal checks and a gold clock, on indigo-to-violet background.
Neither icon uses a graduation cap, keeping it distinct from the class icon.

Run `npm run build` in `apps/web` (or the dev server) and open Settings → Template store: each card should show its image and
no dashed placeholder. The web test `PipelinePacksPanel.spec.ts` checks the placeholder for an id without a file, so it keeps
passing when real icons are added.
