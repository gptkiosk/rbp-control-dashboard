/** Shape of GET /api/projects/{id}/standards (see apps/api/standards.py). */
export interface StandardsArea { area: string; risk: 'low' | 'medium' | 'high'; route: string }
export interface StandardsCheck { touches: string; run: string }
export interface Standards {
  state: 'ok' | 'missing' | 'unreadable' | 'no_workdir'
  path: string
  property: string | null
  sha256: string | null
  areas: StandardsArea[]
  checks: StandardsCheck[]
  warnings: string[]
  message: string
}
