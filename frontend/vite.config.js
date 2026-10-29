/**
 * FreshRoute Vite configuration.
 * Responsible for: building the React app and proxying API + WebSocket traffic to FastAPI in dev.
 * NOT responsible for: business logic, data fetching or production serving (FastAPI serves dist/).
 */
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const BACKEND = 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/state': BACKEND,
      '/health': BACKEND,
      '/analytics': BACKEND,
      '/audit.csv': BACKEND,
      '/simulate': BACKEND,
      '/recommend': BACKEND,
      '/reroute': BACKEND,
      '/reset': BACKEND,
      '/events': { target: BACKEND, ws: true },
    },
  },
})
