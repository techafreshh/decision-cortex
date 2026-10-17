import type { ReactNode } from 'react'

export type CardTone = 'plain' | 'warn' | 'good' | 'muted'

export interface CardProps {
  title?: ReactNode
  tone?: CardTone
  className?: string
  children: ReactNode
}

export function Card({ title, tone = 'plain', className, children }: CardProps) {
  const classes = ['card', `card--${tone}`, className].filter(Boolean).join(' ')
  return (
    <section className={classes}>
      {title === undefined ? null : <h3 className="card__title">{title}</h3>}
      <div className="card__body">{children}</div>
    </section>
  )
}
