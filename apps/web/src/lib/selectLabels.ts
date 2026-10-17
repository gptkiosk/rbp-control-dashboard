/** Keep the human name prominent and place exact identifiers on the secondary line. */
export function agentName(name: string | null | undefined, id: string): string {
  if (!name || name === id) return id
  return name.startsWith(`${id} - `) ? name.slice(id.length + 3) : name
}

export function directoryName(path: string): string {
  return path.split('/').filter(Boolean).at(-1) || '/'
}

/** The scratch area is not a place to work in; picking it creates a new private folder for the project. */
export function directoryLabel(path: string, scratchRoot?: string | null): string {
  return scratchRoot && path === scratchRoot ? 'Scratch folder (new, private to this project)' : directoryName(path)
}

export function directoryDetailFor(path: string, branch: string | null | undefined, scratchRoot?: string | null): string {
  return scratchRoot && path === scratchRoot ? 'Recommended. No repository, branch or grant to set up.' : directoryDetail(path, branch)
}

export function directoryDetail(path: string, branch?: string | null): string {
  return branch ? `${branch} · ${path}` : path
}
