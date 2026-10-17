import { useState } from 'react'

import { AnswerCard } from './components/AnswerCard'
import { CypherPeek } from './components/CypherPeek'
import { FaithfulnessBadge } from './components/FaithfulnessBadge'
import { ImpactView } from './components/ImpactView'
import { Landing } from './components/Landing'
import { LedgerFooter } from './components/LedgerFooter'
import { NoRecordCard } from './components/NoRecordCard'
import { OpenNodeProvider, SourcePanel } from './components/SourcePanel'
import { ShowYourWork } from './components/ShowYourWork'
import { TimelinePanel } from './components/TimelineView'
import { Button } from './components/kit/Button'
import { useAskStream, type UseAskStream } from './hooks/useAskStream'
import { hasRun } from './state/runStore'

type View = 'ask' | 'impact' | 'timeline'

const VIEWS: { key: View; label: string }[] = [
  { key: 'ask', label: 'Ask' },
  { key: 'impact', label: 'Impact' },
  { key: 'timeline', label: 'Timeline' },
]

function App() {
  const { state, ask, clear } = useAskStream()
  const [openNodeId, setOpenNodeId] = useState<string | null>(null)
  const [view, setView] = useState<View>('ask')
  const showRun = hasRun(state)

  return (
    <OpenNodeProvider value={setOpenNodeId}>
      <div className="app">
        <header className="app__head">
          <span className="app__brand">Decision Cortex</span>
          <span className="app__tag">a company brain over rust-lang/rfcs</span>
          <nav className="app__nav" aria-label="Views">
            {VIEWS.map((entry) => (
              <Button
                key={entry.key}
                variant={view === entry.key ? 'primary' : 'ghost'}
                onClick={() => setView(entry.key)}
              >
                {entry.label}
              </Button>
            ))}
          </nav>
        </header>

        {view === 'ask' ? (
          <AskView state={state} ask={ask} clear={clear} showRun={showRun} />
        ) : null}

        {view === 'impact' ? (
          <main className="app__main">
            <ImpactView />
          </main>
        ) : null}

        {view === 'timeline' ? (
          <main className="app__main">
            <TimelinePanel />
          </main>
        ) : null}

        <SourcePanel nodeId={openNodeId} onClose={() => setOpenNodeId(null)} />
      </div>
    </OpenNodeProvider>
  )
}

function AskView({
  state,
  ask,
  clear,
  showRun,
}: Pick<UseAskStream, 'state' | 'ask' | 'clear'> & { showRun: boolean }) {
  if (!showRun) {
    return <Landing onAsk={ask} disabled={state.running} />
  }

  return (
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
        <NoRecordCard question={state.question} receipt={state.abstention} />
      )}

      {state.faithfulnessPending ? <FaithfulnessBadge /> : null}

      <CypherPeek queries={state.queries} />

      <ShowYourWork traces={state.traces} />

      {state.ledger === null ? null : <LedgerFooter ledger={state.ledger} />}
    </main>
  )
}

export default App
