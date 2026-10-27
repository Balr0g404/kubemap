import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  ssr: { noExternal: ['vuetify', '@vue-flow/core', '@xterm/xterm', '@xterm/addon-fit'] },
  server: { proxy: { '/api': 'http://127.0.0.1:8765' } },
})
