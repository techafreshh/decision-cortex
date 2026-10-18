import { useEffect, useRef, useState } from 'react'

import { SCENARIOS } from '../../api/ask'
import { activeEntry, type ThreadState } from '../../state/threadStore'
import { AssistantMessage } from './AssistantMessage'
import { UserMessage } from './UserMessage'

export interface ThreadProps {
  state: ThreadState
}

const SCENARIO_LABELS = new Map(SCENARIOS.map((entry) => [entry.key, entry.label]))

/**
 * The conversation scroll: user bubbles and assistant messages in order, with
 * a pinned-bottom autoscroll that the user can break by scrolling up (and
 * restore with a "jump to latest" pill). The thread becomes scrollable the
 * moment the first question lands; the hero only shows while it is empty.
 */
export function Thread({ state }: ThreadProps) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const [pinned, setPinned] = useState(true)

  const active = activeEntry(state)
  // A signature that changes as the live run streams (and again when the
  // post-stream card/badge phases land), so autoscroll follows the answer, the
  // trace, and the receipts — not just new messages.
  const signature = [
    state.entries.length,
    active?.state.sentences.length ?? 0,
    active?.state.traces.length ?? 0,
    active?.state.finished ?? false,
    active?.state.faithfulnessPending ?? false,
    active?.state.faithfulness !== null,
  ].join(':')

  useEffect(() => {
    const element = scrollRef.current
    if (element === null || !pinned) return
    // Instant follow while streaming: a smooth animation restarted on every
    // delta never finishes, and the thread lags mid-way through the run.
    element.scrollTo({ top: element.scrollHeight, behavior: 'auto' })
  }, [signature, pinned])

  const onScroll = () => {
    const element = scrollRef.current
    if (element === null) return
    const distance = element.scrollHeight - element.scrollTop - element.clientHeight
    setPinned(distance < 80)
  }

  const jump = () => {
    const element = scrollRef.current
    if (element === null) return
    setPinned(true)
    element.scrollTo({ top: element.scrollHeight, behavior: 'smooth' })
  }

  return (
    <div className="thread" ref={scrollRef} onScroll={onScroll}>
      <div className="thread__inner">
        {state.entries.map((entry) =>
          entry.kind === 'user' ? (
            <UserMessage
              key={entry.id}
              text={entry.text}
              scenarioKey={entry.scenarioKey}
              scriptedLabel={
                entry.scenarioKey === null
                  ? null
                  : (SCENARIO_LABELS.get(entry.scenarioKey) ?? entry.scenarioKey)
              }
            />
          ) : (
            <AssistantMessage key={entry.id} state={entry.state} />
          ),
        )}
      </div>
      {pinned ? null : (
        <button type="button" className="thread__jump" onClick={jump}>
          ↓ latest
        </button>
      )}
    </div>
  )
}
