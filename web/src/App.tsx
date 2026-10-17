import { useState } from 'react'

import { AnswerCard } from './components/AnswerCard'
import { CypherPeek } from './components/CypherPeek'
import { FaithfulnessBadge } from './components/FaithfulnessBadge'
import { Landing } from './components/Landing'
import { LedgerFooter } from './components/LedgerFooter'
import { NoRecordCard } from './components/NoRecordCard'
import { OpenNodeProvider, SourcePanel } from './components/SourcePanel'
import { ShowYourWork } from './components/ShowYourWork'
import { Button } from './components/kit/Button'
import { useAskStream } from './hooks/useAskStream'
import { hasRun } from './state/runStore'

function App() {
  const { state, ask, clear } = useAskStream()
  const [openNodeId, setOpenNodeId] = useState<string | null>(null)
  const showRun = hasRun(state)

  return (
    <OpenNodeProvider value={setOpenNodeId}>
      <div className="app">
        <header className="app__head">
          <span className="app__brand">Decision Cortex</span>
          <span className="app__tag">a company brain over rust-lang/rfcs</span>
        </header>

        {showRun ? null : <Landing onAsk={ask} disabled={state.running} />}

        {showRun ? (
          <main className="app__main">
            <div className="app__question">
              <p className="app__questionText">{state.question}</p>
              <Button variant="ghost" onClick={clear}>
                New question
              </Button>
            </div>

            {state.error === null ? null : (
              <p className="error">Run failed: {state.error}</p>
            )}

            {state.running ? <p className="muted">Retrieving…</p> : null}

            <AnswerCard question={state.question} sentences={state.sentences} />

            {state.abstention === null ? null : (
              <NoRecordCard
                question={state.question}
                receipt={state.abstention}
              />
            )}

            {state.faithfulnessPending ? <FaithfulnessBadge /> : null}

            <CypherPeek queries={state.queries} />

            <ShowYourWork traces={state.traces} />

            {state.ledger === null ? null : (
              <LedgerFooter ledger={state.ledger} />
            )}
          </main>
        ) : null}

        <SourcePanel nodeId={openNodeId} onClose={() => setOpenNodeId(null)} />
      </div>
    </OpenNodeProvider>
  )
}

export default App
