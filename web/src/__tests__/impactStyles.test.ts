/**
 * `evidenceStyle` is the single mapping from a graph relation/stance kind to the
 * label and colour the Impact Explorer and Timeline render. These tests pin the
 * full vocabulary (`api/impact.py::IMPACT_RELATIONS`) and the unknown-kind
 * degradation, since a silent gap here would make an edge vanish from the graph.
 */

import { describe, expect, it } from 'vitest'

import { evidenceLabel, evidenceStyle } from '../lib/evidenceStyle'

const RELATIONS = [
  'ABOUT',
  'AREA',
  'RELATES',
  'SUPERSEDES',
  'ASSOCIATED_TEAM',
  'PROPOSED_BY',
  'OBJECTED',
  'SUPPORTED',
  'MODERATED',
]

describe('evidenceStyle', () => {
  it('labels every relation with a non-empty human string', () => {
    for (const relation of RELATIONS) {
      const style = evidenceStyle(relation)
      expect(style.label.length).toBeGreaterThan(0)
      expect(style.label).not.toBe(relation)
      expect(style.color.length).toBeGreaterThan(0)
    }
  })

  it('keeps the stance kinds visually distinct by tone', () => {
    expect(evidenceStyle('OBJECTED').tone).toBe('bad')
    expect(evidenceStyle('SUPPORTED').tone).toBe('good')
    expect(evidenceStyle('MODERATED').tone).toBe('warn')
    expect(evidenceStyle('SUPERSEDES').tone).toBe('warn')
  })

  it('degrades an unknown kind instead of dropping it', () => {
    const style = evidenceStyle('MYSTERY_EDGE')
    expect(style.label).toBe('mystery_edge')
    expect(style.tone).toBe('plain')
    expect(evidenceLabel('MYSTERY_EDGE')).toBe('mystery_edge')
  })
})
