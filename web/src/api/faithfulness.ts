/**
 * The client for `POST /faithfulness` — the async post-stream phase of the
 * answer (PRD §10). The backend scores each sentence against its cited
 * evidence text with the local HHEM-2.1-Open cross-encoder; the badge shows
 * "scoring…" until this resolves. Failures resolve to `null` report + error
 * message rather than throwing: a scoring outage must never surface as a run
 * failure.
 */

import type { FaithfulnessReport } from './types'

export interface FaithfulnessClaim {
  sentence: string
  evidence_ids: string[]
}

/** Read the FastAPI `{"detail": ...}` body so the UI can show *why* a POST failed. */
async function errorDetail(response: Response): Promise<string> {
  try {
    const body: unknown = await response.json()
    const detail = (body as { detail?: unknown }).detail
    if (typeof detail === 'string') return detail
  } catch {
    // non-JSON error body — fall through to the status text
  }
  return response.statusText || 'request failed'
}

/**
 * POST the claims and resolve the report, or `null` on any failure (the
 * second element carries the human-readable reason for the badge's fallback).
 */
export async function scoreFaithfulness(
  claims: FaithfulnessClaim[],
  signal?: AbortSignal,
): Promise<[FaithfulnessReport | null, string | null]> {
  if (claims.length === 0) return [null, null]
  const response = await fetch('/faithfulness', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      claims: claims.map((claim) => ({
        sentence: claim.sentence,
        evidence_ids: claim.evidence_ids,
      })),
    }),
    signal,
  })
  if (!response.ok) {
    return [
      null,
      `POST /faithfulness failed (${response.status}): ${await errorDetail(response)}`,
    ]
  }
  const parsed: unknown = await response.json()
  if (typeof parsed !== 'object' || parsed === null) {
    return [null, 'POST /faithfulness returned a non-object body']
  }
  return [parsed as FaithfulnessReport, null]
}
