/**
 * The Impact Explorer canvas: the blast radius around one decision.
 *
 * `ImpactGraph` is deliberately thin — the layout math lives in
 * `lib/impactFlow.ts` (unit-tested in Node) and this only mounts React Flow
 * around it. Clicking a node re-seeds the walk from it (the "bloom"), and
 * hovering one dims everything not directly connected (the hover-focus beat).
 */

import {
  Background,
  Controls,
  ReactFlow,
  type NodeProps,
  type NodeTypes,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { createContext, useContext, useMemo, useState } from 'react'

import type { ImpactGraph as ImpactGraphData } from '../api/types'
import { impactFlow, type ImpactFlowNode } from '../lib/impactFlow'

const SelectNodeContext = createContext<(id: string) => void>(() => {})

function ImpactNodeView({ id, data }: NodeProps<ImpactFlowNode>) {
  const selectNode = useContext(SelectNodeContext)
  const depth = Math.min(data.depth, 3)
  return (
    <button
      type="button"
      className={`impactNode impactNode--d${depth}`}
      onClick={() => selectNode(id)}
    >
      <span className="impactNode__name">{data.name}</span>
      <span className="impactNode__meta">
        {data.kind} · depth {data.depth}
      </span>
    </button>
  )
}

const NODE_TYPES: NodeTypes = { impact: ImpactNodeView }

export interface ImpactGraphProps {
  graph: ImpactGraphData
  onSelectNode: (id: string) => void
}

export function ImpactGraph({ graph, onSelectNode }: ImpactGraphProps) {
  const { nodes, edges } = useMemo(() => impactFlow(graph), [graph])
  const [hovered, setHovered] = useState<string | null>(null)

  const connected = useMemo(() => {
    if (hovered === null) return null
    const ids = new Set([hovered])
    for (const edge of edges) {
      if (edge.source === hovered || edge.target === hovered) {
        ids.add(edge.source)
        ids.add(edge.target)
      }
    }
    return ids
  }, [hovered, edges])

  const styledNodes = useMemo(
    () =>
      nodes.map((node) => ({
        ...node,
        className: connected !== null && !connected.has(node.id) ? 'dimmed' : '',
      })),
    [nodes, connected],
  )

  const styledEdges = useMemo(
    () =>
      edges.map((edge) => ({
        ...edge,
        className:
          hovered !== null && edge.source !== hovered && edge.target !== hovered
            ? 'dimmed'
            : '',
      })),
    [edges, hovered],
  )

  return (
    <div className="impact">
      <SelectNodeContext.Provider value={onSelectNode}>
        <ReactFlow
          nodes={styledNodes}
          edges={styledEdges}
          nodeTypes={NODE_TYPES}
          fitView
          minZoom={0.2}
          nodesDraggable={false}
          nodesConnectable={false}
          edgesFocusable={false}
          onNodeMouseEnter={(_event, node) => setHovered(node.id)}
          onNodeMouseLeave={() => setHovered(null)}
        >
          <Background />
          <Controls showInteractive={false} />
        </ReactFlow>
      </SelectNodeContext.Provider>
      <p className="impact__legend">
        {graph.evidence_types.length === 0
          ? 'No traversed relations.'
          : `Relations: ${graph.evidence_types.join(', ')}`}
        {graph.truncated ? ' · truncated at the node cap' : ''}
      </p>
    </div>
  )
}
