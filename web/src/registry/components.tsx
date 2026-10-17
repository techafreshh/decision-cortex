/**
 * The generative-UI registry: one component per backend tool call.
 *
 * Every tool call the stream carries (`router_classify`, `retrieve_evidence`,
 * `synthesize`, `claim_gate`, `record_abstention`) renders as a registered
 * component; `renderTool` dispatches on the tool name and falls back to the raw
 * JSON for a tool the UI has not registered yet, so a new backend tool degrades
 * gracefully instead of disappearing.
 */

import type { ReactNode } from 'react'

import type {
  AbstentionReceipt,
  ClaimVerdict,
  RetrievalResult,
  RouterResult,
} from '../api/types'
import type { TraceEntry } from '../state/runStore'
import { Badge } from '../components/kit/Badge'

export type ToolRenderer = (trace: TraceEntry) => ReactNode

function RouterCard({ result }: { result: RouterResult }) {
  return (
    <p className="tool">
      route <Badge tone="plain">{result.route}</Badge> · confidence{' '}
      <strong>{result.confidence.toFixed(2)}</strong>
      {result.escalated ? <Badge tone="warn">escalated to S2</Badge> : null}
    </p>
  )
}

function RetrievalCard({ result }: { result: RetrievalResult }) {
  return (
    <p className="tool">
      <strong>{result.candidate_count}</strong> candidates over{' '}
      <strong>{result.rounds}</strong>{' '}
      {result.rounds === 1 ? 'round' : 'rounds'}
      {result.stopped_early ? (
        <Badge tone="good">sufficiency stop</Badge>
      ) : null}
    </p>
  )
}

function SynthesizeCard({ result }: { result: { sentences: number } }) {
  return (
    <p className="tool">
      synthesized <strong>{result.sentences}</strong>{' '}
      {result.sentences === 1 ? 'sentence' : 'sentences'}
    </p>
  )
}

function ClaimGateCard({ result }: { result: { verdicts: ClaimVerdict[] } }) {
  const cited = result.verdicts.filter((verdict) => verdict.cited).length
  return (
    <div className="tool">
      <p>
        gated <strong>{result.verdicts.length}</strong> claims ·{' '}
        <strong>{cited}</strong> cited
      </p>
      <ul className="verdicts">
        {result.verdicts.map((verdict, index) => (
          <li key={index}>
            <Badge tone={verdict.cited ? 'good' : 'warn'}>
              {verdict.cited ? 'cited' : 'uncited'}
            </Badge>{' '}
            <span className="verdicts__sentence">{verdict.sentence}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function AbstentionCard({ result }: { result: AbstentionReceipt }) {
  return (
    <p className="tool">
      abstained after searching <strong>{result.nodes_searched}</strong> nodes
      and <strong>{result.evidence_chains}</strong> chains
    </p>
  )
}

const REGISTRY: Record<string, ToolRenderer> = {
  router_classify: (trace) => <RouterCard result={trace.result as RouterResult} />,
  retrieve_evidence: (trace) => (
    <RetrievalCard result={trace.result as RetrievalResult} />
  ),
  synthesize: (trace) => (
    <SynthesizeCard result={trace.result as { sentences: number }} />
  ),
  claim_gate: (trace) => (
    <ClaimGateCard result={trace.result as { verdicts: ClaimVerdict[] }} />
  ),
  record_abstention: (trace) => (
    <AbstentionCard result={trace.result as AbstentionReceipt} />
  ),
}

export function renderTool(trace: TraceEntry): ReactNode {
  if (trace.status === 'running') {
    return <p className="muted">running…</p>
  }
  const renderer = REGISTRY[trace.toolName]
  if (renderer === undefined) {
    return <pre className="tool__raw">{JSON.stringify(trace.result, null, 2)}</pre>
  }
  return renderer(trace)
}
