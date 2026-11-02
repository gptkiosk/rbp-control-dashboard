// Development-only synthetic store. No real API, installation or providers.
import { createApp, h } from 'vue'
import { createRouter, createMemoryHistory } from 'vue-router'
import PipelinePacksPanel from '../../src/components/PipelinePacksPanel.vue'
import '../../src/styles/main.css'
const available = [
  {
    "id": "gcp-hosted-app",
    "label": "GCP hosted app (containerized application on Google Cloud)",
    "summary": "Build a working web application or API with its own workflows, data and tests, then prepare a container for an explicitly chosen Google Cloud target. Choose this for interactive software, not a content-only website. Cloud deployment follows your review and approval.",
    "version": "1.0.1",
    "service": null,
    "installed": null,
    "update": false,
    "author": "gptkiosk",
    "trust": "official",
    "settings": [],
    "needs": [],
    "too_new": false,
    "changes": "Clearer store description: what this template produces, when to choose it and which delivery decisions remain yours."
  },
  {
    "id": "gcp-hosted-website",
    "label": "GCP hosted website (illustrated site deployed to Google Cloud)",
    "summary": "Create an illustrated, multi-page website and prepare it for your chosen Google Cloud hosting target. Includes page design, reviewed media and browser checks. Choose this when the site must be publicly hosted; domain, spending and deployment decisions remain yours.",
    "version": "1.0.1",
    "service": null,
    "installed": null,
    "update": false,
    "author": "gptkiosk",
    "trust": "official",
    "settings": [],
    "needs": [],
    "too_new": false,
    "changes": "Clearer store description: what this template produces, when to choose it and which delivery decisions remain yours."
  },
  {
    "id": "local-website",
    "label": "Local website (illustrated site reviewed on this host)",
    "summary": "Create an illustrated static website and review it in an isolated preview on this computer. Includes themed pages, reviewed media and browser checks. Choose this for a local demonstration or prototype; public hosting and deployment are outside this template.",
    "version": "1.0.1",
    "service": null,
    "installed": null,
    "update": false,
    "author": "gptkiosk",
    "trust": "official",
    "settings": [],
    "needs": [],
    "too_new": false,
    "changes": "Clearer store description: what this template produces, when to choose it and which delivery decisions remain yours."
  },
  {
    "id": "other",
    "label": "Other (does not exactly fit)",
    "summary": "Plan a deliverable that does not fit the listed templates. The project brief identifies the closest workflow, the differences, required checks and human decisions before work starts. Choose this for an unusual project; the normal safety and approval gates still apply.",
    "version": "1.0.1",
    "service": null,
    "installed": null,
    "update": false,
    "author": "gptkiosk",
    "trust": "official",
    "settings": [],
    "needs": [],
    "too_new": false,
    "changes": "Clearer store description: what this template produces, when to choose it and which delivery decisions remain yours."
  },
  {
    "id": "packaged-app",
    "label": "Packaged app (local install from a public GitHub release)",
    "summary": "Build an application people install on their own computers, with tests, documentation and a signed release package. Choose this for desktop or local tools rather than a hosted site. Public release and installation remain separate, explicitly reviewed steps.",
    "version": "1.0.1",
    "service": null,
    "installed": null,
    "update": false,
    "author": "gptkiosk",
    "trust": "official",
    "settings": [],
    "needs": [],
    "too_new": false,
    "changes": "Clearer store description: what this template produces, when to choose it and which delivery decisions remain yours."
  },
  {
    "id": "upubhub-class",
    "label": "upubhub class (textbook, lesson plans, assessments)",
    "summary": "Create a complete teaching package: a source-credited textbook, linked lesson plans, chat-out discussions and text-grounded assessments for teacher review. Use new writing or your own files. After your sign-off, push private drafts and an invite-only class to upubhub; publishing stays your choice.",
    "version": "0.4.0",
    "service": null,
    "installed": null,
    "update": false,
    "author": "gptkiosk",
    "trust": "official",
    "settings": [],
    "needs": [],
    "too_new": false,
    "changes": "Shared teaching guidance: source-linked textbook/lesson-plan/class workflows, editable chat-out background, bounded assessment and teacher review. Visual requests stay reviewed specifications until the app and connector support them. The class pack adds GEOL for geology."
  },
  {
    "id": "upubhub-lesson-plan",
    "label": "upubhub lesson plan (one lesson)",
    "summary": "Create one practical teaching plan with measurable objectives, textbook references, timed activities, discussion prompts and checks for understanding. Write it new or preserve your own plan. Review it, then push a private draft to upubhub after sign-off; class assignment is a separate choice.",
    "version": "0.2.0",
    "service": null,
    "installed": null,
    "update": false,
    "author": "gptkiosk",
    "trust": "official",
    "settings": [],
    "needs": [],
    "too_new": false,
    "changes": "Shared teaching guidance: source-linked textbook/lesson-plan/class workflows, editable chat-out background, bounded assessment and teacher review. Visual requests stay reviewed specifications until the app and connector support them. The class pack adds GEOL for geology."
  },
  {
    "id": "upubhub-textbook",
    "label": "upubhub textbook (chapters with discussion topics)",
    "summary": "Create one source-credited textbook, with structured chapters, learning objectives and editable chat-out topics anchored in the text. Write new material or convert your own manuscript without rewriting it. Review the evidence, then push a private draft to upubhub after sign-off.",
    "version": "0.2.0",
    "service": null,
    "installed": null,
    "update": false,
    "author": "gptkiosk",
    "trust": "official",
    "settings": [],
    "needs": [],
    "too_new": false,
    "changes": "Shared teaching guidance: source-linked textbook/lesson-plan/class workflows, editable chat-out background, bounded assessment and teacher review. Visual requests stay reviewed specifications until the app and connector support them. The class pack adds GEOL for geology."
  }
]
const installed = available.filter(p => !['gcp-hosted-app', 'upubhub-textbook', 'upubhub-lesson-plan'].includes(p.id)).map(p => ({ id: p.id, label: p.label, version: p.version, versions: [p.version, p.version.startsWith('1.') ? '1.0.0' : '0.1.0'], project_types: [p.id], service: null, summary: p.summary }))
const offers = available.map(p => ({ ...p, installed: installed.some(i => i.id === p.id) ? p.version : null }))
window.fetch = async (input, init) => {
  if (String(input).split('?')[0] !== '/api/pipeline-packs' || (init?.method && init.method !== 'GET')) return new Response(JSON.stringify({ detail: 'Fixture only: installation and mutations are disabled.' }), { status: 403 })
  return new Response(JSON.stringify({ repository: 'gptkiosk/dashboard-pipeline-packs', release: 'synthetic-unreleased-preview', error: null, available: offers, installed, tools: {} }), { status: 200 })
}
createApp({ render: () => h('main', { style: 'max-width:1440px;margin:auto;padding:24px' }, [
  h('p', { class: 'muted small' }, 'Isolated UI fixture. All descriptions and icons are local; no installation, production data or provider calls.'),
  h('button', { type: 'button', class: 'btn', onClick: () => { document.documentElement.dataset.theme = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light' } }, 'Toggle light/dark preview'),
  h(PipelinePacksPanel),
]) }).use(createRouter({ history: createMemoryHistory(), routes: [] })).mount('#app')
