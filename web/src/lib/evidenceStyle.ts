/**
 * The one place edge and stance kinds get a human label and a colour.
 *
 * The graph carries a fixed relation vocabulary (`api/impact.py`
 * `IMPACT_RELATIONS`, `ingest/ontology.py`). The Impact Explorer and the
 * Timeline both render those relations, so the mapping lives here rather than
 * drifting between the two views. An unknown kind degrades to its own
 * lower-cased name in the neutral accent colour instead of disappearing.
 */

import type { BadgeTone } from '../components/kit/Badge'

export interface EvidenceStyle {
  label: string
  tone: BadgeTone
  color: string
}

const STYLES: Record<string, EvidenceStyle> = {
  ABOUT: { label: 'about', tone: 'plain', color: 'var(--accent)' },
  RELATES: { label: 'relates to', tone: 'plain', color: 'var(--accent)' },
  AREA: { label: 'area', tone: 'muted', color: 'var(--muted)' },
  ASSOCIATED_TEAM: { label: 'team', tone: 'muted', color: 'var(--muted)' },
  PROPOSED_BY: { label: 'proposed by', tone: 'muted', color: 'var(--muted)' },
  SUPERSEDES: { label: 'supersedes', tone: 'warn', color: 'var(--warn)' },
  OBJECTED: { label: 'objected', tone: 'bad', color: 'var(--bad)' },
  SUPPORTED: { label: 'supported', tone: 'good', color: 'var(--good)' },
  MODERATED: { label: 'moderated', tone: 'warn', color: 'var(--warn)' },
}

export function evidenceStyle(kind: string): EvidenceStyle {
  return (
    STYLES[kind] ?? { label: kind.toLowerCase(), tone: 'plain', color: 'var(--accent)' }
  )
}
