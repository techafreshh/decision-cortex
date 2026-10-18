import { motion } from 'framer-motion'

import type { RunState } from '../../state/runStore'
import { AnswerCard } from '../AnswerCard'
import { CypherPeek } from '../CypherPeek'
import { FaithfulnessBadge } from '../FaithfulnessBadge'
import { NoRecordCard } from '../NoRecordCard'
import { ShowYourWork } from '../ShowYourWork'
import { MessageLedger } from './MessageLedger'
import { Thinking } from './Thinking'

export interface AssistantMessageProps {
  state: RunState
}

/**
 * One answer as a chat message: the thinking loader while the plan computes,
 * then the sentence-by-sentence answer with its chips, the NoRecordCard when
 * the run abstains, the async faithfulness badge, and the collapsible
 * evidence strip (CypherPeek, tool-call trace, run ledger). Reuses the same
 * components the single-run view rendered — the thread is a re-shell, not a
 * second rendering contract.
 */
export function AssistantMessage({ state }: AssistantMessageProps) {
  const answered = state.sentences.length > 0
  const started = answered || state.abstention !== null || state.finished
  return (
    <motion.article
      className="msg msg--assistant"
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: 'spring', stiffness: 320, damping: 30 }}
    >
      <div className="msg__rail" aria-hidden="true">
        <svg viewBox="0 0 16 16" width="13" height="13" fill="currentColor">
          <path d="M8 0l2.2 5.8L16 8l-5.8 2.2L8 16l-2.2-5.8L0 8l5.8-2.2L8 0z" />
        </svg>
      </div>
      <div className="msg__main">
        {state.error === null ? null : (
          <p className="error">Run failed: {state.error}</p>
        )}
        {state.running && !started ? <Thinking traces={state.traces} /> : null}
        <AnswerCard question="" sentences={state.sentences} />
        {state.abstention === null ? null : (
          <NoRecordCard question={state.question} receipt={state.abstention} />
        )}
        {state.faithfulnessPending ? (
          <div className="msg__badges">
            <FaithfulnessBadge
              pending={state.faithfulnessPending}
              report={state.faithfulness}
              error={state.faithfulnessError}
              hasSentences={answered}
            />
          </div>
        ) : null}
        {state.ledger === null ? null : <MessageLedger ledger={state.ledger} />}
        <CypherPeek queries={state.queries} />
        <ShowYourWork traces={state.traces} />
      </div>
    </motion.article>
  )
}
