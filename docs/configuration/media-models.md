# Media models (fal.ai)

Agents, then **Billing & rates**, then **Media models** lists the image and video models used to make site art and motion media, with what each costs and which quality tier it serves. It is a catalog: it records facts and your own prices and does not start any generation or limit any spending.

## What is listed

Each model shows its fal endpoint id, its billing unit (per image or per second of video), a quality tier (draft is the cheapest, standard the default, premium the best) and a note. Listed prices are fal's published prices from the date shown and are approximate: resolution, duration and audio change the final cost. Prices were checked against fal's own usage table (Veo 3.1 Fast billed $0.15 a second, Veo 3.1 $0.40 a second, and a 2K Nano Banana 2 picture 1.5 image units at $0.08), so an estimate is an upper bound. MiniMax H3 Max ($0.08 a second at 768p) and H3 Max Turbo ($0.04) are the draft and standard clip models and cost a fraction of Veo; their prices are the list prices after the launch discount ends on 31 October 2026. A run with no price is shown as unpriced and never counted as zero. You can enter your own price; it replaces the listed one for display.

## The fal key

Save the key in **Profile, Private credentials, fal.ai key**. It is encrypted, write-only and never shown again, and agents never receive it. Create it at fal with the **API** preset (model execution and storage) and restrict its allowed models to the patterns the panel shows, so a mistake or a leaked key cannot call other models. Set a credit limit at fal as well: MCD does not cap media spending.

## Generating media from MCD

Open it from the **Media** button on the Agents page (or Billing & rates, then Media models). **Generate all missing** makes one candidate for every slot that has nothing published, no candidate and no approved still it waits for, at one tier, after a single confirmation that shows the estimated total. Stills come first: pick and ingest the approved stills, then run it again for the clips and transitions.

Under **Media models**, **Generate media with your saved fal key** lists the slots in a project folder's `media/slots.json`. For each slot choose a tier (draft is the cheapest model, standard the default, premium the best). The panel starts each slot on its project type's default: a website's background clips start on the cheapest video tier, other projects on standard. A slot with generations still waiting for your review is not generated again until you review them or choose **Another take**, so a double click never pays twice, and the panel asks you to confirm each request with its estimated cost and how many to make, tick the spending acknowledgement, and press Generate. MCD calls fal itself with your saved key, shows progress, and saves each result as a candidate in the folder's `media/candidates/`. The panel shows each candidate as a thumbnail (open it full size) or a small video player, so you can choose by looking. **Use this one** copies the chosen file into `media/inbox/`, and **Publish** then validates and converts it (a resized JPEG for a still; silent WebM and MP4 with a seamless loop blend and a poster for a clip) and records its provenance in `media/provenance.json` and `assets/ART-INVENTORY.md`, using MCD's own code. A draft is too small to publish; generate it at standard or premium. `ffmpeg` must be installed on this machine. **Use this one** copies a candidate into `media/inbox/`; then run the project's own `python3 tools/media/media.py ingest <slot>` to validate, convert and record it.

How the key is protected:

- MCD never runs code from the project folder with the key. Agents can edit that folder, so the folder only supplies data (prompts, file names, reference images). The fal calls are made by MCD's own code.
- The key goes only to fal hosts, never in a response, ledger entry, log line or file, and is not sent with the file download.
- The API is operator-only; agents and the project bridge are refused.
- Reference images and approved stills must be real image files inside the folder (links and `..` that leave the folder are refused). Only models in the catalog can be named.

Every run is explicit and recorded in `media/ledger.jsonl` under MCD's data directory (slot, model, estimate, fal request id, result). Estimates use listed or your own prices, are an upper bound and are not invoices; fal's usage page is the truth. The spend line under the panel also shows how many runs were repeats of a slot already generated. Video needs the approved still published first (`assets/img/<name>.jpg`). MCD does not limit spending; set a credit limit at fal. A restart of MCD loses jobs still in flight, and the ledger keeps the fal request id so you can find them in your fal dashboard.

## Changing the catalog

The model list is in `apps/api/media_catalog.py`. Add a model there with its endpoint id, unit, listed price (or none) and tier; the panel and `GET /api/media/models` pick it up.

## Media review as part of a project

A project whose working folder has `media/slots.json` gets a **Media** tab and, while slots are undecided, a banner on the project page. A human story about media links straight to it (**Open media review**), and its decision box offers the summary as your decision. Each slot ends **published** or **skipped** (the site uses its fallback); nothing else is left open.

Decisions are kept with the project: `media/decisions.json` in the folder records, per slot, what was generated, accepted, rejected, published or skipped and by whom, and the project's ledger gets a matching entry. A published slot is not regenerated unless you choose Regenerate, and a slot with a generation running refuses a second. Every submission to fal is journaled in MCD's data directory, so a generation in flight when MCD restarts is finished at the next start rather than lost (or marked failed in the ledger if it cannot be resumed; it is never resubmitted).
