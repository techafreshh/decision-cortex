import { useState } from 'react'

/**
 * CypherPeek: the Cypher retrieval actually ran. A display flourish, never the
 * retrieval backbone — collapsed by default, one click to flash the queries.
 */
export function CypherPeek({ queries }: { queries: string[] }) {
  const [open, setOpen] = useState(false)
  if (queries.length === 0) return null
  return (
    <section className="cypherpeek">
      <button
        type="button"
        className="cypherpeek__toggle"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="cypherpeek__caret">{open ? '▾' : '▸'}</span>
        CypherPeek — {queries.length} {queries.length === 1 ? 'query' : 'queries'}{' '}
        ran
      </button>
      {open ? (
        <ol className="cypherpeek__list">
          {queries.map((query, index) => (
            <li key={index}>
              <pre className="cypherpeek__query">{query}</pre>
            </li>
          ))}
        </ol>
      ) : null}
    </section>
  )
}
