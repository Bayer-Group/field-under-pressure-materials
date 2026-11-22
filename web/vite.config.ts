import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import { viteSingleFile } from 'vite-plugin-singlefile'

// Dev server: the API runs separately (scripts/12_gui.py) and /api is forwarded to it.
// Static mode (`vite build --mode static`): single-file index.html that works from file://.
export default defineConfig(({ mode }) => {
  if (mode === 'static') {
    return {
      base: './',
      plugins: [react(), viteSingleFile()],
      build: { outDir: '../static_version', emptyOutDir: false },
    }
  }
  return {
    plugins: [react()],
    server: { host: '127.0.0.1', proxy: { '/api': 'http://127.0.0.1:8000' } },
  }
})
