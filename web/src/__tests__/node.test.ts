import { afterEach, describe, expect, it, vi } from 'vitest'

import { getNode } from '../api/node'
import type { NodeDetail } from '../api/types'

const DETAIL: NodeDetail = {
  id: 'message:5001',
  label: 'Message',
  properties: { author: 'bob' },
  source: {
    url: 'https://github.com/rust-lang/rfcs/pull/200#issuecomment-5001',
    author: 'bob',
    date: '2019-01-01T00:00:00Z',
    stance: null,
    truncated: true,
  },
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('getNode', () => {
  it('resolves the node detail and URL-encodes the id', async () => {
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValue(new Response(JSON.stringify(DETAIL), { status: 200 }))

    await expect(getNode('message:5001')).resolves.toEqual(DETAIL)
    expect(fetchMock).toHaveBeenCalledWith('/node/message%3A5001', {
      signal: undefined,
    })
  })

  it('returns null for an unknown id (404)', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('', { status: 404 }))
    await expect(getNode('rfc:999')).resolves.toBeNull()
  })

  it('throws on any other error status', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('', { status: 500 }))
    await expect(getNode('rfc:200')).rejects.toThrow('GET /node/rfc:200 failed: 500')
  })
})
