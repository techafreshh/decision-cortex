/**
 * The `GET /node/{id}` client backing the `SourcePanel`.
 *
 * A citation chip carries only `{id, label, title}`; opening the real source
 * means resolving the id against the graph. The graph stores refs, never
 * bodies, so the panel renders the node's metadata plus a deep link to the real
 * GitHub/RFC URL rather than any text the graph does not hold.
 */

import type { NodeDetail } from './types'

export async function getNode(
  id: string,
  signal?: AbortSignal,
): Promise<NodeDetail | null> {
  const response = await fetch(`/node/${encodeURIComponent(id)}`, { signal })
  if (response.status === 404) return null
  if (!response.ok) {
    throw new Error(`GET /node/${id} failed: ${response.status}`)
  }
  return (await response.json()) as NodeDetail
}
