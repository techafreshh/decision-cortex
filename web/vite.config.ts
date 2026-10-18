import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// The dev server proxies the API routes to the FastAPI app so the SPA can call
// relative paths (`/ask`, `/node/{id}`, `/graph`, `/timeline`, `/exports`,
// `/healthz`) in both dev and the Caddy deployment. Override the target with
// `VITE_API_PROXY` when the API is not on the default port.
const apiTarget = process.env.VITE_API_PROXY ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/ask': apiTarget,
      '/node': apiTarget,
      '/graph': apiTarget,
      '/timeline': apiTarget,
      '/exports': apiTarget,
      '/faithfulness': apiTarget,
      '/verification': apiTarget,
      '/healthz': apiTarget,
    },
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.{ts,tsx}'],
  },
})
