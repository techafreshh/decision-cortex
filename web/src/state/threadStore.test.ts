import { describe, expect, it } from 'vitest'

import type { AskEvent, LedgerSummary } from '../api/types'
import { hasRun } from './runStore'
import {
  activeEntry,
  initialThreadState,
  reduceThread,
  type ThreadAction,
  type ThreadState,
} from './threadStore'

const LEDGER: LedgerSummary = {
  calls: 2,
  cost_usd: 0.0006,
  total_calls: 5,
  total_cost_usd: 0.0031,
  records: [],
}

const event = (value: AskEvent, id = 'r1'): ThreadAction => ({
  kind: 'event',
  id,
  event: value,
})

const ask = (id = 'r1', text = 'who objected?') => ({
  kind: 'ask' as const,
  id,
  text,
  scenarioKey: null as string | null,
})

function fold(actions: ThreadAction[], state = initialThreadState): ThreadState {
  return actions.reduce((current, action) => reduceThread(current, action), state)
}

describe('reduceThread', () => {
  it('starts empty with no running run', () => {
    expect(initialThreadState.entries).toEqual([])
    expect(initialThreadState.runningId).toBeNull()
    expect(initialThreadState.totals).toEqual({ totalCalls: 0, totalCostUsd: 0 })
  })

  it('appends a user message and a run entry on ask', () => {
    const state = reduceThread(initialThreadState, ask())
    expect(state.entries).toHaveLength(2)
    expect(state.entries[0]).toMatchObject({ kind: 'user', text: 'who objected?' })
    expect(state.entries[1]).toMatchObject({ kind: 'run', id: 'r1' })
    expect(state.runningId).toBe('r1')
    // The run entry is a reset fold: running with the question recorded.
    const run = state.entries[1].kind === 'run' ? state.entries[1].state : null
    expect(run?.running).toBe(true)
    expect(run?.question).toBe('who objected?')
  })

  it('ignores a second ask while a run is in flight', () => {
    const state = fold([ask(), ask('r2', 'second?')])
    expect(state.runningId).toBe('r1')
    expect(state.entries).toHaveLength(2)
  })

  it('folds stream events into the matching run entry', () => {
    const state = fold([
      ask(),
      event({
        type: 'TEXT_MESSAGE_CONTENT',
        message_id: 'answer',
        delta: 'They chose object safety.',
        chips: [{ id: 'rfc:255', label: 'Decision', title: 'Object safety' }],
        cited: true,
      }),
    ])
    const run = state.entries[1].kind === 'run' ? state.entries[1].state : null
    expect(run?.sentences).toHaveLength(1)
    expect(run?.sentences[0]?.chips[0]?.id).toBe('rfc:255')
    expect(hasRun(run!)).toBe(true)
  })

  it('ignores events for unknown runs', () => {
    const state = reduceThread(initialThreadState, event({ type: 'FAITHFULNESS_PENDING' }, 'ghost'))
    expect(state.entries).toEqual([])
  })

  it('tracks deploy-wide totals from ledger events', () => {
    const state = fold([
      ask(),
      event({ type: 'LEDGER_UPDATE', ledger: LEDGER }),
    ])
    expect(state.totals).toEqual({ totalCalls: 5, totalCostUsd: 0.0031 })
  })

  it('clears runningId on RUN_FINISHED but keeps the run in the thread', () => {
    const state = fold([
      ask(),
      event({ type: 'LEDGER_UPDATE', ledger: LEDGER }),
      event({
        type: 'RUN_FINISHED',
        citation_count: 1,
        claims_total: 1,
        claims_cited: 1,
        abstention_required: false,
        ledger: LEDGER,
      }),
    ])
    expect(state.runningId).toBeNull()
    expect(state.entries[1].kind === 'run' && state.entries[1].state.finished).toBe(true)
  })

  it('keeps a finished run receiving its faithfulness score', () => {
    const state = fold([
      ask(),
      event({
        type: 'RUN_FINISHED',
        citation_count: 1,
        claims_total: 1,
        claims_cited: 1,
        abstention_required: false,
        ledger: LEDGER,
      }),
      { kind: 'faithfulness', id: 'r1', report: null, message: 'scoring offline' },
    ])
    const run = state.entries[1].kind === 'run' ? state.entries[1].state : null
    expect(run?.faithfulnessError).toBe('scoring offline')
  })

  it('records a run error and releases the composer', () => {
    const state = fold([ask(), { kind: 'runError', id: 'r1', message: 'POST /ask failed (500)' }])
    expect(state.runningId).toBeNull()
    const run = state.entries[1].kind === 'run' ? state.entries[1].state : null
    expect(run?.error).toBe('POST /ask failed (500)')
  })

  it('a second ask after a finished run appends a new message pair', () => {
    const state = fold([
      ask(),
      event({
        type: 'RUN_FINISHED',
        citation_count: 0,
        claims_total: 0,
        claims_cited: 0,
        abstention_required: true,
        ledger: LEDGER,
      }),
      ask('r2', 'prove a negative'),
      { kind: 'ask', id: 'r2-done-check', text: 'ignored', scenarioKey: null },
    ])
    expect(state.entries).toHaveLength(4)
    expect(state.runningId).toBe('r2')
  })

  it('discard resets the whole conversation', () => {
    const state = fold([
      ask(),
      event({
        type: 'RUN_FINISHED',
        citation_count: 0,
        claims_total: 0,
        claims_cited: 0,
        abstention_required: true,
        ledger: LEDGER,
      }),
      { kind: 'discard' },
    ])
    expect(state).toEqual(initialThreadState)
  })

  it('activeEntry finds the in-flight run', () => {
    const state = fold([ask()])
    expect(activeEntry(state)?.id).toBe('r1')
    const finished = reduceThread(state, event({
      type: 'RUN_FINISHED',
      citation_count: 0,
      claims_total: 0,
      claims_cited: 0,
      abstention_required: true,
      ledger: LEDGER,
    }))
    expect(activeEntry(finished)).toBeNull()
  })

  it('scripted asks record the scenario key on the user message and run', () => {
    const state = reduceThread(initialThreadState, {
      kind: 'ask',
      id: 'r1',
      text: 'Prove the negative',
      scenarioKey: 'prove_negative',
    })
    expect(state.entries[0]).toMatchObject({ kind: 'user', scenarioKey: 'prove_negative' })
    const run = state.entries[1].kind === 'run' ? state.entries[1].state : null
    expect(run?.scenario).toBe('prove_negative')
  })
})
