import type { ReactNode } from 'react'

export type BadgeTone = 'plain' | 'good' | 'warn' | 'bad' | 'muted'

export function Badge({
  tone = 'plain',
  children,
}: {
  tone?: BadgeTone
  children: ReactNode
}) {
  return <span className={`badge badge--${tone}`}>{children}</span>
}
