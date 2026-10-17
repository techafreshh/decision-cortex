import { useEffect, type ReactNode } from 'react'

import { Button } from './Button'

export interface DrawerProps {
  open: boolean
  title: ReactNode
  onClose: () => void
  children: ReactNode
}

/** A right-hand panel that closes on Escape or a scrim click. */
export function Drawer({ open, title, onClose, children }: DrawerProps) {
  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  return (
    <div
      className="drawer"
      role="dialog"
      aria-modal="true"
      aria-label={typeof title === 'string' ? title : 'Source'}
    >
      <button
        type="button"
        className="drawer__scrim"
        aria-label="Close source panel"
        onClick={onClose}
      />
      <aside className="drawer__panel">
        <header className="drawer__head">
          <h2 className="drawer__title">{title}</h2>
          <Button variant="ghost" onClick={onClose} aria-label="Close">
            ×
          </Button>
        </header>
        <div className="drawer__body">{children}</div>
      </aside>
    </div>
  )
}
