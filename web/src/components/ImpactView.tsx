/**
 * The Impact Explorer surface: pick a decision id, see what it touches.
 *
 * Wraps `ImpactGraph` with the fetch lifecycle and a portable-export button
 * (`POST /exports/graph`), so the same picture a judge sees on screen is
 * downloadable as JSON.
 */

import { useEffect, useState, type FormEvent } from 'react'

import { downloadGraph, getImpact } from '../api/graph'
import type { ImpactGraph as ImpactGraphData } from '../api/types'
import { ImpactGraph } from './ImpactGraph'
import { Button } from './kit/Button'

/** RFC 2394 (async/await) — the seed the demo beat opens on. */
export const DEFAULT_IMPACT_SEED = 'rfc:2394'

type Status = 'loading' | 'ready' | 'missing' | 'error'

export function ImpactView() {
  const [seed, setSeed] = useState(DEFAULT_IMPACT_SEED)
  const [draft, setDraft] = useState(DEFAULT_IMPACT_SEED)
  const [graph, setGraph] = useState<ImpactGraphData | null>(null)
  const [status, setStatus] = useState<Status>('loading')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    setStatus('loading')
    setError(null)
    setGraph(null)
    getImpact(seed, controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return
        if (result === null) {
          setStatus('missing')
        } else {
          setGraph(result)
          setStatus('ready')
        }
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return
        setError(cause instanceof Error ? cause.message : String(cause))
        setStatus('error')
      })
    return () => controller.abort()
  }, [seed])

  const explore = (event: FormEvent) => {
    event.preventDefault()
    const trimmed = draft.trim()
    if (trimmed !== '') setSeed(trimmed)
  }

  const bloom = (id: string) => {
    setSeed(id)
    setDraft(id)
  }

  const exportGraph = () => {
    downloadGraph({ node_id: seed }).catch((cause: unknown) => {
      setError(cause instanceof Error ? cause.message : String(cause))
    })
  }

  return (
    <section className="impactView">
      <form className="impactView__form" onSubmit={explore}>
        <input
          className="impactView__input"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="rfc:2394"
          aria-label="Decision id"
        />
        <Button type="submit" variant="primary">
          Explore
        </Button>
        <Button
          type="button"
          variant="ghost"
          disabled={status !== 'ready'}
          onClick={exportGraph}
        >
          Export JSON
        </Button>
      </form>

      {status === 'loading' ? (
        <div className="impactSkeleton" role="status">
          <span className="skeletonCard__bar skeletonCard__bar--short" />
          <span className="sr-only">Walking the graph…</span>
          walking the graph…
        </div>
      ) : null}
      {status === 'missing' ? (
        <p className="muted">No graph node matches {seed}.</p>
      ) : null}
      {error === null ? null : <p className="error">{error}</p>}

      {graph === null ? null : (
        <ImpactGraph graph={graph} onSelectNode={bloom} />
      )}
    </section>
  )
}
