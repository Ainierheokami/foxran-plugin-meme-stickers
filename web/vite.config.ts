import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'
import cssInjectedByJsPlugin from 'vite-plugin-css-injected-by-js'

export default defineConfig({
  plugins: [vue(), cssInjectedByJsPlugin()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('.', import.meta.url))
    }
  },
  build: {
    outDir: '../',
    emptyOutDir: false,
    lib: {
      entry: 'index.ts',
      name: 'MemeStickersPlugin',
      formats: ['umd'],
      fileName: () => 'index.umd.js'
    },
    rollupOptions: {
      external: ['vue', 'vue-router', 'lucide-vue-next', 'element-plus'],
      output: {
        globals: {
          vue: 'Vue',
          'vue-router': 'VueRouter',
          'lucide-vue-next': 'LucideVueNext',
          'element-plus': 'ElementPlus'
        }
      }
    }
  }
})
