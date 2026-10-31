// What the template store shows for each template beyond what the pack itself says: a category for the card and an icon.
//
// Icons are files in src/assets/template-icons/ named after the template id (upubhub-class.png, gcp-hosted-app.webp, ...).
// They are found at build time, so adding an icon is dropping a file in that folder: no list to update here. A template
// with no icon file, including any community template, shows a monogram tile instead. Prompts for the built-in icons are
// in docs/configuration/template-store-icons.md.
const files = import.meta.glob('@/assets/template-icons/*.{png,webp,svg,jpg}', { eager: true, query: '?url', import: 'default' }) as Record<string, string>
const ICONS: Record<string, string> = Object.fromEntries(Object.entries(files).map(([path, url]) => [path.split('/').pop()!.replace(/\.[a-z]+$/, ''), url]))

// Short category words for the top corner of a card. Unknown ids say TEMPLATE.
const CATEGORIES: Record<string, string> = {
  'gcp-hosted-app': 'Cloud app',
  'gcp-hosted-website': 'Cloud website',
  'local-website': 'Website',
  'packaged-app': 'Desktop app',
  'upubhub-class': 'Teaching',
  other: 'General',
}

export function iconFor(id: string): string | null { return ICONS[id] ?? null }
export function categoryFor(id: string): string { return CATEGORIES[id] ?? 'Template' }

// "GCP hosted app (containerized application on Google Cloud)" → title "GCP hosted app", tagline "Containerized application on Google Cloud".
export function splitLabel(label: string): { title: string; tagline: string } {
  const m = /^(.*?)\s*\((.+)\)\s*$/.exec(label)
  if (!m) return { title: label, tagline: '' }
  const tagline = m[2]!
  return { title: m[1]!, tagline: tagline.charAt(0).toUpperCase() + tagline.slice(1) }
}

// Up to two letters for the placeholder tile, first and last word, so siblings differ: "GCP hosted app" → "GA",
// "GCP hosted website" → "GW", "upubhub class" → "UC", "Other" → "O".
export function monogram(title: string): string {
  const words = title.split(/[\s-]+/).filter(Boolean)
  return (words.length > 1 ? [words[0]!, words.at(-1)!] : words).map(w => w[0]!.toUpperCase()).join('')
}

// A stable chart series (1-6, the --series-N tokens) per template id, so each placeholder tile keeps its colour in
// both themes.
export function seriesFor(id: string): number {
  let h = 0
  for (const c of id) h = (h * 31 + c.charCodeAt(0)) % 6
  return h + 1
}
