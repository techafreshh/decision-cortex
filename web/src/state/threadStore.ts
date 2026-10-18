/**
 * The thread store: a pure reducer turning per-run AG-UI folds into a chat
 * conversation. `runStore` still owns one run's state — untouched — and every
 * `RunEntry` embeds exactly one of those folds, driven by the same events, so
 * the provenance contract (chips, receipts, ledger rows) cannot drift between
 * the single-run and thread surfaces.
 *
 * Entries are append-only: a finished run stays in the thread as its own
 * message, with its sentences, chips, abstention card, and ledger rows intact.
 * Only one run may be in flight (`runningId`) — the System-1 budget doctrine
 * and the per-scenario compute lock both assume a user cannot race questions.
 */

import type { AskEvent, FaithfulnessReport } from '../api/types'
import { initialRunState, reduceRun, type RunState } from './runStore'

export interface UserEntry {
  kind: 'user'
  id: string
  text: string
  /** The scripted scenario driving this question, when one does. */
  scenarioKey: string | null
}

export interface RunEntry {
  kind: 'run'
  id: string
  state: RunState
}

export type ThreadEntry = UserEntry | RunEntry

/** The deploy-wide decision-ledger totals, as of the freshest ledger event. */
export interface ThreadTotals {
  totalCalls: number
  totalCostUsd: number
}

export interface ThreadState {
  entries: ThreadEntry[]
  runningId: string | null
  totals: ThreadTotals
}

export type ThreadAction =
  | { kind: 'ask'; id: string; text: string; scenarioKey: string | null }
  | { kind: 'event'; id: string; event: AskEvent }
  | { kind: 'runError'; id: string; message: string }
  | {
      kind: 'faithfulness'
      id: string
      report: FaithfulnessReport | null
      message: string | null
    }
  | { kind: 'discard' }

export const initialThreadState: ThreadState = {
  entries: [],
  runningId: null,
  totals: { totalCalls: 0, totalCostUsd: 0 },
}

function patchRun(
  state: ThreadState,
  id: string,
  patch: (run: RunState) => RunState,
): ThreadState {
  return {
    ...state,
    entries: state.entries.map((entry) =>
      entry.kind === 'run' && entry.id === id
        ? { ...entry, state: patch(entry.state) }
        : entry,
    ),
  }
}

function foldTotals(state: ThreadState, event: AskEvent): ThreadTotals {
  if (event.type === 'LEDGER_UPDATE' || event.type === 'RUN_FINISHED') {
    return {
      totalCalls: event.ledger.total_calls,
      totalCostUsd: event.ledger.total_cost_usd,
    }
  }
  return state.totals
}

/** Fold one action into the thread state. Pure: no I/O, no clock, no randomness. */
export function reduceThread(state: ThreadState, action: ThreadAction): ThreadState {
  if (action.kind === 'discard') {
    return initialThreadState
  }

  if (action.kind === 'ask') {
    // One in-flight run at a time; the caller disables the composer, so a
    // second `ask` slipping through is ignored rather than interleaved.
    if (state.runningId !== null) return state
    const runState = reduceRun(initialRunState, {
      kind: 'reset',
      request: { question: action.text, scenario: action.scenarioKey },
    })
    return {
      ...state,
      entries: [
        ...state.entries,
        { kind: 'user', id: `q-${action.id}`, text: action.text, scenarioKey: action.scenarioKey },
        { kind: 'run', id: action.id, state: runState },
      ],
      runningId: action.id,
    }
  }

  const known = state.entries.some(
    (entry) => entry.kind === 'run' && entry.id === action.id,
  )
  if (!known) return state

  if (action.kind === 'event') {
    const next = patchRun(state, action.id, (run) => reduceRun(run, { kind: 'event', event: action.event }))
    const withTotals = { ...next, totals: foldTotals(next, action.event) }
    if (action.event.type === 'RUN_FINISHED' && withTotals.runningId === action.id) {
      return { ...withTotals, runningId: null }
    }
    return withTotals
  }

  if (action.kind === 'runError') {
    const next = patchRun(state, action.id, (run) =>
      reduceRun(run, { kind: 'error', message: action.message }),
    )
    return { ...next, runningId: next.runningId === action.id ? null : next.runningId }
  }

  return patchRun(state, action.id, (run) =>
    reduceRun(run, { kind: 'faithfulness', report: action.report, message: action.message }),
  )
}

/** The in-flight run entry, when one is streaming. */
export function activeEntry(state: ThreadState): RunEntry | null {
  if (state.runningId === null) return null
  const entry = state.entries.find(
    (candidate) => candidate.kind === 'run' && candidate.id === state.runningId,
  )
  return entry && entry.kind === 'run' ? entry : null
}
