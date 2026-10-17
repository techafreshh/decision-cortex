import type { CitationChip as Chip } from '../api/types'
import { useOpenNode } from './SourcePanel'

/** A citation chip: the id, label, and title; clicking opens the source panel. */
export function CitationChip({ chip }: { chip: Chip }) {
  const openNode = useOpenNode()
  return (
    <button
      type="button"
      className="chip"
      title={chip.title}
      onClick={() => openNode(chip.id)}
    >
      <span className="chip__label">{chip.label}</span>
      <span className="chip__id">{chip.id}</span>
    </button>
  )
}
