import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  filenameFromDisposition,
  getImpact,
  getTimeline,
  getTour,
  requestExport,
} from '../api/graph'
import type { ImpactGraph, Timeline, Tour } from '../api/types'

const IMPACT: ImpactGraph = {
  seed: 'rfc:2394',
  nodes: [{ id: 'rfc:2394', label: 'Decision', name: 'async/await', depth: 0 }],
  edges: [],
  evidence_types: [],
  truncated: false,
}

const TIMELINE: Timeline = {
  decisions: [],
  supersede_edges: [],
  areas: [],
  teams: [],
  tours: ['async_await'],
}

const TOUR: Tour = { tour: 'async_await', stages: [], transitions: [] }

afterEach(() => {
  vi.restoreAllMocks()
})

describe('graph clients', () => {
  it('resolves an impact graph and URL-encodes the id', async () => {
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(new Response(JSON.stringify(IMPACT), { status: 200 }))

    await expect(getImpact('rfc:2394')).resolves.toEqual(IMPACT)
    expect(fetchMock).toHaveBeenCalledWith('/graph/impact/rfc%3A2394', {
      signal: undefined,
    })
  })

  it('returns null for an unknown impact seed (404)', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('', { status: 404 }))
    await expect(getImpact('rfc:999')).resolves.toBeNull()
  })

  it('throws on any other impact error status', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('', { status: 500 }))
    await expect(getImpact('rfc:2394')).rejects.toThrow(
      'GET /graph/impact/rfc:2394 failed: 500',
    )
  })

  it('resolves the flat timeline', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(TIMELINE), { status: 200 }),
    )
    await expect(getTimeline()).resolves.toEqual(TIMELINE)
  })

  it('resolves a tour through the timeline query param', async () => {
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(new Response(JSON.stringify(TOUR), { status: 200 }))

    await expect(getTour('async_await')).resolves.toEqual(TOUR)
    expect(fetchMock).toHaveBeenCalledWith('/timeline?tour=async_await', {
      signal: undefined,
    })
  })

  it('throws when the timeline read fails', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('', { status: 503 }))
    await expect(getTimeline()).rejects.toThrow('GET /timeline failed: 503')
  })
})

describe('exports', () => {
  it('parses the filename from a Content-Disposition header', () => {
    expect(
      filenameFromDisposition('attachment; filename="rfc-2394.md"'),
    ).toBe('rfc-2394.md')
    expect(filenameFromDisposition('inline')).toBeNull()
  })

  it('POSTs the request and returns the bytes with the filename', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('body', {
        status: 200,
        headers: { 'content-disposition': 'attachment; filename="rfc-2394.md"' },
      }),
    )

    const result = await requestExport('/exports/report', { node_id: 'rfc:2394' })

    expect(result.filename).toBe('rfc-2394.md')
    await expect(result.blob.text()).resolves.toBe('body')
    expect(fetchMock).toHaveBeenCalledWith('/exports/report', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ node_id: 'rfc:2394' }),
      signal: undefined,
    })
  })

  it('falls back to a generic filename when the header is missing', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('{}', { status: 200 }),
    )

    const result = await requestExport('/exports/graph', { node_id: 'rfc:2394' })
    expect(result.filename).toBe('decision-cortex-export')
  })

  it('throws on a failed export', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('', { status: 409 }))
    await expect(
      requestExport('/exports/report', { scenario: 'async_story' }),
    ).rejects.toThrow('POST /exports/report failed: 409')
  })
})
