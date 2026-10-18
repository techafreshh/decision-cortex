/**
 * `useThread` owns the conversation: it appends a user message plus a run
 * entry, streams `POST /ask` into the thread store, and fires the async
 * post-stream faithfulness phase for the run that produced it.
 *
 * One run may stream at a time (the composer disables while `runningId` is
 * live), so a run holds its own `AbortController`; `discard` aborts anything
 * still in flight. A finished run keeps receiving its HHEM score even after a
 * newer question starts — scores attach to their own message — but an aborted
 * or discarded run never gets one.
 */

import { useCallback, useReducer, useRef } from 'react'

import { streamAsk, type AskRequest } from '../api/ask'
import { scoreFaithfulness, type FaithfulnessClaim } from '../api/faithfulness'
import {
  initialThreadState,
  reduceThread,
  type ThreadState,
} from '../state/threadStore'

export interface ThreadApi {
  state: ThreadState
  ask: (request: AskRequest, text: string) => void
  discard: () => void
}

let runCounter = 0

export function useThread(): ThreadApi {
  const [state, dispatch] = useReducer(reduceThread, initialThreadState)
  const controllerRef = useRef<AbortController | null>(null)

  const ask = useCallback((request: AskRequest, text: string) => {
    if (controllerRef.current !== null) return
    const runId = `run-${(runCounter += 1)}`
    const controller = new AbortController()
    controllerRef.current = controller

    const scenarioKey = request.scenario ?? null
    dispatch({ kind: 'ask', id: runId, text, scenarioKey })

    const claims: FaithfulnessClaim[] = []
    let finished = false

    const release = () => {
      if (controllerRef.current === controller) controllerRef.current = null
    }

    void (async () => {
      try {
        for await (const event of streamAsk(request, controller.signal)) {
          if (event.type === 'TEXT_MESSAGE_CONTENT') {
            claims.push({
              sentence: event.delta,
              evidence_ids: event.chips.map((chip) => chip.id),
            })
          } else if (event.type === 'RUN_FINISHED') {
            finished = true
          }
          dispatch({ kind: 'event', id: runId, event })
        }
      } catch (error) {
        release()
        if (!controller.signal.aborted) {
          dispatch({
            kind: 'runError',
            id: runId,
            message: error instanceof Error ? error.message : String(error),
          })
        }
        return
      }
      release()
      if (!finished || claims.length === 0) return
      // The stream is done; scoring is the badge's out-of-band phase. It must
      // never fail the run (abort or network error land as a badge state), so
      // its outcome is dispatched as a plain state patch scoped to this run.
      try {
        const [report, message] = await scoreFaithfulness(claims, controller.signal)
        if (!controller.signal.aborted) {
          dispatch({ kind: 'faithfulness', id: runId, report, message })
        }
      } catch (scoringError) {
        if (!controller.signal.aborted) {
          dispatch({
            kind: 'faithfulness',
            id: runId,
            report: null,
            message:
              scoringError instanceof Error
                ? scoringError.message
                : String(scoringError),
          })
        }
      }
    })()
  }, [])

  const discard = useCallback(() => {
    controllerRef.current?.abort()
    controllerRef.current = null
    dispatch({ kind: 'discard' })
  }, [])

  return { state, ask, discard }
}
