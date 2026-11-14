import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig(({ mode }) => ({
  base: mode === 'pages' ? './' : '/',
  publicDir: mode === 'pages' ? 'public-pages' : 'public',
  build: { outDir: mode === 'pages' ? 'dist-pages' : 'dist' },
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
}))
