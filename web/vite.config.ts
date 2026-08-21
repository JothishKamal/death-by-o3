import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': 'http://127.0.0.1:8000' } },
  build: {
    rolldownOptions: {
      output: {
        advancedChunks: {
          groups: [
            { name: 'xyflow', test: /@xyflow|@dagrejs/ },
            { name: 'codemirror', test: /@codemirror/ },
            { name: 'shiki', test: /shiki|@shikijs/ },
            { name: 'react', test: /react|scheduler/ },
          ],
        },
      },
    },
  },
  test: { environment: 'jsdom' },
})
