import type { LedgerSummary } from '../api/types'
import { Badge } from './kit/Badge'

/**
 * The decision-ledger footer: the System-1 routing economics made live. Totals
 * for the run and the deploy, plus one row per ledgered call.
 */
export function LedgerFooter({ ledger }: { ledger: LedgerSummary }) {
  return (
    <footer className="ledger">
      <div className="ledger__totals">
        <span className="ledger__total">
          this run: <strong>{ledger.calls}</strong> decisions ·{' '}
          <strong>${ledger.cost_usd.toFixed(4)}</strong>
        </span>
        <span className="ledger__total ledger__total--deploy">
          deploy total: <strong>{ledger.total_calls}</strong> decisions ·{' '}
          <strong>${ledger.total_cost_usd.toFixed(4)}</strong>
        </span>
      </div>
      {ledger.records.length === 0 ? null : (
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
                <td>{record.escalated ? <Badge tone="warn">S2</Badge> : 'S1'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </footer>
  )
}
