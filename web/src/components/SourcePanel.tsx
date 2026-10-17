import { createContext, useContext, useEffect, useState } from 'react'

import { getNode } from '../api/node'
import type { NodeDetail } from '../api/types'
import { Badge } from './kit/Badge'
import { Drawer } from './kit/Drawer'

/**
 * Any citation chip can open the source panel. The panel is a single instance
 * mounted by `App`, so chips publish the node id through this context instead
 * of each chip owning a drawer.
 */
const OpenNodeContext = createContext<(id: string) => void>(() => {})

export function useOpenNode(): (id: string) => void {
  return useContext(OpenNodeContext)
}

export const OpenNodeProvider = OpenNodeContext.Provider

export interface SourcePanelProps {
  nodeId: string | null
  onClose: () => void
}

export function SourcePanel({ nodeId, onClose }: SourcePanelProps) {
  const [detail, setDetail] = useState<NodeDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (nodeId === null) return
    const controller = new AbortController()
    setLoading(true)
    setDetail(null)
    setError(null)
    getNode(nodeId, controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return
        setDetail(result)
        setLoading(false)
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return
        setError(cause instanceof Error ? cause.message : String(cause))
        setLoading(false)
      })
    return () => controller.abort()
  }, [nodeId])

  const title = detail === null ? (nodeId ?? 'Source') : `${detail.label} · ${detail.id}`

  return (
    <Drawer open={nodeId !== null} title={title} onClose={onClose}>
      {loading ? <p className="muted">Loading source…</p> : null}
      {error === null ? null : <p className="error">{error}</p>}
      {!loading && error === null && detail === null ? (
        <p className="muted">No graph node matches {nodeId}.</p>
      ) : null}
      {detail === null ? null : <NodeBody detail={detail} />}
    </Drawer>
  )
}

function NodeBody({ detail }: { detail: NodeDetail }) {
  const { source } = detail
  return (
    <div className="source">
      <p className="source__note">
        The graph stores refs, not bodies — the real text lives at the link.
      </p>
      {source.url === null ? (
        <p className="muted">No external link recorded for this node.</p>
      ) : (
        <a
          className="source__link"
          href={source.url}
          target="_blank"
          rel="noreferrer"
        >
          {source.url}
        </a>
      )}
      <dl className="source__meta">
        <MetaRow label="Author" value={source.author} />
        <MetaRow label="Date" value={source.date} />
        <MetaRow label="Stance" value={source.stance} />
        <MetaRow
          label="Truncated"
          value={source.truncated === null ? null : source.truncated ? 'yes' : 'no'}
        />
      </dl>
      <h4 className="source__heading">
        Graph properties <Badge tone="muted">{detail.label}</Badge>
      </h4>
      <table className="props">
        <tbody>
          {Object.entries(detail.properties).map(([key, value]) => (
            <tr key={key}>
              <th scope="row">{key}</th>
              <td>{formatValue(value)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function MetaRow({ label, value }: { label: string; value: string | null }) {
  return (
    <div className="source__metaRow">
      <dt>{label}</dt>
      <dd>{value ?? '—'}</dd>
    </div>
  )
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}
