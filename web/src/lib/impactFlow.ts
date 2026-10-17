/**
 * The pure `ImpactGraph` → React Flow transform.
 *
 * Kept free of any DOM so it can be unit-tested in Node: given the backend's
 * blast-radius payload it returns positioned nodes and styled edges with no
 * randomness (a rerender lands every node in the same place). Depth drives the
 * layout — the seed sits at the centre, each hop is one ring further out — so
 * the picture reads as "how far this decision reaches" at a glance.
 */

import type { Edge, Node } from '@xyflow/react'

import type { ImpactGraph } from '../api/types'
import { evidenceStyle } from './evidenceStyle'

export interface ImpactNodeData extends Record<string, unknown> {
  name: string
  kind: string
  depth: number
}

export type ImpactFlowNode = Node<ImpactNodeData, 'impact'>

export interface ImpactFlow {
  nodes: ImpactFlowNode[]
  edges: Edge[]
}

export const IMPACT_FLOW_WIDTH = 900
export const IMPACT_FLOW_HEIGHT = 560
export const IMPACT_FLOW_RING = 150

function ringPosition(index: number, count: number, depth: number): { x: number; y: number } {
  const centreX = IMPACT_FLOW_WIDTH / 2
  const centreY = IMPACT_FLOW_HEIGHT / 2
  if (depth === 0 || count === 0) return { x: centreX, y: centreY }
  const angle = -Math.PI / 2 + (index * 2 * Math.PI) / count
  const radius = depth * IMPACT_FLOW_RING
  return {
    x: centreX + radius * Math.cos(angle),
    y: centreY + radius * Math.sin(angle),
  }
}

export function impactFlow(graph: ImpactGraph): ImpactFlow {
  const ordered = [...graph.nodes].sort((a, b) =>
    a.depth !== b.depth ? a.depth - b.depth : a.id.localeCompare(b.id),
  )

  const ringCounts = new Map<number, number>()
  for (const node of ordered) {
    ringCounts.set(node.depth, (ringCounts.get(node.depth) ?? 0) + 1)
  }

  const seen = new Map<number, number>()
  const nodes: ImpactFlowNode[] = ordered.map((node) => {
    const index = seen.get(node.depth) ?? 0
    seen.set(node.depth, index + 1)
    return {
      id: node.id,
      type: 'impact',
      position: ringPosition(index, ringCounts.get(node.depth) ?? 1, node.depth),
      data: { name: node.name, kind: node.label, depth: node.depth },
    }
  })

  const ids = new Set(nodes.map((node) => node.id))
  const edges: Edge[] = graph.edges
    .filter((edge) => ids.has(edge.src) && ids.has(edge.dst))
    .map((edge) => ({
      id: `${edge.src}->${edge.dst}:${edge.type}`,
      source: edge.src,
      target: edge.dst,
      label: evidenceStyle(edge.type).label,
      animated: edge.type === 'SUPERSEDES',
      style: { stroke: evidenceStyle(edge.type).color },
    }))

  return { nodes, edges }
}
