/** Keep the human name prominent and place exact identifiers on the secondary line. */
export function agentName(name: string | null | undefined, id: string): string {
  if (!name || name === id) return id
  return name.startsWith(`${id} - `) ? name.slice(id.length + 3) : name
}

export function directoryName(path: string): string {
  return path.split('/').filter(Boolean).at(-1) || '/'
}

export function directoryDetail(path: string, branch?: string | null): string {
  return branch ? `${branch} · ${path}` : path
}
