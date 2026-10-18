import { describe, expect, it } from 'vitest'

import type { ImpactGraph } from '../api/types'
import { IMPACT_FLOW_HEIGHT, IMPACT_FLOW_WIDTH, impactFlow } from '../lib/impactFlow'

const GRAPH: ImpactGraph = {
  seed: 'rfc:2394',
  nodes: [
    { id: 'area:async', label: 'Area', name: 'async', depth: 1 },
    { id: 'rfc:2394', label: 'Decision', name: 'async/await', depth: 0 },
    { id: 'rfc:3083', label: 'Decision', name: 'update 2033', depth: 1 },
    { id: 'person:alice', label: 'Person', name: 'alice', depth: 2 },
  ],
  edges: [
    { src: 'rfc:2394', dst: 'area:async', type: 'AREA', properties: {} },
    { src: 'rfc:2394', dst: 'person:alice', type: 'PROPOSED_BY', properties: {} },
    { src: 'rfc:3083', dst: 'rfc:2394', type: 'SUPERSEDES', properties: {} },
    { src: 'rfc:2394', dst: 'rfc:999', type: 'SUPERSEDES', properties: {} },
  ],
  evidence_types: ['AREA', 'PROPOSED_BY', 'SUPERSEDES'],
  truncated: false,
}

describe('impactFlow', () => {
  it('centres the depth-0 seed', () => {
    const { nodes } = impactFlow(GRAPH)
    const seed = nodes.find((node) => node.id === 'rfc:2394')
    expect(seed?.position).toEqual({
      x: IMPACT_FLOW_WIDTH / 2,
      y: IMPACT_FLOW_HEIGHT / 2,
    })
    expect(seed?.data).toEqual({ name: 'async/await', kind: 'Decision', depth: 0 })
  })

  it('orders nodes by depth then id, deterministically', () => {
    const ids = impactFlow(GRAPH).nodes.map((node) => node.id)
    expect(ids).toEqual(['rfc:2394', 'area:async', 'rfc:3083', 'person:alice'])
    expect(impactFlow(GRAPH).nodes.map((n) => n.position)).toEqual(
      impactFlow(GRAPH).nodes.map((n) => n.position),
    )
  })

  it('labels edges and animates supersession', () => {
    const edges = impactFlow(GRAPH).edges
    expect(edges.find((edge) => edge.id.endsWith('AREA'))?.label).toBe('area')
    expect(edges.find((edge) => edge.id.endsWith('PROPOSED_BY'))?.label).toBe(
      'proposed by',
    )
    const supersede = edges.find((edge) => edge.id === 'rfc:3083->rfc:2394:SUPERSEDES')
    expect(supersede?.animated).toBe(true)
  })

  it('drops edges whose endpoints are not in the node set', () => {
    const edges = impactFlow(GRAPH).edges
    expect(edges.some((edge) => edge.target === 'rfc:999')).toBe(false)
    expect(edges).toHaveLength(3)
  })
})
