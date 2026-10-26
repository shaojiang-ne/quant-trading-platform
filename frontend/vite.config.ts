import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    proxy: {
      '/api': {
        target: `http://localhost:${process.env.STOCK_BACKEND_PORT || 8010}`,
        changeOrigin: true,
      },
      '/ws': {
        target: `ws://localhost:${process.env.STOCK_BACKEND_PORT || 8010}`,
        ws: true,
      },
    },
  },
})
