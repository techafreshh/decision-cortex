import { describe, expect, it } from 'vitest'

import type {
  AbstentionReceipt,
  AskEvent,
  FaithfulnessReport,
  LedgerSummary,
} from '../api/types'
import {
  hasRun,
  initialRunState,
  reduceRun,
  type RunAction,
  type RunState,
} from '../state/runStore'

const event = (value: AskEvent): RunAction => ({ kind: 'event', event: value })

function fold(actions: RunAction[]) {
  return actions.reduce(reduceRun, initialRunState)
}

const LEDGER: LedgerSummary = {
  calls: 1,
  cost_usd: 0.0004,
  total_calls: 7,
  total_cost_usd: 0.0031,
  records: [
    {
      input_digest: 'abc',
      choice: 'graph',
      confidence: 0.91,
      model: 'small',
      latency_ms: 120,
      cost_usd: 0.0004,
      escalated: false,
    },
  ],
}

describe('reduceRun', () => {
  it('starts empty and idle', () => {
    expect(initialRunState.running).toBe(false)
    expect(initialRunState.traces).toEqual([])
    expect(initialRunState.sentences).toEqual([])
    expect(initialRunState.abstention).toBeNull()
  })

  it('reset marks the run in flight and records the question', () => {
    const state = reduceRun(initialRunState, {
      kind: 'reset',
      request: { question: 'who objected?' },
    })
    expect(state.running).toBe(true)
    expect(state.question).toBe('who objected?')
    expect(state.scenario).toBeNull()
  })

  it('records a scripted scenario on reset', () => {
    const state = reduceRun(initialRunState, {
      kind: 'reset',
      request: { scenario: 'prove_negative' },
    })
    expect(state.scenario).toBe('prove_negative')
    expect(state.question).toBe('')
  })

  it('builds a trace from start/args/result', () => {
    const state = fold([
      event({ type: 'TOOL_CALL_START', tool_call_id: 'router_classify', tool_name: 'router_classify' }),
      event({ type: 'TOOL_CALL_ARGS', tool_call_id: 'router_classify', delta: '{"route":"graph"}' }),
      event({
        type: 'TOOL_CALL_RESULT',
        tool_call_id: 'router_classify',
        result: { route: 'graph', confidence: 0.9, escalated: false },
      }),
    ])
    expect(state.traces).toEqual([
      {
        toolName: 'router_classify',
        status: 'done',
        args: '{"route":"graph"}',
        result: { route: 'graph', confidence: 0.9, escalated: false },
      },
    ])
  })

  it('captures the abstention receipt from record_abstention', () => {
    const receipt: AbstentionReceipt = {
      nodes_searched: 42,
      evidence_chains: 6,
      matches: 0,
      came_close: [{ id: 'rfc:123', label: 'Decision', title: 'unsafe attachments' }],
    }
    const state = fold([
      event({ type: 'TOOL_CALL_START', tool_call_id: 'record_abstention', tool_name: 'record_abstention' }),
      event({ type: 'TOOL_CALL_RESULT', tool_call_id: 'record_abstention', result: receipt }),
    ])
    expect(state.abstention).toEqual(receipt)
  })

  it('leaves abstention null when no card is emitted (cardless ungrounded)', () => {
    const state = fold([
      event({ type: 'RUN_STARTED', question: 'q', scenario: null }),
      event({
        type: 'TOOL_CALL_START',
        tool_call_id: 'router_classify',
        tool_name: 'router_classify',
      }),
      event({
        type: 'TOOL_CALL_RESULT',
        tool_call_id: 'router_classify',
        result: { route: 'out_of_graph', confidence: 0.8, escalated: false },
      }),
      event({ type: 'RUN_FINISHED', citation_count: 0, claims_total: 0, claims_cited: 0, abstention_required: false, ledger: LEDGER }),
    ])
    expect(state.abstention).toBeNull()
    expect(state.sentences).toEqual([])
  })

  it('accumulates answer sentences in order', () => {
    const state = fold([
      event({ type: 'TEXT_MESSAGE_START', message_id: 'answer' }),
      event({
        type: 'TEXT_MESSAGE_CONTENT',
        message_id: 'answer',
        delta: 'Rust decided X.',
        chips: [{ id: 'rfc:1', label: 'Decision', title: 'X' }],
        cited: true,
      }),
      event({
        type: 'TEXT_MESSAGE_CONTENT',
        message_id: 'answer',
        delta: 'Someone objected.',
        chips: [],
        cited: false,
      }),
    ])
    expect(state.sentences).toEqual([
      {
        text: 'Rust decided X.',
        chips: [{ id: 'rfc:1', label: 'Decision', title: 'X' }],
        cited: true,
      },
      { text: 'Someone objected.', chips: [], cited: false },
    ])
  })

  it('records the Cypher retrieval ran', () => {
    const state = fold([
      event({ type: 'CYPHER_PREVIEW', queries: ['MATCH (n) RETURN n'] }),
    ])
    expect(state.queries).toEqual(['MATCH (n) RETURN n'])
  })

  it('flags faithfulness scoring and lands the ledger on finish', () => {
    const state = fold([
      event({ type: 'FAITHFULNESS_PENDING' }),
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
    expect(state.faithfulnessPending).toBe(true)
    expect(state.finished).toBe(true)
    expect(state.running).toBe(false)
    expect(state.ledger).toEqual(LEDGER)
  })

  it('records an error and stops the run', () => {
    const running = reduceRun(initialRunState, {
      kind: 'reset',
      request: { question: 'q' },
    })
    const state = reduceRun(running, { kind: 'error', message: 'boom' })
    expect(state.running).toBe(false)
    expect(state.error).toBe('boom')
  })

  it('lands the faithfulness report without touching run lifecycle fields', () => {
    const report: FaithfulnessReport = {
      faithfulness: 0.8571,
      claims_total: 7,
      claims_supported: 6,
      claims_scored: 6,
      claims_unresolved: 1,
      threshold: 0.5,
      model: 'faithfulness:hhem-2.1-open',
      latency_ms: 4200,
      claims: [],
    }
    const finished = fold([
      event({ type: 'FAITHFULNESS_PENDING' }),
      event({
        type: 'RUN_FINISHED',
        citation_count: 2,
        claims_total: 7,
        claims_cited: 6,
        abstention_required: false,
        ledger: LEDGER,
      }),
    ])
    const state = reduceRun(finished, {
      kind: 'faithfulness',
      report,
      message: null,
    })
    expect(state.faithfulness).toEqual(report)
    expect(state.faithfulnessError).toBeNull()
    expect(state.finished).toBe(true)
    expect(state.running).toBe(false)

    const failed = reduceRun(finished, {
      kind: 'faithfulness',
      report: null,
      message: 'POST /faithfulness failed (503): install the extra',
    })
    expect(failed.faithfulness).toBeNull()
    expect(failed.faithfulnessError).toContain('503')
  })

  it('shows the run view once a failure lands, so the error can render', () => {
    const failed: RunState = { ...initialRunState, error: 'boom' }

    expect(hasRun(failed)).toBe(true)
    expect(hasRun(initialRunState)).toBe(false)
  })

  it('clear returns to the idle state', () => {
    const state = reduceRun(
      reduceRun(initialRunState, { kind: 'reset', request: { question: 'q' } }),
      { kind: 'clear' },
    )
    expect(state).toEqual(initialRunState)
  })
})
