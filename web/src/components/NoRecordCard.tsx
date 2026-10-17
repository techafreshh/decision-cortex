import type { AbstentionReceipt } from '../api/types'
import { CitationChip } from './CitationChip'
import { Card } from './kit/Card'

export interface NoRecordCardProps {
  question: string
  receipt: AbstentionReceipt
}

/**
 * The negative-proof moment: the pipeline found no decision answering the
 * question and shows its search receipts instead of confabulating — how many
 * nodes it searched, how many evidence chains it walked, and the real proposals
 * that came close.
 */
export function NoRecordCard({ question, receipt }: NoRecordCardProps) {
  return (
    <Card tone="warn" title="No record">
      <p className="norecord__question">{question}</p>
      <p className="norecord__verdict">
        Decision Cortex found no decision answering this, so it abstains rather
        than confabulate. Here are the receipts.
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
