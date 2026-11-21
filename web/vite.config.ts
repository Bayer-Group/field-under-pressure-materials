import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Dev server: the API runs separately (scripts/12_gui.py) and /api is forwarded to it.
export default defineConfig({
  plugins: [react()],
  server: { host: '127.0.0.1', proxy: { '/api': 'http://127.0.0.1:8000' } },
})
