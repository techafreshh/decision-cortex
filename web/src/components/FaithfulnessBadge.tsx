import { Badge } from './kit/Badge'

/**
 * The faithfulness badge is async: scoring runs out-of-band on the CPU-only VPS
 * and never blocks the answer stream, so the UI shows the pending state here
 * and the score lands separately.
 */
export function FaithfulnessBadge() {
  return (
    <span className="faithfulness">
      <Badge tone="muted">faithfulness: scoring…</Badge>
    </span>
  )
}
