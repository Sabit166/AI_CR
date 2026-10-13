import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import react, { reactCompilerPreset } from '@vitejs/plugin-react'
import babel from '@rolldown/plugin-babel'

// Two pages: the public student board at / and the CR dashboard at /cr/.
// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    babel({ presets: [reactCompilerPreset()] })
  ],
  build: {
    rollupOptions: {
      input: {
        student: fileURLToPath(new URL('./index.html', import.meta.url)),
        cr: fileURLToPath(new URL('./cr/index.html', import.meta.url)),
      },
    },
  },
})
