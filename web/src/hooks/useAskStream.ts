/**
 * `useAskStream` owns one run at a time: it resets the store, streams
 * `POST /ask`, and folds every event through the reducer. Starting a new run
 * aborts the previous one, so a fast second click never interleaves two runs.
 *
 * Once a run finishes with answer sentences, the hook fires the scored async
 * post-stream phase — `POST /faithfulness` with the sentences and their
 * cited evidence ids — and dispatches the report when it lands. A run started
 * or cleared while scoring is in flight invalidates the result: the dispatch
 * checks that this run's controller is still the live one, so a stale score
 * can never attach to a newer question.
 */

import { useCallback, useReducer, useRef } from 'react'

import { streamAsk, type AskRequest } from '../api/ask'
import { scoreFaithfulness, type FaithfulnessClaim } from '../api/faithfulness'
import { initialRunState, reduceRun, type RunState } from '../state/runStore'

export interface UseAskStream {
  state: RunState
  ask: (request: AskRequest) => void
  clear: () => void
}

export function useAskStream(): UseAskStream {
  const [state, dispatch] = useReducer(reduceRun, initialRunState)
  const controllerRef = useRef<AbortController | null>(null)

  const ask = useCallback((request: AskRequest) => {
    controllerRef.current?.abort()
    const controller = new AbortController()
    controllerRef.current = controller

    dispatch({ kind: 'reset', request })

    const claims: FaithfulnessClaim[] = []
    let finished = false

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
          dispatch({ kind: 'event', event })
        }
      } catch (error) {
        if (!controller.signal.aborted) {
          dispatch({
            kind: 'error',
            message: error instanceof Error ? error.message : String(error),
          })
        }
        return
      }
      if (!finished || claims.length === 0) return
      // The stream is done; scoring is the badge's out-of-band phase. It must
      // never fail the run (abort or network error land as a badge state), so
      // its outcome is dispatched as a plain state patch.
      try {
        const [report, message] = await scoreFaithfulness(claims, controller.signal)
        if (controllerRef.current === controller) {
          dispatch({ kind: 'faithfulness', report, message })
        }
      } catch (scoringError) {
        if (!controller.signal.aborted && controllerRef.current === controller) {
          dispatch({
            kind: 'faithfulness',
            report: null,
            message: scoringError instanceof Error ? scoringError.message : String(scoringError),
          })
        }
      }
    })()
  }, [])

  const clear = useCallback(() => {
    controllerRef.current?.abort()
    controllerRef.current = null
    dispatch({ kind: 'clear' })
  }, [])

  return { state, ask, clear }
}
