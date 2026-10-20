import { defineConfig, mergeConfig } from 'vite'
import base from './vite.config.ts'
export default mergeConfig(base, defineConfig({ server: { host: '127.0.0.1', port: 5198, strictPort: true, proxy: { '/api': 'http://127.0.0.1:8896', '/auth': 'http://127.0.0.1:8896', '/healthz': 'http://127.0.0.1:8896' } } }))
