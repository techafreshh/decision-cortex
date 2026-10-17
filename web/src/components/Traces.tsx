import { renderTool } from '../registry/components'
import type { TraceEntry } from '../state/runStore'

/** The tool-call trace list; each entry renders via the generative-UI registry. */
export function Traces({ traces }: { traces: TraceEntry[] }) {
  return (
    <div className="traces">
      {traces.map((trace, index) => (
        <div className="traces__row" key={`${trace.toolName}-${index}`}>
          <div className="traces__head">
            <code className="traces__name">{trace.toolName}</code>
            <span className={`traces__status traces__status--${trace.status}`}>
              {trace.status}
            </span>
          </div>
          {renderTool(trace)}
        </div>
      ))}
    </div>
  )
}
