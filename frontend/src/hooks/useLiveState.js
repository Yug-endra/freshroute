/**
 * FreshRoute live-state hook.
 * Responsible for: opening the /events WebSocket, applying full-state messages,
 * falling back to GET /state every 2 s when the socket drops, and retrying the
 * socket every 5 s. Exposes {state, connected, error, refresh}.
 * NOT responsible for: rendering, or any simulation/business logic.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchState } from '../api'

const POLL_MS = 2000
const RETRY_MS = 5000

export default function useLiveState() {
  const [state, setState] = useState(null)
  const [connected, setConnected] = useState(false)
  const [error, setError] = useState(null)

  const socketRef = useRef(null)
  const pollTimerRef = useRef(null)
  const retryTimerRef = useRef(null)
  const aliveRef = useRef(true)

  const apply = useCallback((next) => {
    if (!aliveRef.current) return
    setState(next)
    setError(null)
  }, [])

  const stopPolling = useCallback(() => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current)
      pollTimerRef.current = null
    }
  }, [])

  const startPolling = useCallback(() => {
    if (pollTimerRef.current) return
    const poll = async () => {
      try {
        apply(await fetchState())
      } catch (err) {
        if (aliveRef.current) setError(err.message)
      }
    }
    poll()
    pollTimerRef.current = setInterval(poll, POLL_MS)
  }, [apply])

  const connect = useCallback(() => {
    if (!aliveRef.current) return

    // ?poll=1 is a demo/testing switch that skips the socket entirely and
    // exercises the 2 s polling fallback on purpose.
    if (new URLSearchParams(window.location.search).has('poll')) {
      startPolling()
      return
    }

    const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws'
    let socket
    try {
      socket = new WebSocket(`${scheme}://${window.location.host}/events`)
    } catch (err) {
      startPolling()
      retryTimerRef.current = setTimeout(connect, RETRY_MS)
      return
    }

    socketRef.current = socket

    socket.onopen = () => {
      if (!aliveRef.current) return
      setConnected(true)
      setError(null)
      stopPolling() // The socket is healthy, so polling is no longer needed.
    }

    socket.onmessage = (event) => {
      try {
        apply(JSON.parse(event.data))
      } catch {
        // Ignore a malformed frame; the next tick will send a fresh snapshot.
      }
    }

    socket.onerror = () => {
      socket.close()
    }

    socket.onclose = () => {
      if (!aliveRef.current) return
      setConnected(false)
      startPolling() // Safety net while the socket is down.
      clearTimeout(retryTimerRef.current)
      retryTimerRef.current = setTimeout(connect, RETRY_MS)
    }
  }, [apply, startPolling, stopPolling])

  useEffect(() => {
    aliveRef.current = true
    connect()
    return () => {
      aliveRef.current = false
      clearTimeout(retryTimerRef.current)
      stopPolling()
      const socket = socketRef.current
      if (socket) {
        socket.onclose = null
        socket.close()
      }
    }
  }, [connect, stopPolling])

  const refresh = useCallback(async () => {
    try {
      const next = await fetchState()
      apply(next)
      return next
    } catch (err) {
      if (aliveRef.current) setError(err.message)
      throw err
    }
  }, [apply])

  return { state, connected, error, refresh }
}
