import type { Sentence } from '../state/runStore'
import { CitationChip } from './CitationChip'
import { Badge } from './kit/Badge'
import { Card } from './kit/Card'

export interface AnswerCardProps {
  question: string
  sentences: Sentence[]
}

/** The answer, built sentence by sentence; each sentence carries its chips. */
export function AnswerCard({ question, sentences }: AnswerCardProps) {
  if (sentences.length === 0) return null
  return (
    <Card title="Answer">
      <p className="answer__question">{question}</p>
      <ol className="answer__sentences">
        {sentences.map((sentence, index) => (
          <li
            key={index}
            className={`sentence${sentence.cited ? '' : ' sentence--uncited'}`}
          >
            <span className="sentence__text">{sentence.text}</span>
            {sentence.cited ? null : <Badge tone="warn">uncited</Badge>}
            {sentence.chips.length === 0 ? null : (
              <span className="sentence__chips">
                {sentence.chips.map((chip) => (
                  <CitationChip key={chip.id} chip={chip} />
                ))}
              </span>
            )}
          </li>
        ))}
      </ol>
    </Card>
  )
}
