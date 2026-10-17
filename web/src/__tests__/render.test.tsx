/**
 * Render smoke tests (no browser available in CI).
 *
 * `react-dom/server` renders the component tree to static markup in Node, so
 * these catch the failure mode a browser check would: a component that throws
 * or drops required text on render. They assert the demo-critical surfaces —
 * the scripted buttons, the cited answer with chips, the NoRecordCard receipts,
 * and the ledger footer.
 */

import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { AnswerCard } from '../components/AnswerCard'
import { CypherPeek } from '../components/CypherPeek'
import { Landing } from '../components/Landing'
import { LedgerFooter } from '../components/LedgerFooter'
import { NoRecordCard } from '../components/NoRecordCard'
import { OpenNodeProvider } from '../components/SourcePanel'
import { ShowYourWork } from '../components/ShowYourWork'
import type { LedgerSummary } from '../api/types'

const noop = () => {}

function render(node: React.ReactElement): string {
  return renderToStaticMarkup(<OpenNodeProvider value={noop}>{node}</OpenNodeProvider>)
}

describe('render smoke', () => {
  it('renders the landing with scripted scenarios before free chat', () => {
    const html = render(<Landing onAsk={noop} disabled={false} />)
    for (const label of [
      'Ask the corpus',
      'Prove the negative',
      'Impact tour',
      'The async/await story',
    ]) {
      expect(html).toContain(label)
    }
    expect(html.indexOf('Ask the corpus')).toBeLessThan(
      html.indexOf('landing__form'),
    )
  })

  it('renders a cited answer with clickable chips', () => {
    const html = render(
      <AnswerCard
        question="What did the language team decide?"
        sentences={[
          {
            text: 'They chose trait objects.',
            cited: true,
            chips: [{ id: 'rfc:200', label: 'Decision', title: 'Trait objects' }],
          },
        ]}
      />,
    )
    expect(html).toContain('They chose trait objects.')
    expect(html).toContain('class="chip"')
    expect(html).toContain('rfc:200')
    expect(html).not.toContain('uncited')
  })

  it('flags an uncited sentence', () => {
    const html = render(
      <AnswerCard
        question="q"
        sentences={[{ text: 'Unsupported claim.', cited: false, chips: [] }]}
      />,
    )
    expect(html).toContain('uncited')
  })

  it('renders the NoRecordCard with receipts and came-close proposals', () => {
    const html = render(
      <NoRecordCard
        question="Did Rust require unsafe attachments?"
        receipt={{
          nodes_searched: 42,
          evidence_chains: 6,
          matches: 0,
          came_close: [
            { id: 'rfc:123', label: 'Decision', title: 'unsafe attachments' },
          ],
        }}
      />,
    )
    expect(html).toContain('No record')
    expect(html).toContain('Nodes searched')
    expect(html).toContain('>42<')
    expect(html).toContain('1 proposal came close')
    expect(html).toContain('rfc:123')
  })

  it('renders the ledger footer with run and deploy totals', () => {
    const ledger: LedgerSummary = {
      calls: 3,
      cost_usd: 0.0009,
      total_calls: 9,
      total_cost_usd: 0.0042,
      records: [
        {
          input_digest: 'a',
          choice: 'graph',
          confidence: 0.9,
          model: 'small',
          latency_ms: 120,
          cost_usd: 0.0003,
          escalated: false,
        },
      ],
    }
    const html = render(<LedgerFooter ledger={ledger} />)
    expect(html).toContain('this run')
    expect(html).toContain('deploy total')
    expect(html).toContain('$0.0009')
    expect(html).toContain('$0.0042')
    expect(html).toContain('small')
  })

  it('renders CypherPeek collapsed and ShowYourWork with its tool count', () => {
    expect(render(<CypherPeek queries={['MATCH (n) RETURN n']} />)).toContain(
      'CypherPeek — 1 query ran',
    )
    const html = render(
      <ShowYourWork
        traces={[
          { toolName: 'router_classify', status: 'done', args: '{}', result: {} },
        ]}
      />,
    )
    expect(html).toContain('Show your work — 1 tool call')
  })
})
