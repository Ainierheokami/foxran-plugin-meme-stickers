<template>
  <div class="config-page">
    <div class="config-inner">
      <div class="config-toolbar">
        <span class="file-badge">{{ currentFile }}</span>
        <div class="toolbar-actions">
          <slot name="header-actions" />
          <button class="btn-secondary" :disabled="loading" @click="load">
            <RefreshCw class="icon" :class="{ spinning: loading }" />
            刷新
          </button>
        </div>
      </div>

      <div v-if="loading" class="card loading">
        <Loader2 class="icon-lg spinning" />
      </div>

      <template v-else>
        <section class="card">
          <header class="card-head pink">
            <h3><Zap class="icon accent-pink" />表情包提示节奏</h3>
            <p>控制 Agent 什么时候在 prompt 里看到“可以发表情包”的提示。</p>
          </header>
          <div class="card-body">
            <div class="grid-2">
              <label class="toggle">
                <input v-model="config.prompt.enabled" type="checkbox" />
                <span>
                  <b>启用表情包提示</b>
                  <small>关闭后 Agent 不会再收到任何表情包相关提示。</small>
                </span>
              </label>
              <label class="toggle">
                <input v-model="config.prompt.always_show_capability" type="checkbox" />
                <span>
                  <b>每轮说明表情包能力</b>
                  <small>每轮用一句话告诉 Agent 可以发表情包和库里有哪些情绪，让它随时自己决定。</small>
                </span>
              </label>
              <label class="toggle">
                <input v-model="config.prompt.persist_until_sent" type="checkbox" />
                <span>
                  <b>持续提示直到发送</b>
                  <small>机会提示出现后，在限制轮数内持续提醒，直到 Agent 发出一张表情包。</small>
                </span>
              </label>
            </div>

            <div class="grid-3">
              <label class="field-label">
                <span>间隔用户消息数</span>
                <input v-model.number="config.prompt.min_messages_between_prompts" class="field" type="number" min="0" />
              </label>
              <label class="field-label">
                <span>发送后冷却秒数</span>
                <input v-model.number="config.prompt.cooldown_seconds" class="field" type="number" min="0" />
              </label>
              <label class="field-label">
                <span>最多连续提示轮数</span>
                <input v-model.number="config.prompt.max_persistent_turns" class="field" type="number" min="0" />
                <small>0 表示不限制。</small>
              </label>
            </div>

            <div class="grid-2">
              <label class="field-label">
                <span>允许平台关键词</span>
                <textarea v-model="text.allowedPlatforms" class="field area mono" rows="5" placeholder="onebot&#10;qq" />
                <small>每行或逗号分隔一个；留空表示所有平台都允许。</small>
              </label>
              <label class="field-label">
                <span>屏蔽关键词</span>
                <textarea v-model="text.blockedKeywords" class="field area mono" rows="5" placeholder="隐私&#10;紧急" />
                <small>用户消息包含这些词时不提示；英文关键词按整词匹配。</small>
              </label>
            </div>
          </div>
        </section>

        <section class="card">
          <header class="card-head violet">
            <h3><Wand class="icon accent-violet" />生成与收集</h3>
            <p>用 image_generation / image_edit 模型画新表情包或复刻表情包，并把用户发来的表情包收进库。</p>
          </header>
          <div class="card-body">
            <div class="grid-3">
              <label class="toggle">
                <input v-model="config.generation.enabled" type="checkbox" />
                <span>
                  <b>允许生成/复刻</b>
                  <small>开启 meme_sticker 的 generate 和 remake 操作。</small>
                </span>
              </label>
              <label class="toggle">
                <input v-model="config.generation.hint_enabled" type="checkbox" />
                <span>
                  <b>提示可以生成</b>
                  <small>库里没有合适的图时，提醒 Agent 可以现画一张。</small>
                </span>
              </label>
              <label class="toggle">
                <input v-model="config.collection.suggest_collect" type="checkbox" />
                <span>
                  <b>提示收集表情包</b>
                  <small>用户发来表情包时，提醒 Agent 可以收进库。</small>
                </span>
              </label>
            </div>

            <div class="grid-2">
              <label class="field-label">
                <span>生成尺寸</span>
                <input v-model="config.generation.size" class="field" placeholder="1024x1024" />
              </label>
              <label class="field-label">
                <span>每天最多生成张数</span>
                <input v-model.number="config.generation.max_per_day" class="field" type="number" min="0" />
                <small>0 表示不限制。</small>
              </label>
            </div>

            <div class="grid-2">
              <label class="field-label">
                <span>风格提示词</span>
                <textarea v-model="config.generation.style_prompt" class="field area" rows="5" />
                <small>生成和复刻时附加在画面描述前。</small>
              </label>
              <label class="field-label">
                <span>表情包识别关键词</span>
                <textarea v-model="text.stickerSummaryKeywords" class="field area mono" rows="5" placeholder="表情&#10;sticker" />
                <small>图片 summary 包含这些词时视为表情包（QQ 表情一般是 [动画表情]）。</small>
              </label>
            </div>

            <div class="note">
              保存后写回 <code>config/meme_sticker.yaml</code>，下一轮对话即生效；需要手工调整时可切到源文件模式。
            </div>
          </div>
        </section>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { Loader2, RefreshCw, Wand, Zap } from 'lucide-vue-next'
