# Media models (fal.ai)

Agents, then **Billing & rates**, then **Media models** lists the image and video models used to make site art and motion media, with what each costs and which quality tier it serves. It is a catalog: it records facts and your own prices and does not start any generation or limit any spending.

## What is listed

Each model shows its fal endpoint id, its billing unit (per image or per second of video), a quality tier (draft is the cheapest, standard the default, premium the best) and a note. Listed prices are fal's published prices from the date shown and are approximate: resolution, duration and audio change the final cost. A blank price means fal's pricing page did not list that model (Veo 3.1 at the time of writing). Look up the live figure with the media tool's `price` command, or enter your own; a price you enter replaces the listed one for display.

## The fal key

Save the key in **Profile, Private credentials, fal.ai key**. It is encrypted, write-only and never shown again, and agents never receive it. Create it at fal with the **API** preset (model execution and storage) and restrict its allowed models to the patterns the panel shows, so a mistake or a leaked key cannot call other models. Set a credit limit at fal as well: MCD does not cap media spending.

## Generating media from MCD

Open it from the **Media** button on the Agents page (or Billing & rates, then Media models). **Generate all missing** makes one candidate for every slot that has nothing published, no candidate and no approved still it waits for, at one tier, after a single confirmation that shows the estimated total. Stills come first: pick and ingest the approved stills, then run it again for the clips and transitions.

Under **Media models**, **Generate media with your saved fal key** lists the slots in a project folder's `media/slots.json`. For each slot choose a tier (draft is the cheapest model, standard the default, premium the best) and how many to make, tick the spending acknowledgement, and press Generate. MCD calls fal itself with your saved key, shows progress, and saves each result as a candidate in the folder's `media/candidates/`. **Use this one** copies a candidate into `media/inbox/`; then run the project's own `python3 tools/media/media.py ingest <slot>` to validate, convert and record it.

How the key is protected:

- MCD never runs code from the project folder with the key. Agents can edit that folder, so the folder only supplies data (prompts, file names, reference images). The fal calls are made by MCD's own code.
- The key goes only to fal hosts, never in a response, ledger entry, log line or file, and is not sent with the file download.
- The API is operator-only; agents and the project bridge are refused.
- Reference images and approved stills must be real image files inside the folder (links and `..` that leave the folder are refused). Only models in the catalog can be named.

Every run is explicit and recorded in `media/ledger.jsonl` under MCD's data directory (slot, model, estimate, fal request id, result). Estimates use listed or your own prices and are not invoices; fal's billing page is the truth. Video needs the approved still published first (`assets/img/<name>.jpg`). MCD does not limit spending; set a credit limit at fal. A restart of MCD loses jobs still in flight, and the ledger keeps the fal request id so you can find them in your fal dashboard.

## Changing the catalog

The model list is in `apps/api/media_catalog.py`. Add a model there with its endpoint id, unit, listed price (or none) and tier; the panel and `GET /api/media/models` pick it up.
