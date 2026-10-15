/** Shape of GET /api/projects/{id}/standards (see apps/api/standards.py). */
export interface StandardsArea { area: string; risk: 'low' | 'medium' | 'high'; route: string }
export interface StandardsCheck { touches: string; run: string }
export interface StandardsProposal {
  id: number; created_at: number; created_by: string; project_id: number; summary: string; section: string; patch: string
  status: 'pending' | 'applied' | 'rejected' | 'failed'; decided_by: string | null; result: { branch?: string; commit?: string; note?: string; reason?: string } | null
}
export interface Standards {
  state: 'ok' | 'missing' | 'unreadable' | 'no_workdir'
  source?: 'repository' | 'starter' | 'none'
  starter_from?: 'shipped' | 'your copy'
  repo_state?: 'ok' | 'missing' | 'unreadable' | 'no_workdir'
  path: string
  property: string | null
  sha256: string | null
  areas: StandardsArea[]
  checks: StandardsCheck[]
  warnings: string[]
  message: string
}
