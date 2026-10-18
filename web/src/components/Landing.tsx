import { SCENARIOS, type AskRequest } from '../api/ask'

export interface LandingProps {
  onAsk: (request: AskRequest, text: string) => void
  disabled: boolean
}

/**
 * The empty-thread hero. The four scripted scenarios come first (AGENTS.md
 * demo beats: scripted buttons before free chat — same labels, same cache
 * underneath); the free-chat box is the composer below them.
 */
export function Landing({ onAsk, disabled }: LandingProps) {
  return (
    <section className="landing">
      <p className="landing__kicker">
        <code>rust-lang/rfcs</code> · 2,309 decisions · 21k debate comments
      </p>
      <h1 className="landing__title">
        600 decisions, 30k debate comments, one question box.
      </h1>
      <p className="landing__sub">
        Ask the real <code>rust-lang/rfcs</code> corpus. Every claim cites its
        source; the pipeline abstains rather than guess.
      </p>
      <div className="landing__scenarios">
        {SCENARIOS.map((scenario) => (
          <button
            key={scenario.key}
            type="button"
            className="chip chip--suggest chip--suggest-lg"
            disabled={disabled}
            onClick={() => onAsk({ scenario: scenario.key }, scenario.label)}
          >
            <span className="chip__label">{scenario.label}</span>
          </button>
        ))}
      </div>
      <p className="landing__hint">…or ask anything below. Free chat is second; sources always first.</p>
    </section>
  )
}
