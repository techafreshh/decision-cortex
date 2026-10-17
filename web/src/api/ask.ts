/**
 * The SSE client for `POST /ask`.
 *
 * Hand-rolled against the frozen schema (PRD §6.2 fallback: "hand-rolled SSE
 * with the same event schema"). The backend streams `event: TYPE\ndata: {...}`
 * frames separated by blank lines; `createEventParser` reassembles them across
 * chunk boundaries and drops malformed frames so one bad byte never kills the
 * stream. The caller gets a plain async iterable of events.
 */

import type { AskEvent } from './types'

/** The four PRD §10 scripted scenarios, in demo-script order. */
export const SCENARIOS: { key: string; label: string }[] = [
  { key: 'ask_corpus', label: 'Ask the corpus' },
  { key: 'prove_negative', label: 'Prove the negative' },
  { key: 'impact_tour', label: 'Impact tour' },
  { key: 'async_story', label: 'The async/await story' },
]

export interface AskRequest {
  question?: string
  scenario?: string | null
  /** `scripted` for a verification-set button, `free` for the chat box. */
  mode?: 'free' | 'scripted'
}

/**
 * Parse one SSE frame (`event:` + `data:` lines, no trailing blank line) into an
 * event, or `null` for a frame with no valid `data:` JSON object carrying a
 * string `type`.
 */
export function parseFrame(frame: string): AskEvent | null {
  const dataLines = frame
    .split('\n')
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice('data:'.length).trimStart())
  if (dataLines.length === 0) return null
  const payload = dataLines.join('\n')
  if (payload === '') return null
  try {
    const parsed: unknown = JSON.parse(payload)
    if (typeof parsed !== 'object' || parsed === null) return null
    const type = (parsed as { type?: unknown }).type
    if (typeof type !== 'string') return null
    return parsed as AskEvent
  } catch {
    return null
  }
}

/** An incremental frame splitter: `push` each decoded chunk, `flush` the tail. */
export function createEventParser(): {
  push: (chunk: string) => AskEvent[]
  flush: () => AskEvent[]
} {
  let buffer = ''
  const drain = (frame: string): AskEvent | null => parseFrame(frame)
  return {
    push(chunk: string): AskEvent[] {
      buffer += chunk
      const frames = buffer.split('\n\n')
      buffer = frames.pop() ?? ''
      return frames
        .map(drain)
        .filter((event): event is AskEvent => event !== null)
    },
    flush(): AskEvent[] {
      const tail = buffer
      buffer = ''
      const event = tail === '' ? null : drain(tail)
      return event === null ? [] : [event]
    },
  }
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

/** POST the request and yield the parsed event stream until it ends. */
export async function* streamAsk(
  request: AskRequest,
  signal?: AbortSignal,
): AsyncGenerator<AskEvent> {
  const response = await fetch('/ask', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      question: request.question ?? '',
      scenario: request.scenario ?? null,
      mode: request.mode ?? (request.scenario ? 'scripted' : 'free'),
    }),
    signal,
  })
  if (!response.ok) {
    throw new Error(`POST /ask failed (${response.status}): ${await errorDetail(response)}`)
  }
  if (response.body === null) {
    throw new Error('POST /ask returned no body to stream')
  }

  const parser = createEventParser()
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    for (const event of parser.push(decoder.decode(value, { stream: true }))) {
      yield event
    }
  }
  for (const event of parser.flush()) {
    yield event
  }
}
