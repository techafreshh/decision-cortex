import { useEffect, useState } from 'react'

import type { TraceEntry } from '../../state/runStore'

export interface ThinkingProps {
  traces: TraceEntry[]
}

/** The phase label for what the pipeline has reported so far. */
export function thinkingPhase(traces: TraceEntry[]): string {
  if (traces.some((trace) => trace.toolName === 'claim_gate')) return 'Weighing the claims'
  if (traces.some((trace) => trace.toolName === 'synthesize')) return 'Composing the answer'
  if (traces.some((trace) => trace.toolName === 'retrieve_evidence')) {
    return 'Walking the graph'
  }
  if (traces.some((trace) => trace.toolName === 'router_classify')) {
    return 'Routing the question'
  }
  return 'Starting the run'
}

export function formatElapsed(totalSeconds: number): string {
  if (totalSeconds < 60) return `${totalSeconds}s`
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return `${minutes}m ${String(seconds).padStart(2, '0')}s`
}

/**
 * The in-flight indicator: a pulsing marker, the current pipeline phase, and
 * the honest elapsed time. The backend computes an answer's whole plan before
 * the first tool event streams, so on a cold run (a scenario not yet cached on
 * the deployment) this may tick for a while — the copy says so, it never
 * fakes progress.
 */
export function Thinking({ traces }: ThinkingProps) {
  const [seconds, setSeconds] = useState(0)

  useEffect(() => {
    const timer = window.setInterval(() => setSeconds((value) => value + 1), 1000)
    return () => window.clearInterval(timer)
  }, [])

  return (
    <div className="thinking" role="status" aria-live="polite">
      <span className="thinking__mark" aria-hidden="true">
        <svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor">
          <path d="M8 0l2.2 5.8L16 8l-5.8 2.2L8 16l-2.2-5.8L0 8l5.8-2.2L8 0z" />
        </svg>
      </span>
      <span className="thinking__phase">
        {thinkingPhase(traces)}
        <span className="thinking__elapsed">{formatElapsed(seconds)}</span>
      </span>
      <span className="sr-only">The answer is being computed</span>
      {seconds >= 30 ? (
        <p className="thinking__note">
          A cold first compute walks the whole graph server-side before the
          first event streams — cached replays land in seconds.
        </p>
      ) : null}
      {traces.length === 0 ? null : (
        <ol className="thinking__trace">
          {traces.map((trace, index) => (
            <li key={`${trace.toolName}-${index}`} className={trace.status}>
              <code>{trace.toolName}</code>
              <span className="thinking__status">{trace.status}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}