import { getStickerConfig, saveStickerConfig, type StickerConfig } from '../services/stickers'

withDefaults(defineProps<{ currentFile?: string }>(), { currentFile: 'meme_sticker.yaml' })

const loading = ref(false)
const config = ref<StickerConfig>(defaultConfig())
const text = reactive({ allowedPlatforms: '', blockedKeywords: '', stickerSummaryKeywords: '' })

function defaultConfig(): StickerConfig {
  return {
    prompt: {
      enabled: true,
      always_show_capability: true,
      min_messages_between_prompts: 2,
      cooldown_seconds: 60,
      persist_until_sent: true,
      max_persistent_turns: 3,
      allowed_platforms: [],
      blocked_keywords: [],
    },
    generation: { enabled: true, style_prompt: '', size: '1024x1024', max_per_day: 20, hint_enabled: true },
    collection: { suggest_collect: true, sticker_summary_keywords: [] },
  }
}

function listToText(value: unknown): string {
  return Array.isArray(value) ? value.join('\n') : ''
}

function textToList(value: string): string[] {
  const seen = new Set<string>()
  return value
    .split(/[\n,，]/)
    .map((item) => item.trim())
    .filter((item) => {
      if (!item || seen.has(item)) return false
      seen.add(item)
      return true
    })
}

function apply(data: StickerConfig) {
  const defaults = defaultConfig()
  config.value = {
    prompt: { ...defaults.prompt, ...data.prompt },
    generation: { ...defaults.generation, ...data.generation },
    collection: { ...defaults.collection, ...data.collection },
  }
  text.allowedPlatforms = listToText(config.value.prompt.allowed_platforms)
  text.blockedKeywords = listToText(config.value.prompt.blocked_keywords)
  text.stickerSummaryKeywords = listToText(config.value.collection.sticker_summary_keywords)
}

function nonNegative(value: unknown) {
  return Math.max(0, Number(value) || 0)
}

async function load() {
  loading.value = true
  try {
    apply(await getStickerConfig())
  } catch (err: any) {
    alert(`加载表情包配置失败: ${err?.response?.data?.detail || err?.message || err}`)
  } finally {
    loading.value = false
  }
}

async function save() {
  const { prompt, generation, collection } = config.value
  const payload: StickerConfig = {
    prompt: {
      enabled: Boolean(prompt.enabled),
      always_show_capability: Boolean(prompt.always_show_capability),
      min_messages_between_prompts: nonNegative(prompt.min_messages_between_prompts),
      cooldown_seconds: nonNegative(prompt.cooldown_seconds),
      persist_until_sent: Boolean(prompt.persist_until_sent),
      max_persistent_turns: nonNegative(prompt.max_persistent_turns),
      allowed_platforms: textToList(text.allowedPlatforms),
      blocked_keywords: textToList(text.blockedKeywords),
    },
    generation: {
      enabled: Boolean(generation.enabled),
      style_prompt: String(generation.style_prompt || '').trim(),
      size: String(generation.size || '').trim() || '1024x1024',
      max_per_day: nonNegative(generation.max_per_day),
      hint_enabled: Boolean(generation.hint_enabled),
    },
    collection: {
      suggest_collect: Boolean(collection.suggest_collect),
      sticker_summary_keywords: textToList(text.stickerSummaryKeywords),
    },
  }
  try {
    apply(await saveStickerConfig(payload))
    alert('表情包配置已保存')
  } catch (err: any) {
    alert(`保存表情包配置失败: ${err?.response?.data?.detail || err?.message || err}`)
    throw err
  }
}

onMounted(load)

