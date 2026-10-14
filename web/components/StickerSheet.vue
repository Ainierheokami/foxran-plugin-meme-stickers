<template>
  <Teleport to="body">
    <Transition :name="side === 'right' ? 'sheet-slide' : 'sheet-pop'">
      <div v-if="open" class="sheet-backdrop" :class="`side-${side}`" @mousedown.self="close">
        <div class="sheet-panel" :class="`side-${side}`" :style="{ '--sheet-width': width }" role="dialog" aria-modal="true">
          <header class="sheet-head">
            <div class="sheet-title">
              <slot name="title">{{ title }}</slot>
            </div>
            <button class="sheet-close" title="关闭" @click="close">
              <X class="sheet-icon" />
            </button>
          </header>
          <div class="sheet-body">
            <slot />
          </div>
          <footer v-if="$slots.footer" class="sheet-foot">
            <slot name="footer" />
          </footer>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { onBeforeUnmount, watch } from 'vue'
import { X } from 'lucide-vue-next'

const props = withDefaults(defineProps<{
  open: boolean
  title?: string
  side?: 'center' | 'right'
  width?: string
  /** 进行中的操作不允许关闭 */
  locked?: boolean
}>(), { title: '', side: 'center', width: '34rem', locked: false })

const emit = defineEmits<{ (e: 'close'): void }>()

function close() {
  if (!props.locked) emit('close')
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') close()
}

watch(() => props.open, (value) => {
  if (value) window.addEventListener('keydown', onKeydown)
  else window.removeEventListener('keydown', onKeydown)
}, { immediate: true })

onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
</script>

<style scoped>
.sheet-backdrop {
  position: fixed;
  inset: 0;
  z-index: 90;
  display: flex;
  background: rgb(0 0 0 / 0.36);
  backdrop-filter: blur(2px);
}

.sheet-backdrop.side-center {
  align-items: center;
  justify-content: center;
  padding: 1rem;
}

.sheet-backdrop.side-right {
  justify-content: flex-end;
}

.sheet-panel {
  display: flex;
  flex-direction: column;
  width: min(var(--sheet-width), 100%);
  background: hsl(var(--card));
  color: hsl(var(--card-foreground, var(--foreground)));
  border: 1px solid hsl(var(--border));
  box-shadow: 0 24px 60px rgb(0 0 0 / 0.2);
}

.sheet-panel.side-center {
  max-height: min(46rem, calc(100vh - 2rem));
  border-radius: 0.75rem;
}

.sheet-panel.side-right {
  height: 100%;
  border-width: 0 0 0 1px;
}

.sheet-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  border-bottom: 1px solid hsl(var(--border));
  padding: 0.85rem 1rem;
}

.sheet-title {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 0.5rem;
  font-size: 1rem;
  font-weight: 600;
}

.sheet-close {
  display: inline-flex;
  height: 2rem;
  width: 2rem;
  flex: 0 0 2rem;
  align-items: center;
  justify-content: center;
  border-radius: 0.375rem;
  color: hsl(var(--muted-foreground));
}

.sheet-close:hover {
  background: hsl(var(--muted));
  color: hsl(var(--foreground));
}

.sheet-icon {
  height: 1rem;
  width: 1rem;
}

.sheet-body {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  padding: 1rem;
}

.sheet-foot {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 0.5rem;
  border-top: 1px solid hsl(var(--border));
  padding: 0.75rem 1rem;
}

.sheet-pop-enter-active,
.sheet-pop-leave-active,
.sheet-slide-enter-active,
.sheet-slide-leave-active {
  transition: opacity 0.16s ease;
}

.sheet-pop-enter-active .sheet-panel,
.sheet-pop-leave-active .sheet-panel {
  transition: transform 0.16s ease;
}

.sheet-slide-enter-active .sheet-panel,
.sheet-slide-leave-active .sheet-panel {
  transition: transform 0.2s ease;
}

.sheet-pop-enter-from,
.sheet-pop-leave-to,
.sheet-slide-enter-from,
.sheet-slide-leave-to {
  opacity: 0;
}

.sheet-pop-enter-from .sheet-panel,
.sheet-pop-leave-to .sheet-panel {
  transform: scale(0.97);
}

.sheet-slide-enter-from .sheet-panel,
.sheet-slide-leave-to .sheet-panel {
  transform: translateX(100%);
}
</style>
