/**
 * The Timeline surface: the decision history, flat or along a curated tour.
 *
 * `TimelineView` is presentational (so it render-tests in Node); `TimelinePanel`
 * owns the two fetches — the flat `GET /timeline` and, once a tour is picked,
 * `GET /timeline?tour=`. Every decision and every tour stage is a button that
 * opens the shared `SourcePanel`, and each carries an export action
 * (`POST /exports/report`) so the receipt travels with the story.
 */

import { useEffect, useState } from 'react'

import { downloadReport, getTimeline, getTour } from '../api/graph'
import type { Timeline, TimelineDecision, Tour, TourStage } from '../api/types'
import { Badge, type BadgeTone } from './kit/Badge'
import { Button } from './kit/Button'
import { evidenceStyle } from '../lib/evidenceStyle'
import { useOpenNode } from './SourcePanel'

function statusTone(status: string | null): BadgeTone {
  if (status === 'merged') return 'good'
  if (status === 'rejected') return 'bad'
  return 'muted'
}

/** Friendly labels for the curated tours; an unknown key falls back to its id. */
const TOUR_LABELS: Record<string, string> = {
  async_await: 'The async/await story',
}

export function tourLabel(name: string): string {
  return TOUR_LABELS[name] ?? name
}

/**
 * The tour as revealed after `step` advances — stage 0 plus every stage up to
 * `step`, with the matching lifecycle transitions. Pure, so the stage-by-stage
 * walk is testable without the canvas.
 */
export function tourProgress(tour: Tour, step: number): Tour {
  const clamped = Math.max(0, Math.min(step, tour.stages.length - 1))
  const shown = clamped + 1
  return {
    ...tour,
    stages: tour.stages.slice(0, shown),
    transitions: tour.transitions.slice(0, shown - 1),
  }
}

export interface TimelineViewProps {
  timeline: Timeline
  tour: Tour | null
  selectedTour: string | null
  onSelectTour: (name: string | null) => void
  onExportNode: (id: string) => void
}

export function TimelineView({
  timeline,
  tour,
  selectedTour,
  onSelectTour,
  onExportNode,
}: TimelineViewProps) {
  // `null` means "the whole spine" (the default); a number is a stage-by-stage
  // walk position, started by Replay and advanced by Next stage.
  const [step, setStep] = useState<number | null>(null)

  useEffect(() => {
    setStep(null)
  }, [tour?.tour])

  const shown = tour === null ? null : step === null ? tour : tourProgress(tour, step)
  const atEnd =
    tour !== null && (step === null || step >= tour.stages.length - 1)

  return (
    <section className="timeline">
      <div className="timeline__tours">
        <Button
          variant={selectedTour === null ? 'primary' : 'ghost'}
          onClick={() => onSelectTour(null)}
        >
          All decisions
        </Button>
        {timeline.tours.map((name) => (
          <Button
            key={name}
            variant={selectedTour === name ? 'primary' : 'ghost'}
            onClick={() => onSelectTour(name)}
          >
            {tourLabel(name)}
          </Button>
        ))}
      </div>

      {shown === null ? (
        <FlatTimeline decisions={timeline.decisions} onExportNode={onExportNode} />
      ) : (
        <>
          <div className="timeline__player">
            <Button
              variant="primary"
              disabled={atEnd}
              onClick={() => setStep((current) => (current === null ? 0 : current + 1))}
            >
              Next stage
            </Button>
            <Button variant="ghost" onClick={() => setStep(0)}>
              Replay
            </Button>
            <span className="muted">
              stage {shown.stages.length} of {tour?.stages.length}
            </span>
          </div>
          <TourSpine tour={shown} onExportNode={onExportNode} />
        </>
      )}
    </section>
  )
}

function FlatTimeline({
  decisions,
  onExportNode,
}: {
  decisions: TimelineDecision[]
  onExportNode: (id: string) => void
}) {
  return (
    <ol className="timeline__list">
      {decisions.map((decision) => (
        <DecisionRow
          key={decision.id}
          decision={decision}
          onExportNode={onExportNode}
        />
      ))}
    </ol>
  )
}

