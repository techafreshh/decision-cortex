/**
 * The run store: a pure reducer folding the AG-UI event stream into the shape
 * the components render.
 *
 * One run is one `POST /ask`. Tool-call events become trace entries (the
 * generative-UI registry renders each one); `TEXT_MESSAGE_CONTENT` deltas build
 * the answer sentence by sentence; `CYPHER_PREVIEW` carries the Cypher actually
 * run; the `record_abstention` result becomes the `NoRecordCard` receipt; and
 * `LEDGER_UPDATE` carries the decision-ledger rows for the footer. Keeping the
 * fold pure means the whole stream contract is unit-testable with no DOM.
 */

import type {
  AbstentionReceipt,
  AskEvent,
  CitationChip,
  LedgerSummary,
} from '../api/types'

export interface TraceEntry {
  toolName: string
  status: 'running' | 'done'
  args: string
  result: unknown
}

export interface Sentence {
  text: string
  chips: CitationChip[]
  cited: boolean
}

export interface RunState {
  question: string
  scenario: string | null
  running: boolean
  traces: TraceEntry[]
  sentences: Sentence[]
  queries: string[]
  ledger: LedgerSummary | null
  abstention: AbstentionReceipt | null
  faithfulnessPending: boolean
  finished: boolean
  error: string | null
}

export interface AskRequestLike {
  question?: string
  scenario?: string | null
}

export type RunAction =
  | { kind: 'reset'; request: AskRequestLike }
  | { kind: 'event'; event: AskEvent }
  | { kind: 'error'; message: string }
  | { kind: 'clear' }

export const initialRunState: RunState = {
  question: '',
  scenario: null,
  running: false,
  traces: [],
  sentences: [],
  queries: [],
  ledger: null,
  abstention: null,
  faithfulnessPending: false,
  finished: false,
  error: null,
}

function updateTrace(
  traces: TraceEntry[],
  toolCallId: string,
  patch: Partial<TraceEntry>,
): TraceEntry[] {
  return traces.map((trace, index) =>
    index === traces.length - 1 && trace.toolName === toolCallId
      ? { ...trace, ...patch }
      : trace,
  )
}

/** Fold one action into the run state. Pure: no I/O, no clock, no randomness. */
export function reduceRun(state: RunState, action: RunAction): RunState {
  if (action.kind === 'clear') {
    return initialRunState
  }
  if (action.kind === 'reset') {
    return {
      ...initialRunState,
      question: action.request.question ?? '',
      scenario: action.request.scenario ?? null,
      running: true,
    }
  }
  if (action.kind === 'error') {
    return { ...state, running: false, error: action.message }
  }

  const { event } = action
  switch (event.type) {
    case 'RUN_STARTED':
      return {
        ...state,
        question: event.question,
        scenario: event.scenario,
        running: true,
      }
    case 'TOOL_CALL_START':
      return {
        ...state,
        traces: [
          ...state.traces,
          {
            toolName: event.tool_name,
            status: 'running',
            args: '',
            result: undefined,
          },
        ],
      }
    case 'TOOL_CALL_ARGS':
      return {
        ...state,
        traces: updateTrace(state.traces, event.tool_call_id, { args: event.delta }),
      }
    case 'TOOL_CALL_END':
      return state
    case 'TOOL_CALL_RESULT':
      return {
        ...state,
        traces: updateTrace(state.traces, event.tool_call_id, {
          status: 'done',
          result: event.result,
        }),
        abstention:
          event.tool_call_id === 'record_abstention'
            ? (event.result as AbstentionReceipt)
            : state.abstention,
      }
    case 'TEXT_MESSAGE_CONTENT':
      return {
        ...state,
        sentences: [
          ...state.sentences,
          { text: event.delta, chips: event.chips, cited: event.cited },
        ],
      }
    case 'CYPHER_PREVIEW':
      return { ...state, queries: event.queries }
    case 'LEDGER_UPDATE':
      return { ...state, ledger: event.ledger }
    case 'FAITHFULNESS_PENDING':
      return { ...state, faithfulnessPending: true }
    case 'RUN_FINISHED':
      return {
        ...state,
        running: false,
        finished: true,
        ledger: event.ledger,
      }
    case 'TEXT_MESSAGE_START':
    case 'TEXT_MESSAGE_END':
      return state
    default:
      return state
  }
}
