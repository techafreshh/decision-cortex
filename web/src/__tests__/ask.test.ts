import { afterEach, describe, expect, it, vi } from 'vitest'

import { createEventParser, parseFrame, streamAsk } from '../api/ask'
import type { AskEvent } from '../api/types'

describe('parseFrame', () => {
  it('parses a data frame into an event', () => {
    const frame =
      'event: RUN_STARTED\ndata: {"type":"RUN_STARTED","question":"q","scenario":null}'
    expect(parseFrame(frame)).toEqual({
      type: 'RUN_STARTED',
      question: 'q',
      scenario: null,
    })
  })

  it('returns null for a frame with no data line', () => {
    expect(parseFrame('event: RUN_STARTED')).toBeNull()
  })

  it('returns null for malformed JSON', () => {
    expect(parseFrame('data: {not json')).toBeNull()
  })

  it('returns null when the payload has no type', () => {
    expect(parseFrame('data: {"question":"q"}')).toBeNull()
  })

  it('ignores the event: line and trusts the data payload', () => {
    expect(parseFrame('event: WRONG\ndata: {"type":"FAITHFULNESS_PENDING"}')).toEqual(
      { type: 'FAITHFULNESS_PENDING' },
    )
  })
})

describe('createEventParser', () => {
  const frame = (event: object) =>
    `event: ${(event as { type: string }).type}\ndata: ${JSON.stringify(event)}\n\n`

  it('reassembles frames split across chunk boundaries', () => {
    const first = {
      type: 'TEXT_MESSAGE_CONTENT',
      message_id: 'answer',
      delta: 'Hello ',
      chips: [],
      cited: true,
    }
    const second = { type: 'TEXT_MESSAGE_END', message_id: 'answer' }

    const parser = createEventParser()
    expect(
      parser.push('event: TEXT_MESSAGE_CONTENT\ndata: {"type":"TEXT_MESS'),
    ).toEqual([])
    expect(
      parser.push(
        'AGE_CONTENT","message_id":"answer","delta":"Hello ","chips":[],"cited":true}\n\n' +
          frame(second),
      ),
    ).toEqual([first, second])
  })

  it('drops malformed frames but keeps the valid ones', () => {
    const parser = createEventParser()
    expect(
      parser.push('data: {oops\n\n' + frame({ type: 'FAITHFULNESS_PENDING' })),
    ).toEqual([{ type: 'FAITHFULNESS_PENDING' }])
  })

  it('flushes a trailing frame with no blank line', () => {
    const parser = createEventParser()
    expect(parser.push('data: {"type":"RUN_FINISHED"}')).toEqual([])
    expect(parser.flush()).toEqual([{ type: 'RUN_FINISHED' }])
  })
})

describe('streamAsk', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  const sseResponse = (frames: string[]): Response => {
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        const encoder = new TextEncoder()
        for (const frame of frames) controller.enqueue(encoder.encode(frame))
        controller.close()
      },
    })
    return { ok: true, body } as unknown as Response
  }

  it('POSTs the scenario with mode=scripted and yields parsed events', async () => {
    const calls: RequestInit[] = []
    vi.stubGlobal('fetch', (_url: string, init: RequestInit) => {
      calls.push(init)
      return Promise.resolve(
        sseResponse([
          'event: RUN_STARTED\ndata: {"type":"RUN_STARTED","question":"q","scenario":"prove_negative"}\n\n',
          'data: {"type":"RUN_FINISHED"}\n\n',
        ]),
      )
    })

    const events: AskEvent[] = []
    for await (const event of streamAsk({ scenario: 'prove_negative' })) {
      events.push(event)
    }

    expect(events.map((e) => e.type)).toEqual(['RUN_STARTED', 'RUN_FINISHED'])
    expect(JSON.parse(calls[0].body as string)).toEqual({
      question: '',
      scenario: 'prove_negative',
      mode: 'scripted',
    })
  })

  it('defaults mode=free for a free question', async () => {
    const calls: RequestInit[] = []
    vi.stubGlobal('fetch', (_url: string, init: RequestInit) => {
      calls.push(init)
      return Promise.resolve(sseResponse([]))
    })

    for await (const _event of streamAsk({ question: 'why?' })) {
      // drain
    }

    expect(JSON.parse(calls[0].body as string).mode).toBe('free')
  })

  it('surfaces the FastAPI detail on a non-200 response', async () => {
    vi.stubGlobal('fetch', () =>
      Promise.resolve({
        ok: false,
        status: 400,
        statusText: 'Bad Request',
        json: () => Promise.resolve({ detail: "unknown scenario 'nope'" }),
      } as unknown as Response),
    )

    await expect(
      (async () => {
        for await (const _event of streamAsk({ scenario: 'nope' })) {
          // drain
        }
      })(),
    ).rejects.toThrow("unknown scenario 'nope'")
  })
})
