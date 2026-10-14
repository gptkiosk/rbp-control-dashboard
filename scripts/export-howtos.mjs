// Run with Node 22+: node --experimental-strip-types scripts/export-howtos.mjs
// The same reviewed content powers Help, chat answers, and this printable guide.
import { writeFile } from 'node:fs/promises'
import { helpGuides } from '../apps/web/src/lib/help.ts'

const origin = 'http://127.0.0.1:8800'
const intro = `# Using Mac Control Dashboard\n\nOpen [MCD](${origin}/) and sign in with an allowed Google account.\nUse **Help** in the header to ask a feature question, or **Help & how-tos** in the sidebar to browse these guides.\nHelp answers from built-in instructions locally, without sending questions to a model or changing settings.\nIts Open links navigate to a section or open an unsubmitted form. You decide whether to save, approve, or run anything.\nHelp conversation stays in memory and clears on sign-out or reload. Never paste credentials into help.\n\nOn Tailscale, use your dashboard origin on port 9443 instead of localhost; in-app links retain the current origin.\n\n`
const sections = helpGuides.map(g => `## ${g.title}\n\n${g.summary}\n\n${g.steps.map((s, i) => `${i + 1}. ${s}`).join('\n')}\n\n${g.note ? `${g.note}\n\n` : ''}${g.links.map(l => `[${l.label}](${origin}${l.to})`).join(' · ')} · [Bookmark this how-to](${origin}/help?topic=${g.id})\n`).join('\n')
await writeFile(new URL('../docs/HOW_TO.md', import.meta.url), intro + sections)
console.log(`Exported ${helpGuides.length} MCD how-tos.`)
