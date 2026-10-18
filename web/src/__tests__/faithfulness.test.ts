import { afterEach, describe, expect, it, vi } from 'vitest'

import { scoreFaithfulness } from '../api/faithfulness'

const REPORT = {
  faithfulness: 1.0,
  claims_total: 2,
  claims_supported: 2,
  claims_scored: 2,
  claims_unresolved: 0,
  threshold: 0.5,
  model: 'faithfulness:hhem-2.1-open',
  latency_ms: 4211,
  claims: [],
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('scoreFaithfulness', () => {
  it('short-circuits an answer with no claims to score', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    const [report, error] = await scoreFaithfulness([])

    expect(report).toBeNull()
    expect(error).toBeNull()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('posts the claims and resolves the report', async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify(REPORT), { status: 200 }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const [report, error] = await scoreFaithfulness([
      { sentence: 'Rust decided X.', evidence_ids: ['rfc:200'] },
    ])

    expect(error).toBeNull()
    expect(report?.faithfulness).toBe(1.0)
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/faithfulness')
    expect(JSON.parse(String(init.body))).toEqual({
      claims: [{ sentence: 'Rust decided X.', evidence_ids: ['rfc:200'] }],
    })
  })

  it('turns a failure into a message instead of a throw', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        new Response(JSON.stringify({ detail: 'local HHEM scorer missing' }), {
          status: 503,
        }),
      ),
    )

    const [report, error] = await scoreFaithfulness([
      { sentence: 'A claim.', evidence_ids: [] },
    ])

    expect(report).toBeNull()
    expect(error).toContain('503')
    expect(error).toContain('local HHEM scorer missing')
  })
})
