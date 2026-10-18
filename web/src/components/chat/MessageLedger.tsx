import { useState } from 'react'

import type { LedgerSummary } from '../../api/types'

export interface MessageLedgerProps {
  ledger: LedgerSummary
  /** Initial expansion; rows stay hidden until toggled open by default. */
  defaultOpen?: boolean
}

/**
 * The ledger, scoped to one run: the System-1 economics for this answer, with
 * the locked seven-field rows one toggle away. Deploy-wide totals live in the
 * header chip; these rows are the "show your work" evidence for this message.
 */
export function MessageLedger({ ledger, defaultOpen = false }: MessageLedgerProps) {
  const [open, setOpen] = useState(defaultOpen)
  if (ledger.records.length === 0 && ledger.calls === 0) return null
  return (
    <section className="mledger">
      <button
        type="button"
        className="mledger__toggle"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="mledger__caret">{open ? '▾' : '▸'}</span>
        ledger — {ledger.calls} {ledger.calls === 1 ? 'decision' : 'decisions'} ·{' '}
        <strong>${ledger.cost_usd.toFixed(4)}</strong>
      </button>
      {open && ledger.records.length > 0 ? (
        <table className="ledger__table">
          <thead>
            <tr>
              <th>model</th>
              <th>choice</th>
              <th>conf</th>
              <th>latency</th>
              <th>cost</th>
              <th>tier</th>
            </tr>
          </thead>
          <tbody>
            {ledger.records.map((record, index) => (
              <tr key={index}>
                <td>
                  <code>{record.model}</code>
                </td>
                <td>{String(record.choice)}</td>
                <td>
                  {record.confidence === null
                    ? '—'
                    : record.confidence.toFixed(2)}
                </td>
                <td>{record.latency_ms} ms</td>
                <td>${record.cost_usd.toFixed(5)}</td>
                <td>{record.escalated ? 'S2' : 'S1'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </section>
  )
}
