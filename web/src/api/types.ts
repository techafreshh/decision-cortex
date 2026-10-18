/**
 * The web mirror of the frozen AG-UI/SSE schema (`api/events.py`, PRD §10).
 *
 * These types are the contract between the SPA and `POST /ask`: the event names
 * and payload field names are snake_case and match the backend exactly. Keep
 * them in lockstep with `api/events.py` — the backend is the source of truth.
 */

export type EventType =
  | 'RUN_STARTED'
  | 'TOOL_CALL_START'
  | 'TOOL_CALL_ARGS'
  | 'TOOL_CALL_END'
  | 'TOOL_CALL_RESULT'
  | 'TEXT_MESSAGE_START'
  | 'TEXT_MESSAGE_CONTENT'
  | 'TEXT_MESSAGE_END'
  | 'CYPHER_PREVIEW'
  | 'LEDGER_UPDATE'
  | 'FAITHFULNESS_PENDING'
  | 'RUN_FINISHED'

/** A citation chip: only the id, label, and title travel on the stream. */
export interface CitationChip {
  id: string
  label: string
  title: string
}

/** One decision-ledger row (the locked seven-field schema, `api/llm.py`). */
export interface LedgerRecord {
  input_digest: string
  choice: string | number | boolean | null
  confidence: number | null
  model: string
  latency_ms: number
  cost_usd: number
  escalated: boolean
}

/** The ledger summary embedded in `LEDGER_UPDATE` and `RUN_FINISHED`. */
export interface LedgerSummary {
  calls: number
  cost_usd: number
  total_calls: number
  total_cost_usd: number
  records: LedgerRecord[]
}

/** One real decision the search reached but that did not answer the question. */
export interface CameClose {
  id: string
  label: string
  title: string
}

/** The `record_abstention` result the `NoRecordCard` renders. */
export interface AbstentionReceipt {
  nodes_searched: number
  evidence_chains: number
  matches: number
  came_close: CameClose[]
}

/** One claim-gate verdict, carried in the `claim_gate` result. */
export interface ClaimVerdict {
  sentence: string
  cited: boolean
  confidence: number | null
  evidence_ids: string[]
}

export interface RouterResult {
  route: string
  confidence: number
  escalated: boolean
}

export interface RetrievalResult {
  candidate_count: number
  rounds: number
  stopped_early: boolean
}

/** The discriminated union of every event the stream can carry. */
export type AskEvent =
  | { type: 'RUN_STARTED'; question: string; scenario: string | null }
  | { type: 'TOOL_CALL_START'; tool_call_id: string; tool_name: string }
  | { type: 'TOOL_CALL_ARGS'; tool_call_id: string; delta: string }
  | { type: 'TOOL_CALL_END'; tool_call_id: string }
  | { type: 'TOOL_CALL_RESULT'; tool_call_id: string; result: unknown }
  | { type: 'TEXT_MESSAGE_START'; message_id: string }
  | {
      type: 'TEXT_MESSAGE_CONTENT'
      message_id: string
      delta: string
      chips: CitationChip[]
      cited: boolean
    }
  | { type: 'TEXT_MESSAGE_END'; message_id: string }
  | { type: 'CYPHER_PREVIEW'; queries: string[] }
  | { type: 'LEDGER_UPDATE'; ledger: LedgerSummary }
  | { type: 'FAITHFULNESS_PENDING' }
  | {
      type: 'RUN_FINISHED'
      citation_count: number
      claims_total: number
      claims_cited: number
      abstention_required: boolean
      ledger: LedgerSummary
    }

/** A node detail from `GET /node/{id}` (`api/nodes.py`). */
export interface NodeSource {
  url: string | null
  author: string | null
  date: string | null
  stance: string | null
  truncated: boolean | null
}

export interface NodeDetail {
  id: string
  label: string
  properties: Record<string, unknown>
  source: NodeSource
}

/** One node in the blast radius from `GET /graph/impact/{id}` (`api/impact.py`). */
export interface ImpactNode {
  id: string
  label: string
  name: string
  depth: number
}

/** One traversed edge; `src`/`dst` keep the graph's stored direction. */
export interface ImpactEdge {
  src: string
  dst: string
  type: string
  properties: Record<string, unknown>
}

export interface ImpactGraph {
  seed: string
  nodes: ImpactNode[]
  edges: ImpactEdge[]
  evidence_types: string[]
  truncated: boolean
}

/** One stance edge (`OBJECTED`/`SUPPORTED`/`MODERATED`) pointing at a decision. */
export interface Stance {
  handle: string
  kind: string
  evidence: string | null
  confidence: number | null
}

export interface SupersedeEdge {
  src: string
  dst: string
}

export interface TimelineDecision {
  id: string
  rfc: number | null
  title: string
  status: string | null
  proposed_on: string | null
  decided_on: string | null
  areas: string[]
  teams: string[]
  supersedes: number[]
  superseded_by: number[]
  stances: Stance[]
}

/** The flat timeline from `GET /timeline` (`api/timeline.py`). */
export interface Timeline {
  decisions: TimelineDecision[]
  supersede_edges: SupersedeEdge[]
  areas: string[]
  teams: string[]
  tours: string[]
}

/** One curated stage of a lifecycle tour (`GET /timeline?tour=...`). */
export interface TourStage {
  id: string
  rfc: number
  title: string
  status: string | null
  proposed_on: string | null
  decided_on: string | null
  role: string
  narrative: string
}

export interface TourTransition {
  from: string
  to: string
  label: string
}

export interface Tour {
  tour: string
  stages: TourStage[]
  transitions: TourTransition[]
}
