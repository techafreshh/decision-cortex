import { useState, type FormEvent } from 'react'

import { SCENARIOS, type AskRequest } from '../api/ask'
import { Button } from './kit/Button'

export interface LandingProps {
  onAsk: (request: AskRequest) => void
  disabled: boolean
}

/**
 * The landing view. The four scripted scenarios come first (AGENTS.md demo
 * beats: scripted buttons before free chat), then the free-chat box.
 */
export function Landing({ onAsk, disabled }: LandingProps) {
  const [question, setQuestion] = useState('')

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const trimmed = question.trim()
    if (trimmed === '') return
    onAsk({ question: trimmed })
  }

  return (
    <section className="landing">
      <h1 className="landing__title">
        600 decisions, 30k debate comments, one question box.
      </h1>
      <p className="landing__sub">
        Ask the real <code>rust-lang/rfcs</code> corpus. Every claim cites its
        source; the pipeline abstains rather than guess.
      </p>
      <div className="landing__scenarios">
        {SCENARIOS.map((scenario) => (
          <Button
            key={scenario.key}
            variant="primary"
            disabled={disabled}
            onClick={() => onAsk({ scenario: scenario.key })}
          >
            {scenario.label}
          </Button>
        ))}
      </div>
      <form className="landing__form" onSubmit={submit}>
        <input
          className="landing__input"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Ask the corpus…"
          aria-label="Ask the corpus"
        />
        <Button
          type="submit"
          variant="ghost"
          disabled={disabled || question.trim() === ''}
        >
          Ask
        </Button>
      </form>
    </section>
  )
}