defineExpose({ load, save })
</script>

<style scoped>
.config-page {
  flex: 1;
  overflow-x: hidden;
  overflow-y: auto;
}

.config-inner {
  display: flex;
  width: 100%;
  max-width: 64rem;
  margin: 0 auto;
  flex-direction: column;
  gap: 2rem;
  padding: 1.5rem 1.5rem 8rem;
}

@media (min-width: 768px) {
  .config-inner {
    padding: 2.5rem 2.5rem 8rem;
  }
}

.config-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
}

.toolbar-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-left: auto;
}

.file-badge {
  display: inline-flex;
  align-items: center;
  border-radius: 0.375rem;
  background: hsl(var(--primary));
  color: hsl(var(--primary-foreground));
  padding: 0.125rem 0.625rem;
  font-size: 0.75rem;
  font-weight: 600;
}

.btn-secondary {
  display: inline-flex;
  height: 2.25rem;
  align-items: center;
  gap: 0.5rem;
  border-radius: 0.375rem;
  border: 1px solid hsl(var(--input));
  background: hsl(var(--background));
  padding: 0 0.75rem;
  font-size: 0.875rem;
  font-weight: 500;
}

.btn-secondary:hover {
  background: hsl(var(--muted));
}

.btn-secondary:disabled {
  opacity: 0.5;
  pointer-events: none;
}

.card {
  overflow: hidden;
  border-radius: 1rem;
  border: 1px solid hsl(var(--border));
  background: hsl(var(--card));
  color: hsl(var(--card-foreground));
  box-shadow: 0 4px 12px rgb(0 0 0 / 0.06);
}

.card.loading {
  display: flex;
  justify-content: center;
  padding: 5rem 0;
  color: hsl(var(--primary) / 0.4);
}

.card-head {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  border-bottom: 1px solid hsl(var(--border));
  padding: 1.25rem;
}

.card-head.pink {
  background: linear-gradient(90deg, rgb(236 72 153 / 0.06), transparent);
}

.card-head.violet {
  background: linear-gradient(90deg, rgb(139 92 246 / 0.06), transparent);
}

.card-head h3 {
  display: flex;
  align-items: center;
  gap: 0.625rem;
  margin: 0;
  font-size: 1rem;
  font-weight: 700;
}

.card-head p {
  margin: 0;
  font-size: 0.75rem;
  color: hsl(var(--muted-foreground));
}

.card-body {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
  padding: 1.5rem;
}

.grid-2,
.grid-3 {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 1rem;
}

@media (min-width: 768px) {
  .grid-2 {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .grid-3 {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

.toggle {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
  border-radius: 0.75rem;
  border: 1px solid hsl(var(--border));
  background: hsl(var(--muted) / 0.1);
  padding: 1rem;
  cursor: pointer;
}

.toggle:hover {
  background: hsl(var(--muted) / 0.25);
}

.toggle input {
  margin-top: 0.25rem;
  height: 1rem;
  width: 1rem;
  accent-color: hsl(var(--primary));
}

.toggle span {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.toggle b {
  font-size: 0.875rem;
}

.toggle small,
.field-label small {
  font-size: 0.75rem;
  line-height: 1.5;
  color: hsl(var(--muted-foreground));
}

.field-label {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.field-label > span {
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.05em;
  color: hsl(var(--muted-foreground));
}

.field {
  height: 2.5rem;
  width: 100%;
  border-radius: 0.5rem;
  border: 1px solid hsl(var(--input));
  background: hsl(var(--background));
  color: hsl(var(--foreground));
  padding: 0 0.75rem;
  font-size: 0.875rem;
  outline: none;
}

.field:focus {
  box-shadow: 0 0 0 2px hsl(var(--primary) / 0.2);
}

.field.area {
  height: auto;
  resize: vertical;
  padding: 0.75rem;
  border-radius: 0.75rem;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}

.note {
  border-radius: 0.75rem;
  border: 1px dashed hsl(var(--border));
  background: hsl(var(--muted) / 0.2);
  padding: 1rem;
  font-size: 0.75rem;
  line-height: 1.6;
  color: hsl(var(--muted-foreground));
}

.note code {
  color: hsl(var(--foreground));
}

.icon {
  height: 1rem;
  width: 1rem;
}

.icon-lg {
  height: 2rem;
  width: 2rem;
}

.accent-pink {
  color: rgb(236 72 153);
}

.accent-violet {
  color: rgb(139 92 246);
}

.spinning {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
