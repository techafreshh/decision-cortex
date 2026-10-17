import type { AbstentionReceipt } from '../api/types'
import { CitationChip } from './CitationChip'
import { Card } from './kit/Card'

export interface NoRecordCardProps {
  question: string
  receipt: AbstentionReceipt
}

/**
 * The negative-proof moment. A true negative (`matches === 0`) found no decision
 * answering the question; a partial answer (`matches > 0`) grounded some claims
 * but abstained on the rest. Both show their search receipts instead of
 * confabulating — how many nodes were searched, how many evidence chains were
 * walked, and the real proposals that came close.
 */
export function NoRecordCard({ question, receipt }: NoRecordCardProps) {
  const partial = receipt.matches > 0
  return (
    <Card tone="warn" title={partial ? 'Partial answer' : 'No record'}>
      <p className="norecord__question">{question}</p>
      <p className="norecord__verdict">
        {partial
          ? `Decision Cortex could only ground ${receipt.matches} of the claims here, so it abstains on the rest rather than confabulate. Here are the receipts.`
          : 'Decision Cortex found no decision answering this, so it abstains rather than confabulate. Here are the receipts.'}
      </p>
      <dl className="receipts">
        <div className="receipts__row">
          <dt>Nodes searched</dt>
          <dd>{receipt.nodes_searched}</dd>
        </div>
        <div className="receipts__row">
          <dt>Evidence chains</dt>
          <dd>{receipt.evidence_chains}</dd>
        </div>
        <div className="receipts__row">
          <dt>Matches</dt>
          <dd>{receipt.matches}</dd>
        </div>
      </dl>
      {receipt.came_close.length === 0 ? null : (
        <>
          <h4 className="norecord__heading">
            {receipt.came_close.length}{' '}
            {receipt.came_close.length === 1 ? 'proposal came' : 'proposals came'}{' '}
            close
          </h4>
          <ul className="cameclose">
            {receipt.came_close.map((entry) => (
              <li key={entry.id}>
                <CitationChip chip={entry} />
                <span className="cameclose__title">{entry.title}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </Card>
  )
}
