import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, deleteJson, patchJson, postJson } from '@/lib/api'
import { headerOf, stubFetch } from './helpers'

afterEach(() => vi.unstubAllGlobals())

describe('mutating request helpers', () => {
  it('postJson sends the guard header and a JSON body', async () => {
    const f = stubFetch(() => ({ status: 201, body: { id: 3 } }))
    const out = await postJson<{ id: number }>('/api/cards', { title: 't' })
    expect(out).toEqual({ id: 3 })
    const [url, init] = f.mock.calls[0]!
    expect(url).toBe('/api/cards')
    expect(init?.method).toBe('POST')
    expect(headerOf(init, 'X-Mac-Control')).toBe('1')
    expect(headerOf(init, 'Content-Type')).toBe('application/json')
    expect(init?.body).toBe(JSON.stringify({ title: 't' }))
  })

  it('postJson without a body sends the guard header and no content type', async () => {
    const f = stubFetch(() => ({ body: { cancelled: 4 } }))
    await postJson('/api/runs/4/cancel')
    const init = f.mock.calls[0]![1]
    expect(headerOf(init, 'X-Mac-Control')).toBe('1')
    expect(headerOf(init, 'Content-Type')).toBeUndefined()
    expect(init?.body).toBeUndefined()
  })

  it('patchJson sends PATCH with the guard header', async () => {
    const f = stubFetch(() => ({ body: { id: 1, column: 'queued' } }))
    await patchJson('/api/cards/1', { column: 'queued' })
    const init = f.mock.calls[0]![1]
    expect(init?.method).toBe('PATCH')
    expect(headerOf(init, 'X-Mac-Control')).toBe('1')
    expect(headerOf(init, 'Content-Type')).toBe('application/json')
    expect(init?.body).toBe('{"column":"queued"}')
  })

  it('deleteJson sends DELETE with the guard header and tolerates 204', async () => {
    const f = stubFetch(() => ({ status: 204 }))
    await expect(deleteJson('/api/cards/1')).resolves.toBeUndefined()
    const init = f.mock.calls[0]![1]
    expect(init?.method).toBe('DELETE')
    expect(headerOf(init, 'X-Mac-Control')).toBe('1')
  })

  it.each([
    ['postJson', () => postJson('/api/cards/1/approve')],
    ['patchJson', () => patchJson('/api/cards/1', { column: 'running' })],
    ['deleteJson', () => deleteJson('/api/cards/1')],
  ])('%s throws ApiError carrying the server detail on 409', async (_name, call) => {
    stubFetch(() => ({ status: 409, body: { detail: 'a running card cannot be moved' } }))
    const err = await call().catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).status).toBe(409)
    expect((err as ApiError).message).toBe('a running card cannot be moved')
  })

  it('flattens a validation-error list into readable text', async () => {
    stubFetch(() => ({ status: 422, body: { detail: [{ loc: ['body', 'working_dir'], msg: 'outside allowed roots' }] } }))
    const err = await postJson('/api/cards', {}).catch((e: unknown) => e)
    expect((err as ApiError).message).toBe('working_dir: outside allowed roots')
  })
})
