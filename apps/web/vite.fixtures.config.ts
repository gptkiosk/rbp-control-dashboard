import { defineConfig } from 'vite'
import base from './vite.config.ts'

// Isolated UI fixtures must never proxy a browser request into a live API.
export default defineConfig({
  ...base,
  server: { host: '127.0.0.1', port: 5194, strictPort: true, proxy: {} },
  plugins: [...(base.plugins ?? []), {
    name: 'fixture-api-denied',
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        if (/^\/(?:api(?:\/|\?|$)|healthz(?:\?|$))/.test(request.url ?? '')) {
          response.statusCode = 403
          response.setHeader('Content-Type', 'application/json')
          response.end(JSON.stringify({ detail: 'Isolated UI fixture: real API access is disabled.' }))
          return
        }
        next()
      })
    },
  }],
})
