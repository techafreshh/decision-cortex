import { useState } from 'react'

import type { TraceEntry } from '../state/runStore'
import { Traces } from './Traces'

/** The collapsible "show your work" strip: the generative-UI tool-call trace. */
export function ShowYourWork({ traces }: { traces: TraceEntry[] }) {
  const [open, setOpen] = useState(false)
  if (traces.length === 0) return null
  return (
    <section className="card card--plain showyourwork">
      <button
        type="button"
        className="showyourwork__toggle"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="showyourwork__caret">{open ? '▾' : '▸'}</span>
        Show your work — {traces.length}{' '}
        {traces.length === 1 ? 'tool call' : 'tool calls'}
      </button>
      {open ? <Traces traces={traces} /> : null}
    </section>
  )
}
