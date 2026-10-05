/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const gateway = process.env.VITE_GATEWAY_URL ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: gateway, changeOrigin: true },
      '/health': { target: gateway, changeOrigin: true },
    },
  },
  test: { environment: 'jsdom', globals: true },
})
