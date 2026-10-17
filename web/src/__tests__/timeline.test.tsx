/**
 * Render smoke tests for the Timeline surface (`react-dom/server`, no browser).
 * They assert the demo-critical content: the tour selector, the flat decision
 * rows with stance badges and the supersede link, and the curated tour spine
 * with its narratives and transitions.
 */

import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { OpenNodeProvider } from '../components/SourcePanel'
import { TimelineView, tourProgress } from '../components/TimelineView'
import type { Timeline, Tour } from '../api/types'

const TIMELINE: Timeline = {
  decisions: [
    {
      id: 'rfc:200',
      rfc: 200,
      title: 'Trait objects',
      status: 'merged',
      proposed_on: '2014-02-01',
      decided_on: '2014-04-01',
      areas: ['trait-objects'],
      teams: ['lang'],
      supersedes: [],
      superseded_by: [300],
      stances: [
        { handle: 'bob', kind: 'OBJECTED', evidence: null, confidence: 0.8 },
      ],
    },
    {
      id: 'rfc:300',
      rfc: 300,
      title: 'Rejected trait-object idea',
      status: 'rejected',
      proposed_on: null,
      decided_on: null,
      areas: [],
      teams: [],
      supersedes: [200],
      superseded_by: [],
      stances: [],
    },
  ],
  supersede_edges: [{ src: 'rfc:300', dst: 'rfc:200' }],
  areas: ['trait-objects'],
  teams: ['lang'],
  tours: ['async_await'],
}

const TOUR: Tour = {
  tour: 'async_await',
  stages: [
    {
      id: 'rfc:2394',
      rfc: 2394,
      title: 'async/await notation',
      status: 'merged',
      proposed_on: '2018-04-06',
      decided_on: '2018-05-08',
      role: 'syntax-landed',
      narrative: 'The await syntax finally lands.',
    },
  ],
  transitions: [],
}

const noop = () => {}

function render(node: React.ReactElement): string {
  return renderToStaticMarkup(<OpenNodeProvider value={noop}>{node}</OpenNodeProvider>)
}

describe('TimelineView', () => {
  it('renders the tour selector and the flat decisions', () => {
    const html = render(
      <TimelineView
        timeline={TIMELINE}
        tour={null}
        selectedTour={null}
        onSelectTour={noop}
        onExportNode={noop}
      />,
    )

    expect(html).toContain('All decisions')
    expect(html).toContain('The async/await story')
    expect(html).toContain('RFC 200')
    expect(html).toContain('Trait objects')
    expect(html).toContain('OBJECTED')
    expect(html).toContain('bob')
    expect(html).toContain('superseded by RFC 300')
    expect(html).toContain('supersedes RFC 200')
  })

  it('renders the curated tour spine with narrative and transition', () => {
    const html = render(
      <TimelineView
        timeline={TIMELINE}
        tour={{ ...TOUR, transitions: [{ from: 'rfc:2394', to: 'rfc:2394', label: 'next' }] }}
        selectedTour="async_await"
        onSelectTour={noop}
        onExportNode={noop}
      />,
    )

    expect(html).toContain('The await syntax finally lands.')
    expect(html).toContain('syntax-landed')
    expect(html).toContain('RFC 2394')
    expect(html).toContain('↓ next')
  })
})

describe('tourProgress', () => {
  const SPINE: Tour = {
    tour: 'async_await',
    stages: [
      { ...TOUR.stages[0], id: 'rfc:53', rfc: 53, role: 'first' },
      { ...TOUR.stages[0], id: 'rfc:1083', rfc: 1083, role: 'second' },
      { ...TOUR.stages[0], id: 'rfc:1823', rfc: 1823, role: 'third' },
    ],
    transitions: [
      { from: 'rfc:53', to: 'rfc:1083', label: 'a' },
      { from: 'rfc:1083', to: 'rfc:1823', label: 'b' },
    ],
  }

  it('reveals one stage at a time with the matching transitions', () => {
    expect(tourProgress(SPINE, 0).stages.map((s) => s.rfc)).toEqual([53])
    expect(tourProgress(SPINE, 0).transitions).toEqual([])
    expect(tourProgress(SPINE, 1).stages.map((s) => s.rfc)).toEqual([53, 1083])
    expect(tourProgress(SPINE, 1).transitions.map((t) => t.label)).toEqual(['a'])
    expect(tourProgress(SPINE, 2).transitions.map((t) => t.label)).toEqual(['a', 'b'])
  })

  it('clamps out-of-range steps to the ends', () => {
    expect(tourProgress(SPINE, -4).stages).toHaveLength(1)
    expect(tourProgress(SPINE, 99).stages).toHaveLength(3)
    expect(tourProgress(SPINE, 99).transitions).toHaveLength(2)
  })
})