function DecisionRow({
  decision,
  onExportNode,
}: {
  decision: TimelineDecision
  onExportNode: (id: string) => void
}) {
  const openNode = useOpenNode()
  const label = decision.rfc === null ? decision.id : `RFC ${decision.rfc}`
  return (
    <li className="timeline__item">
      <div className="timeline__head">
        <button
          type="button"
          className="timeline__node"
          onClick={() => openNode(decision.id)}
        >
          <span className="timeline__rfc">{label}</span>
          <span className="timeline__title">{decision.title}</span>
        </button>
        <Badge tone={statusTone(decision.status)}>{decision.status ?? 'unknown'}</Badge>
        <Button
          variant="ghost"
          aria-label={`Export ${decision.id}`}
          onClick={() => onExportNode(decision.id)}
        >
          Export
        </Button>
      </div>

      <p className="timeline__dates">
        {decision.proposed_on ?? '—'} → {decision.decided_on ?? '—'}
      </p>

      {decision.areas.length + decision.teams.length === 0 ? null : (
        <p className="timeline__tags">
          {decision.areas.map((area) => (
            <Badge key={`area:${area}`} tone="muted">
              {area}
            </Badge>
          ))}
          {decision.teams.map((team) => (
            <Badge key={`team:${team}`} tone="muted">
              {team}
            </Badge>
          ))}
        </p>
      )}

      {decision.stances.length === 0 ? null : (
        <ul className="timeline__stances">
          {decision.stances.map((stance) => (
            <li key={`${stance.handle}:${stance.kind}`}>
              <Badge tone={evidenceStyle(stance.kind).tone}>{stance.kind}</Badge>{' '}
              <span className="timeline__handle">{stance.handle}</span>
            </li>
          ))}
        </ul>
      )}

      {decision.supersedes.length + decision.superseded_by.length === 0 ? null : (
        <p className="timeline__supersede">
          {decision.supersedes.length > 0
            ? `supersedes ${decision.supersedes.map((n) => `RFC ${n}`).join(', ')}`
            : null}
          {decision.supersedes.length > 0 && decision.superseded_by.length > 0
            ? ' · '
            : null}
          {decision.superseded_by.length > 0
            ? `superseded by ${decision.superseded_by.map((n) => `RFC ${n}`).join(', ')}`
            : null}
        </p>
      )}
    </li>
  )
}

function TourSpine({
  tour,
  onExportNode,
}: {
  tour: Tour
  onExportNode: (id: string) => void
}) {
  return (
    <ol className="tour">
      {tour.stages.map((stage, index) => (
        <li className="tour__stage" key={stage.id}>
          <TourCard stage={stage} onExportNode={onExportNode} />
          {index < tour.transitions.length ? (
            <p className="tour__transition">↓ {tour.transitions[index].label}</p>
          ) : null}
        </li>
      ))}
    </ol>
  )
}

function TourCard({
  stage,
  onExportNode,
}: {
  stage: TourStage
  onExportNode: (id: string) => void
}) {
  const openNode = useOpenNode()
  return (
    <div className="tour__card">
      <div className="tour__head">
        <button type="button" className="timeline__node" onClick={() => openNode(stage.id)}>
          <span className="timeline__rfc">RFC {stage.rfc}</span>
          <span className="timeline__title">{stage.title}</span>
        </button>
        <Badge tone={statusTone(stage.status)}>{stage.status ?? 'unknown'}</Badge>
        <Button
          variant="ghost"
          aria-label={`Export ${stage.id}`}
          onClick={() => onExportNode(stage.id)}
        >
          Export
        </Button>
      </div>
      <p className="tour__narrative">{stage.narrative}</p>
      <p className="tour__meta">
        <span className="tour__role">{stage.role}</span>
        <span className="timeline__dates">{stage.proposed_on ?? '—'}</span>
      </p>
    </div>
  )
}

type Status = 'loading' | 'ready' | 'error'

export function TimelinePanel() {
  const [timeline, setTimeline] = useState<Timeline | null>(null)
  const [tour, setTour] = useState<Tour | null>(null)
  const [selectedTour, setSelectedTour] = useState<string | null>(null)
  const [status, setStatus] = useState<Status>('loading')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    getTimeline(controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return
        setTimeline(result)
        setStatus('ready')
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return
        setError(cause instanceof Error ? cause.message : String(cause))
        setStatus('error')
      })
    return () => controller.abort()
  }, [])

  useEffect(() => {
    if (selectedTour === null) {
      setTour(null)
      return
    }
    const controller = new AbortController()
    getTour(selectedTour, controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return
        setTour(result)
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return
        setError(cause instanceof Error ? cause.message : String(cause))
      })
    return () => controller.abort()
  }, [selectedTour])

  const exportNode = (id: string) => {
    downloadReport({ node_id: id }).catch((cause: unknown) => {
      setError(cause instanceof Error ? cause.message : String(cause))
    })
  }

  if (status === 'loading') return <p className="muted">Loading the timeline…</p>
  if (status === 'error' || timeline === null) {
    return <p className="error">{error ?? 'timeline unavailable'}</p>
  }

  return (
    <>
      {error === null ? null : <p className="error">{error}</p>}
      <TimelineView
        timeline={timeline}
        tour={tour}
        selectedTour={selectedTour}
        onSelectTour={setSelectedTour}
        onExportNode={exportNode}
      />
    </>
  )
}
