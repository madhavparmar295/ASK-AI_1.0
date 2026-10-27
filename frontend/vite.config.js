import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The API runs on its own port in development. Proxying it keeps the browser on one
// origin, so the grievance session cookie and CSRF cookie behave exactly as they do in
// production, where one server serves both the chat and /api/grievance.
const backend = process.env.VITE_BACKEND_URL || 'http://localhost:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  base: '/',
  server: {
    proxy: {
      '/api/grievance': backend,
      '/chat/api': backend,
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.js'],
    css: false,
    // The live contract check needs a running backend; `npm test` must not.
    exclude: ['node_modules/**', 'dist/**', 'src/contract/**'],
  },
})
