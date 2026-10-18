import { useState } from 'react'

import { ImpactView } from './components/ImpactView'
import { Landing } from './components/Landing'
import { Composer } from './components/Composer'
import { TimelinePanel } from './components/TimelineView'
import { OpenNodeProvider, SourcePanel } from './components/SourcePanel'
import { Thread } from './components/chat/Thread'
import { Button } from './components/kit/Button'
import { useThread } from './hooks/useThread'
import type { AskRequest } from './api/ask'

type View = 'chat' | 'impact' | 'timeline'

const VIEWS: { key: View; label: string }[] = [
  { key: 'chat', label: 'Chat' },
  { key: 'impact', label: 'Impact' },
  { key: 'timeline', label: 'Timeline' },
]

function App() {
  const { state, ask, discard } = useThread()
  const [openNodeId, setOpenNodeId] = useState<string | null>(null)
  const [view, setView] = useState<View>('chat')

  const onAsk = (request: AskRequest, text: string) => {
    setView('chat')
    ask(request, text)
  }

  return (
    <OpenNodeProvider value={setOpenNodeId}>
      <div className="app">
        <header className="app__head">
          <div className="app__brandBlock">
            <span className="app__brand">
              <span className="app__spark" aria-hidden="true">
                <svg viewBox="0 0 16 16" width="15" height="15" fill="currentColor">
                  <path d="M8 0l2.2 5.8L16 8l-5.8 2.2L8 16l-2.2-5.8L0 8l5.8-2.2L8 0z" />
                </svg>
              </span>
              Decision Cortex
            </span>
            <span className="app__tag">a company brain over rust-lang/rfcs</span>
          </div>
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
          {state.totals.totalCalls > 0 ? (
            <span
              className="app__totals"
              title="Deploy-wide decision-ledger totals across every answer so far"
            >
              {state.totals.totalCalls} decisions · $
              {state.totals.totalCostUsd.toFixed(4)}
            </span>
          ) : null}
        </header>

        {view === 'chat' ? (
          <>
            {state.entries.length === 0 ? (
              <div className="app__scroll app__scroll--center">
                <Landing
                  onAsk={onAsk}
                  disabled={state.runningId !== null}
                />
              </div>
            ) : (
              <Thread state={state} />
            )}
            <footer className="app__composerBar">
              {state.entries.length > 0 ? (
                <Button variant="ghost" className="app__discard" onClick={discard}>
                  New conversation
                </Button>
              ) : null}
              <Composer
                onAsk={onAsk}
                disabled={state.runningId !== null}
                chips={state.entries.length > 0}
              />
            </footer>
          </>
        ) : null}

        {view === 'impact' ? (
          <main className="app__scroll app__main">
            <ImpactView />
          </main>
        ) : null}

        {view === 'timeline' ? (
          <main className="app__scroll app__main">
            <TimelinePanel />
          </main>
        ) : null}

        <SourcePanel nodeId={openNodeId} onClose={() => setOpenNodeId(null)} />
      </div>
    </OpenNodeProvider>
  )
}

export default App
