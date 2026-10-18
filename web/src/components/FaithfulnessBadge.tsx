import { Badge } from './kit/Badge'
import type { FaithfulnessReport } from '../api/types'

export interface FaithfulnessBadgeProps {
  /** `FAITHFULNESS_PENDING` arrived: scoring applies to this run. */
  pending: boolean
  /** The landed HHEM report, or `null` while scoring (or after a failure). */
  report: FaithfulnessReport | null
  /** Why scoring failed, when it did — shown instead of a number. */
  error: string | null
  /** Whether the run produced answer sentences (an abstention has none to score). */
  hasSentences: boolean
}

/**
 * The faithfulness badge is async by design (PRD §7.2): scoring runs
 * out-of-band with the local HHEM cross-encoder and never blocks the answer
 * stream, so the badge shows the pending state first and the real numbers
 * when `POST /faithfulness` lands. An abstention run has no claims to score —
 * it renders an honest "n/a" instead of a placeholder that would never resolve.
 */
export function FaithfulnessBadge({
  pending,
  report,
  error,
  hasSentences,
}: FaithfulnessBadgeProps) {
  if (!pending) return null
  if (report !== null) {
    const value =
      report.faithfulness === null ? null : report.faithfulness.toFixed(2)
    return (
      <span className="faithfulness">
        <Badge tone={value === '1.00' ? 'good' : 'plain'}>
          faithfulness {value ?? 'n/a'} · {report.claims_supported}/
          {report.claims_total} claims supported
        </Badge>
        <Badge tone="muted">{report.claims_scored} scored (HHEM)</Badge>
      </span>
    )
  }
  if (!hasSentences) {
    return (
      <span className="faithfulness">
        <Badge tone="muted">faithfulness: n/a · abstention</Badge>
      </span>
    )
  }
  if (error !== null) {
    return (
      <span className="faithfulness">
        <Badge tone="warn">faithfulness unavailable</Badge>
      </span>
    )
  }
  return (
    <span className="faithfulness">
      <Badge tone="muted">faithfulness: scoring…</Badge>
    </span>
  )
}
