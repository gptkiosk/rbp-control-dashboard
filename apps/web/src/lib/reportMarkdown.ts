import MarkdownIt from 'markdown-it'

// Reports are untrusted text. Never embed their HTML or fetch image URLs.
const markdown = new MarkdownIt({ html: false, linkify: false, typographer: false, maxNesting: 20 })
markdown.validateLink = (url: string) => {
  try {
    const parsed = new URL(url)
    return ['https:', 'http:'].includes(parsed.protocol) && !parsed.username && !parsed.password
  } catch { return false }
}
markdown.renderer.rules.image = (tokens, index) => markdown.utils.escapeHtml(`[Image: ${tokens[index]?.content || 'omitted'}]`)
const renderLink = markdown.renderer.rules.link_open
markdown.renderer.rules.link_open = (tokens, index, options, env, renderer) => {
  tokens[index]!.attrSet('target', '_blank')
  tokens[index]!.attrSet('rel', 'noopener noreferrer')
  tokens[index]!.attrSet('referrerpolicy', 'no-referrer')
  return renderLink ? renderLink(tokens, index, options, env, renderer) : renderer.renderToken(tokens, index, options)
}
export function renderReport(text: string): string { return markdown.render(text) }
