import { motion } from 'framer-motion'

import { Badge } from '../kit/Badge'

export interface UserMessageProps {
  text: string
  scenarioKey: string | null
  scriptedLabel: string | null
}

/** The question as a right-aligned chat bubble; scripted questions carry a badge. */
export function UserMessage({ text, scenarioKey, scriptedLabel }: UserMessageProps) {
  const content = text.trim()
  if (content === '') return null
  return (
    <motion.article
      className="msg msg--user"
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ type: 'spring', stiffness: 380, damping: 30 }}
    >
      <p className="msg__text">{content}</p>
      {scenarioKey !== null && scriptedLabel !== null ? (
        <Badge tone="muted">scripted · {scriptedLabel}</Badge>
      ) : null}
    </motion.article>
  )
}
