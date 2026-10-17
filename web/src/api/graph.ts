/**
 * The graph-read and export clients for the Impact Explorer and Timeline.
 *
 * `getImpact` / `getTimeline` / `getTour` mirror the `GET /graph/impact/{id}`,
 * `GET /timeline`, and `GET /timeline?tour=` endpoints; a missing seed resolves
 * to `null` so the view can say "no such node" instead of throwing. The export
 * helpers POST to `/exports/*` and hand back the downloaded bytes, keeping the
 * browser-only blob save (`saveBlob`) separate from the fetch so both stay
 * testable.
 */

import type { ImpactGraph, Timeline, Tour } from './types'

export interface ExportRequest {
  node_id?: string
  scenario?: string
}

export interface ExportResult {
  blob: Blob
  filename: string
}

export async function getImpact(
  nodeId: string,
  signal?: AbortSignal,
): Promise<ImpactGraph | null> {
  const response = await fetch(`/graph/impact/${encodeURIComponent(nodeId)}`, {
    signal,
  })
  if (response.status === 404) return null
  if (!response.ok) {
    throw new Error(`GET /graph/impact/${nodeId} failed: ${response.status}`)
  }
  return (await response.json()) as ImpactGraph
}

export async function getTimeline(signal?: AbortSignal): Promise<Timeline> {
  const response = await fetch('/timeline', { signal })
  if (!response.ok) {
    throw new Error(`GET /timeline failed: ${response.status}`)
  }
  return (await response.json()) as Timeline
}

export async function getTour(name: string, signal?: AbortSignal): Promise<Tour> {
  const response = await fetch(`/timeline?tour=${encodeURIComponent(name)}`, {
    signal,
  })
  if (!response.ok) {
    throw new Error(`GET /timeline?tour=${name} failed: ${response.status}`)
  }
  return (await response.json()) as Tour
}

/** Pull the filename out of a `Content-Disposition` header, or `null`. */
export function filenameFromDisposition(disposition: string): string | null {
  const match = /filename="([^"]+)"/.exec(disposition)
  return match === null ? null : match[1]
}

export async function requestExport(
  path: '/exports/report' | '/exports/graph',
  body: ExportRequest,
  signal?: AbortSignal,
): Promise<ExportResult> {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })
  if (!response.ok) {
    throw new Error(`POST ${path} failed: ${response.status}`)
  }
  const filename =
    filenameFromDisposition(response.headers.get('content-disposition') ?? '') ??
    'decision-cortex-export'
  return { blob: await response.blob(), filename }
}

/** Browser-only: hand the bytes to the download manager via a temporary anchor. */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}

export async function downloadReport(
  body: ExportRequest,
  signal?: AbortSignal,
): Promise<string> {
  const { blob, filename } = await requestExport('/exports/report', body, signal)
  saveBlob(blob, filename)
  return filename
}

export async function downloadGraph(
  body: ExportRequest,
  signal?: AbortSignal,
): Promise<string> {
  const { blob, filename } = await requestExport('/exports/graph', body, signal)
  saveBlob(blob, filename)
  return filename
}
