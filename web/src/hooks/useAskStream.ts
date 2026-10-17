/**
 * `useAskStream` owns one run at a time: it resets the store, streams
 * `POST /ask`, and folds every event through the reducer. Starting a new run
 * aborts the previous one, so a fast second click never interleaves two runs.
 */

import { useCallback, useReducer, useRef } from 'react'

import { streamAsk, type AskRequest } from '../api/ask'
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

    void (async () => {
      try {
        for await (const event of streamAsk(request, controller.signal)) {
          dispatch({ kind: 'event', event })
        }
      } catch (error) {
        if (!controller.signal.aborted) {
          dispatch({
            kind: 'error',
            message: error instanceof Error ? error.message : String(error),
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
