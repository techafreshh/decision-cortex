import { useEffect, useState, type FormEvent, type KeyboardEvent } from 'react'

import { SCENARIOS, type AskRequest } from '../api/ask'
import { formatElapsed } from './chat/Thinking'

export interface ComposerProps {
  onAsk: (request: AskRequest, text: string) => void
  disabled: boolean
  /** Scenario chips inside the composer; hidden on the hero (it has its own). */
  chips?: boolean
}

/**
 * The chat composer: the four scripted scenario buttons (AGENTS.md demo beats:
 * scripted buttons first, free chat second — the labels are the demo script's,
 * never changed here) and the free-question textarea. Enter sends,
 * Shift+Enter breaks a line. While a run streams, everything disables and the
 * send button shows the honest elapsed time.
 */
export function Composer({ onAsk, disabled, chips = true }: ComposerProps) {
  const [draft, setDraft] = useState('')
  const [seconds, setSeconds] = useState(0)

  useEffect(() => {
    if (!disabled) {
      setSeconds(0)
      return
    }
    const timer = window.setInterval(() => setSeconds((value) => value + 1), 1000)
    return () => window.clearInterval(timer)
  }, [disabled])

  const submit = (event?: FormEvent) => {
    event?.preventDefault()
    const trimmed = draft.trim()
    if (trimmed === '' || disabled) return
    onAsk({ question: trimmed }, trimmed)
    setDraft('')
  }

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      submit()
    }
  }

  const autoresize = (element: HTMLTextAreaElement | null) => {
    if (element === null) return
    element.style.height = 'auto'
    element.style.height = `${Math.min(element.scrollHeight, 160)}px`
  }

  return (
    <form className="composer" onSubmit={submit} aria-label="Ask the corpus">
      {chips ? (
        <div className="composer__chips">
          {SCENARIOS.map((scenario) => (
            <button
              key={scenario.key}
              type="button"
              className="chip chip--suggest"
              disabled={disabled}
              onClick={() => onAsk({ scenario: scenario.key }, scenario.label)}
            >
              <span className="chip__label">{scenario.label}</span>
            </button>
          ))}
        </div>
      ) : null}
      <div className="composer__row">
        <textarea
          className="composer__input"
          value={draft}
          rows={1}
          ref={autoresize}
          placeholder={
            disabled ? 'Decision Cortex is answering…' : 'Ask the corpus…'
          }
          aria-label="Ask the corpus"
          disabled={disabled}
          onChange={(event) => {
            setDraft(event.target.value)
            autoresize(event.target)
          }}
          onKeyDown={onKeyDown}
        />
        <button
          type="submit"
          className="composer__send"
          disabled={disabled || draft.trim() === ''}
        >
          {disabled ? (
            <>
              <span className="composer__spinner" aria-hidden="true" />
              {formatElapsed(seconds)}
            </>
          ) : (
            <>
              <span aria-hidden="true">↑</span>
              <span className="sr-only">Ask</span>
            </>
          )}
        </button>
      </div>
    </form>
  )
}
