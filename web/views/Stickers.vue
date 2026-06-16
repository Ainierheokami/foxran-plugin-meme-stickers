<template>
  <div class="p-4 md:p-0 space-y-5">
    <div class="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
      <div>
        <h2 class="text-2xl font-semibold tracking-tight">表情包池</h2>
        <p class="text-sm text-muted-foreground">上传、打标和维护 Agent 可用于聊天的表情素材</p>
      </div>

      <div class="flex flex-wrap items-center gap-2">
        <div class="relative">
          <Search class="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
          <input
            v-model="filters.q"
            class="h-9 w-56 rounded-md border border-input bg-background pl-9 pr-3 text-sm shadow-sm outline-none focus:ring-1 focus:ring-ring"
            placeholder="搜索说明、标签、URL"
            @keydown.enter="fetchStickers"
          />
        </div>
        <select v-model="filters.tag" class="h-9 rounded-md border border-input bg-background px-3 text-sm shadow-sm outline-none focus:ring-1 focus:ring-ring">
          <option value="">全部标签</option>
          <option v-for="tag in availableTags" :key="tag" :value="tag">{{ tag }}</option>
        </select>
        <select v-model="filters.emotion" class="h-9 rounded-md border border-input bg-background px-3 text-sm shadow-sm outline-none focus:ring-1 focus:ring-ring">
          <option value="">全部情绪</option>
          <option v-for="emotion in availableEmotions" :key="emotion" :value="emotion">{{ emotion }}</option>
        </select>
        <button class="btn-secondary h-9 px-3" :disabled="loading" @click="fetchStickers">
          <RefreshCcw class="h-4 w-4" :class="{ 'animate-spin': loading }" />
          刷新
        </button>
      </div>
    </div>

    <section
      class="upload-zone"
      :class="{ 'is-dragging': dragging }"
      tabindex="0"
      @dragenter.prevent="dragging = true"
      @dragover.prevent="dragging = true"
      @dragleave.prevent="dragging = false"
      @drop.prevent="handleDrop"
      @paste="handlePaste"
    >
      <div class="flex min-w-0 flex-1 items-center gap-3">
        <div class="flex h-11 w-11 shrink-0 items-center justify-center rounded-md border bg-background">
          <UploadCloud class="h-5 w-5 text-primary" />
        </div>
        <div class="min-w-0">
          <div class="font-medium">拖入、粘贴图片或批量选择文件</div>
          <div class="text-xs text-muted-foreground">支持 PNG、JPG、WebP、GIF；也可复制多行图片 URL 后粘贴导入</div>
        </div>
      </div>

      <div class="grid w-full gap-2 md:w-auto md:grid-cols-[150px_150px_220px_auto]">
        <input
          v-model="uploadMeta.emotion"
          class="field"
          placeholder="情绪"
        />
        <input
          v-model="uploadMeta.summary"
          class="field"
          placeholder="统一说明"
        />
        <input
          v-model="uploadMeta.tags"
          class="field"
          placeholder="标签，逗号分隔"
        />
        <label class="btn-primary h-9 cursor-pointer px-3">
          <ImagePlus class="h-4 w-4" />
          选择图片
          <input ref="fileInput" class="hidden" type="file" accept="image/*" multiple @change="handleFileInput" />
        </label>
      </div>
    </section>

    <section class="rounded-md border bg-card p-3">
      <div class="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div class="min-w-0 flex-1">
          <div class="mb-2 flex items-center gap-2 text-sm font-medium">
            <ClipboardPaste class="h-4 w-4" />
            粘贴导入
          </div>
          <textarea
            v-model="pasteText"
            class="min-h-20 w-full resize-y rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm outline-none focus:ring-1 focus:ring-ring"
            placeholder="粘贴图片 URL，可一行一个；也可以直接在页面按 Ctrl+V 粘贴剪贴板图片"
            @paste="handlePaste"
          />
        </div>
        <div class="grid w-full gap-2 md:w-64">
          <button class="btn-secondary h-9 px-3" :disabled="!pasteText.trim() || pasteSaving" @click="importPastedUrls">
            <ClipboardPaste class="h-4 w-4" />
            导入文本 URL
          </button>
          <div class="text-xs text-muted-foreground">
            文本会提取 http(s)、/api/media/cache/ 与 file:// 图片地址。
          </div>
        </div>
      </div>
    </section>

    <section class="rounded-md border bg-card p-3">
      <div class="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div class="flex flex-wrap items-center gap-2 text-sm">
          <button class="btn-secondary h-8 px-3" :disabled="items.length === 0" @click="toggleSelectAll">
            <CheckSquare v-if="allVisibleSelected" class="h-4 w-4" />
            <Square v-else class="h-4 w-4" />
            {{ allVisibleSelected ? '取消全选' : '全选当前' }}
          </button>
          <span class="text-muted-foreground">已选 {{ selectedIds.size }} / {{ items.length }}</span>
          <button v-if="selectedIds.size" class="btn-ghost h-8 px-2" @click="clearSelection">
            <X class="h-4 w-4" />
            清空
          </button>
        </div>

        <div class="bulk-form">
          <input v-model="bulkEmotion" class="field h-8" placeholder="批量情绪" />
          <input v-model="bulkTags" class="field h-8" placeholder="批量标签，逗号分隔" />
          <select v-model="bulkMode" class="field h-8">
            <option value="merge">追加标签</option>
            <option value="replace">替换标签</option>
          </select>
          <button class="btn-primary h-8 px-3" :disabled="selectedIds.size === 0 || bulkSaving" @click="applyBulkTags">
            <Tags class="h-4 w-4" />
            应用
          </button>
          <label class="auto-overwrite">
            <input v-model="autoOverwrite" type="checkbox" />
            覆盖
          </label>
          <button class="btn-secondary h-8 px-3" :disabled="selectedIds.size === 0 || autoTagging" @click="applyAutoTags">
            <Sparkles class="h-4 w-4" />
            LLM 打标
          </button>
        </div>
      </div>
    </section>

    <section class="rounded-md border bg-card p-3">
      <div class="grid gap-2 md:grid-cols-[1fr_160px_220px_auto]">
        <input v-model="urlForm.url" class="field" placeholder="图片 URL 或 /api/media/cache/..." />
        <input v-model="urlForm.emotion" class="field" placeholder="情绪" />
        <input v-model="urlForm.tags" class="field" placeholder="标签，逗号分隔" />
        <button class="btn-secondary h-9 px-3" :disabled="!urlForm.url || urlSaving" @click="addUrlSticker">
          <LinkIcon class="h-4 w-4" />
          添加 URL
        </button>
      </div>
      <input v-model="urlForm.summary" class="field mt-2" placeholder="URL 表情说明" />
    </section>

    <div v-if="notice" class="rounded-md border border-primary/30 bg-primary/5 px-3 py-2 text-sm text-primary">
      {{ notice }}
    </div>
    <div v-if="error" class="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
      {{ error }}
    </div>

    <section class="rounded-md border bg-card px-3 py-2 text-xs text-muted-foreground">
      <span class="font-medium text-foreground">标注建议：</span>
      情绪写用途分类，如 happy、thanks、agree、tease、awkward、surprised、comfort、sorry、confused；标签写触发场景，如 开心、赞同、捧场、疑惑、安慰、调侃、道歉、震惊、卖萌、摸鱼。选中表情后可点 LLM 打标自动补齐。
    </section>

    <section class="min-h-[320px]">
      <div v-if="loading && items.length === 0" class="rounded-md border p-10 text-center text-sm text-muted-foreground">
        加载中...
      </div>
      <div v-else-if="items.length === 0" class="rounded-md border p-10 text-center text-sm text-muted-foreground">
        暂无表情包，拖入几张图开始建立池子
      </div>
      <div v-else class="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        <article
          v-for="item in items"
          :key="item.id"
          class="sticker-row"
          :class="{ selected: selectedIds.has(item.id), disabled: !item.enabled }"
        >
          <button class="select-box" :aria-label="`选择 ${item.id}`" @click="toggleSelection(item.id)">
            <CheckSquare v-if="selectedIds.has(item.id)" class="h-4 w-4" />
            <Square v-else class="h-4 w-4" />
          </button>

          <button class="preview" @click="openSticker(item)">
            <img :src="imageSrc(item)" :alt="item.summary || item.id" />
          </button>

          <div class="min-w-0 flex-1 space-y-2">
            <div class="flex items-start justify-between gap-2">
              <div class="min-w-0">
                <div class="truncate font-mono text-xs text-muted-foreground">{{ item.id }}</div>
                <input v-model="drafts[item.id].summary" class="inline-field mt-1 font-medium" placeholder="表情说明" />
              </div>
              <button class="icon-btn" title="删除" @click="removeSticker(item)">
                <Trash2 class="h-4 w-4" />
              </button>
            </div>

            <div class="sticker-fields">
              <input v-model="drafts[item.id].emotion" class="field h-8" placeholder="情绪" />
              <input v-model="drafts[item.id].tagsText" class="field h-8" placeholder="标签，逗号分隔" />
            </div>

            <div class="sticker-footer">
              <div class="flex flex-wrap gap-1">
                <span v-if="item.emotion" class="chip">{{ item.emotion }}</span>
                <span v-for="tag in item.tags" :key="`${item.id}-${tag}`" class="chip muted">{{ tag }}</span>
              </div>
              <div class="sticker-actions">
                <button class="icon-btn" :title="item.enabled ? '停用' : '启用'" @click="toggleEnabled(item)">
                  <Eye v-if="item.enabled" class="h-4 w-4" />
                  <EyeOff v-else class="h-4 w-4" />
                </button>
                <button class="icon-btn" title="打开图片" @click="openSticker(item)">
                  <ExternalLink class="h-4 w-4" />
                </button>
                <button class="icon-btn primary" title="保存" @click="saveSticker(item)">
                  <Save class="h-4 w-4" />
                </button>
              </div>
            </div>
          </div>
        </article>
      </div>
    </section>

    <Teleport to="body">
      <Transition name="fade">
        <div v-if="autoTagging" class="tagging-overlay">
          <div class="tagging-panel">
            <div class="tagging-spinner">
              <Sparkles class="h-6 w-6" />
            </div>
            <div class="text-lg font-semibold">正在进行视觉打标</div>
            <div class="max-w-sm text-center text-sm text-muted-foreground">
              视觉模型正在逐张分析 {{ selectedIds.size }} 个表情包，生成 summary、emotion 和 tags。图片多时会稍慢一些。
            </div>
            <div class="tagging-progress">
              <span />
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import {
  CheckSquare,
  ClipboardPaste,
  ExternalLink,
  Eye,
  EyeOff,
  ImagePlus,
  Link as LinkIcon,
  RefreshCcw,
  Save,
  Search,
  Sparkles,
  Square,
  Tags,
  Trash2,
  UploadCloud,
  X,
} from 'lucide-vue-next'
import { autoTagStickers, bulkTagStickers, createSticker, deleteSticker, listStickers, updateSticker, uploadStickers, type StickerItem } from '../services/stickers'
import { getApiOrigin } from '@/services/api'
import { toast, showConfirm } from '@/lib/feedback'

type StickerDraft = {
  summary: string
  emotion: string
  tagsText: string
}

const items = ref<StickerItem[]>([])
const availableTags = ref<string[]>([])
const availableEmotions = ref<string[]>([])
const selectedIds = ref(new Set<string>())
const drafts = reactive<Record<string, StickerDraft>>({})
const loading = ref(false)
const dragging = ref(false)
const bulkSaving = ref(false)
const autoTagging = ref(false)
const urlSaving = ref(false)
const pasteSaving = ref(false)
const notice = ref('')
const error = ref('')
const fileInput = ref<HTMLInputElement | null>(null)
const pasteText = ref('')

const filters = reactive({
  q: '',
  tag: '',
  emotion: '',
})

const uploadMeta = reactive({
  summary: '',
  emotion: '',
  tags: '',
})

const urlForm = reactive({
  url: '',
  summary: '',
  emotion: '',
  tags: '',
})

const bulkTags = ref('')
const bulkEmotion = ref('')
const bulkMode = ref<'merge' | 'replace'>('merge')
const autoOverwrite = ref(false)

const allVisibleSelected = computed(() => {
  return items.value.length > 0 && items.value.every((item) => selectedIds.value.has(item.id))
})

function parseTags(text: string) {
  return text
    .split(/[,，\s]+/)
    .map((tag) => tag.trim().toLowerCase())
    .filter(Boolean)
}

function extractImageUrls(text: string) {
  const matches = text.match(/(?:https?:\/\/[^\s"'<>]+|file:\/\/\/?[^\s"'<>]+|\/api\/media\/cache\/[^\s"'<>]+)/gi) || []
  const imageLike = matches
    .map((url) => url.replace(/[),，。；;]+$/g, ''))
    .filter((url) => {
      const clean = url.split('?')[0].toLowerCase()
      return clean.startsWith('/api/media/cache/') || /\.(png|jpe?g|webp|gif|bmp|svg)$/i.test(clean)
    })
  return [...new Set(imageLike)]
}

function showNotice(message: string) {
  toast.success(message)
}

function showError(message: string) {
  toast.error(message)
}

function syncDraft(item: StickerItem) {
  drafts[item.id] = {
    summary: item.summary || '',
    emotion: item.emotion || '',
    tagsText: (item.tags || []).join(', '),
  }
}

function normalizeMediaUrl(raw: string) {
  if (!raw) return ''
  const origin = getApiOrigin() || window.location.origin
  if (raw.startsWith('http://') || raw.startsWith('https://')) {
    try {
      const url = new URL(raw)
      if (url.pathname.startsWith('/api/media/cache/')) {
        return `${origin}${url.pathname}${url.search}`
      }
      return raw
    } catch {
      return raw
    }
  }
  return `${origin}${raw.startsWith('/') ? '' : '/'}${raw}`
}

function imageSrc(item: StickerItem) {
  if (item.thumb_url) {
    return normalizeMediaUrl(item.thumb_url)
  }
  const url = item.url || ''
  if (url.includes('/api/media/cache/')) {
    const cleanUrl = url.split('?')[0]
    return normalizeMediaUrl(`${cleanUrl}/thumb?size=160`)
  }
  return normalizeMediaUrl(url)
}

function openSticker(item: StickerItem) {
  window.open(normalizeMediaUrl(item.url), '_blank')
}

async function fetchStickers() {
  loading.value = true
  try {
    const data = await listStickers({ ...filters, limit: 300 })
    items.value = data.items || []
    availableTags.value = data.tags || []
    availableEmotions.value = data.emotions || []
    items.value.forEach(syncDraft)
    const visibleIds = new Set(items.value.map((item) => item.id))
    selectedIds.value = new Set([...selectedIds.value].filter((id) => visibleIds.has(id)))
  } catch (e) {
    showError('加载表情包失败')
  } finally {
    loading.value = false
  }
}

async function uploadFiles(files: File[]) {
  const imageFiles = files.filter((file) => file.type.startsWith('image/'))
  if (imageFiles.length === 0) {
    showError('请选择图片文件')
    return
  }
  loading.value = true
  try {
    const result = await uploadStickers(imageFiles, {
      summary: uploadMeta.summary,
      emotion: uploadMeta.emotion,
      tags: parseTags(uploadMeta.tags),
    })
    await fetchStickers()
    const failureText = result.failures.length ? `，${result.failures.length} 个失败` : ''
    showNotice(`已上传 ${result.items.length} 个表情包${failureText}`)
  } catch (e) {
    showError('上传失败')
  } finally {
    loading.value = false
  }
}

function handleFileInput(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || [])
  input.value = ''
  uploadFiles(files)
}

function handleDrop(event: DragEvent) {
  dragging.value = false
  const files = Array.from(event.dataTransfer?.files || [])
  uploadFiles(files)
}

async function handlePaste(event: ClipboardEvent) {
  const clipboard = event.clipboardData
  if (!clipboard) return

  const files = Array.from(clipboard.files || []).filter((file) => file.type.startsWith('image/'))
  if (files.length > 0) {
    event.preventDefault()
    await uploadFiles(files)
    return
  }

  const imageItems = Array.from(clipboard.items || [])
    .filter((item) => item.kind === 'file' && item.type.startsWith('image/'))
    .map((item) => item.getAsFile())
    .filter((file): file is File => !!file)
  if (imageItems.length > 0) {
    event.preventDefault()
    await uploadFiles(imageItems)
    return
  }

  const text = clipboard.getData('text/plain')
  const urls = extractImageUrls(text)
  if (urls.length > 0 && !pasteText.value.trim()) {
    pasteText.value = urls.join('\n')
  }
}

function toggleSelection(id: string) {
  const next = new Set(selectedIds.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  selectedIds.value = next
}

function toggleSelectAll() {
  if (allVisibleSelected.value) {
    clearSelection()
    return
  }
  selectedIds.value = new Set(items.value.map((item) => item.id))
}

function clearSelection() {
  selectedIds.value = new Set()
}

async function applyBulkTags() {
  bulkSaving.value = true
  try {
    const ids = [...selectedIds.value]
    await bulkTagStickers({
      ids,
      tags: parseTags(bulkTags.value),
      emotion: bulkEmotion.value,
      mode: bulkMode.value,
    })
    await fetchStickers()
    showNotice(`已更新 ${ids.length} 个表情包`)
  } catch (e) {
    showError('批量打标失败')
  } finally {
    bulkSaving.value = false
  }
}

async function applyAutoTags() {
  const ids = [...selectedIds.value]
  if (ids.length === 0) return
  if (ids.length > 12) {
    showError('一次最多选择 12 个表情包做视觉打标')
    return
  }
  autoTagging.value = true
  try {
    const result = await autoTagStickers({ ids, overwrite: autoOverwrite.value })
    await fetchStickers()
    const skipped = result.skipped?.length || 0
    showNotice(`LLM 已自动标注 ${result.updated} 个表情包${skipped ? `，${skipped} 个未识别已跳过` : ''}`)
  } catch (e: any) {
    const detail = e?.response?.data?.detail
    showError(detail || 'LLM 自动打标失败')
  } finally {
    autoTagging.value = false
  }
}

async function addUrlSticker() {
  urlSaving.value = true
  try {
    await createSticker({
      url: urlForm.url,
      summary: urlForm.summary,
      emotion: urlForm.emotion,
      tags: parseTags(urlForm.tags),
    })
    urlForm.url = ''
    urlForm.summary = ''
    await fetchStickers()
    showNotice('已添加 URL 表情包')
  } catch (e) {
    showError('添加 URL 失败')
  } finally {
    urlSaving.value = false
  }
}

async function importPastedUrls() {
  const urls = extractImageUrls(pasteText.value)
  if (urls.length === 0) {
    showError('没有识别到图片 URL')
    return
  }

  pasteSaving.value = true
  try {
    await Promise.all(urls.map((url) => createSticker({
      url,
      summary: urlForm.summary || uploadMeta.summary || '粘贴导入表情包',
      emotion: urlForm.emotion || uploadMeta.emotion,
      tags: parseTags(urlForm.tags || uploadMeta.tags),
    })))
    pasteText.value = ''
    await fetchStickers()
    showNotice(`已从粘贴文本导入 ${urls.length} 个表情包`)
  } catch (e) {
    showError('粘贴导入失败')
  } finally {
    pasteSaving.value = false
  }
}

async function saveSticker(item: StickerItem) {
  const draft = drafts[item.id]
  try {
    await updateSticker(item.id, {
      summary: draft.summary,
      emotion: draft.emotion,
      tags: parseTags(draft.tagsText),
    })
    await fetchStickers()
    showNotice('已保存表情包')
  } catch (e) {
    showError('保存失败')
  }
}

async function toggleEnabled(item: StickerItem) {
  try {
    await updateSticker(item.id, { enabled: !item.enabled })
    await fetchStickers()
  } catch (e) {
    showError('状态更新失败')
  }
}

async function removeSticker(item: StickerItem) {
  if (!await showConfirm(`确定删除表情包 ${item.id} 吗？`)) return
  try {
    await deleteSticker(item.id)
    selectedIds.value.delete(item.id)
    await fetchStickers()
    showNotice('已删除表情包')
  } catch (e) {
    showError('删除失败')
  }
}

onMounted(fetchStickers)
</script>

<style scoped>
.field {
  height: 2.25rem;
  min-width: 0;
  width: 100%;
  border-radius: 0.375rem;
  border: 1px solid hsl(var(--input));
  background: hsl(var(--background));
  padding: 0 0.75rem;
  font-size: 0.875rem;
  box-shadow: 0 1px 2px rgb(0 0 0 / 0.04);
  outline: none;
}

.field:focus {
  box-shadow: 0 0 0 1px hsl(var(--ring));
}

.inline-field {
  height: 1.75rem;
  width: 100%;
  border-radius: 0.25rem;
  border: 1px solid transparent;
  background: transparent;
  padding: 0 0.25rem;
  font-size: 0.875rem;
  outline: none;
}

.inline-field:focus {
  border-color: hsl(var(--input));
  background: hsl(var(--background));
  box-shadow: 0 0 0 1px hsl(var(--ring));
}

.btn-primary,
.btn-secondary,
.btn-ghost,
.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  border-radius: 0.375rem;
  font-size: 0.875rem;
  font-weight: 500;
  transition: background-color 150ms ease, color 150ms ease, border-color 150ms ease;
}

.btn-primary:disabled,
.btn-secondary:disabled,
.btn-ghost:disabled,
.icon-btn:disabled {
  pointer-events: none;
  opacity: 0.5;
}

.btn-primary {
  background: hsl(var(--primary));
  color: hsl(var(--primary-foreground));
  box-shadow: 0 1px 2px rgb(0 0 0 / 0.08);
}

.btn-primary:hover {
  background: hsl(var(--primary) / 0.9);
}

.btn-secondary {
  border: 1px solid hsl(var(--input));
  background: hsl(var(--background));
  box-shadow: 0 1px 2px rgb(0 0 0 / 0.04);
}

.btn-secondary:hover {
  background: hsl(var(--muted));
  color: hsl(var(--foreground));
}

.btn-ghost {
  color: hsl(var(--muted-foreground));
}

.btn-ghost:hover {
  background: hsl(var(--muted));
  color: hsl(var(--foreground));
}

.icon-btn {
  height: 2rem;
  width: 2rem;
  border: 1px solid hsl(var(--input));
  background: hsl(var(--background));
  color: hsl(var(--muted-foreground));
  box-shadow: 0 1px 2px rgb(0 0 0 / 0.04);
}

.icon-btn:hover {
  background: hsl(var(--muted));
  color: hsl(var(--foreground));
}

.icon-btn.primary {
  background: hsl(var(--primary));
  color: hsl(var(--primary-foreground));
}

.icon-btn.primary:hover {
  background: hsl(var(--primary) / 0.9);
}

.upload-zone {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  border-radius: 0.375rem;
  border: 1px dashed hsl(var(--border));
  background: hsl(var(--card));
  padding: 1rem;
  transition: background-color 150ms ease, border-color 150ms ease;
}

@media (min-width: 1024px) {
  .upload-zone {
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
  }
}

.upload-zone.is-dragging {
  border-color: hsl(var(--primary));
  background: hsl(var(--primary) / 0.05);
}

.bulk-form {
  display: grid;
  grid-template-columns: minmax(0, 8.75rem) minmax(0, 14rem) minmax(0, 7.5rem) auto auto auto;
  gap: 0.5rem;
  align-items: center;
}

@media (max-width: 920px) {
  .bulk-form {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 520px) {
  .bulk-form {
    grid-template-columns: minmax(0, 1fr);
  }
}

.auto-overwrite {
  display: inline-flex;
  height: 2rem;
  align-items: center;
  gap: 0.375rem;
  white-space: nowrap;
  color: hsl(var(--muted-foreground));
  font-size: 0.875rem;
}

.sticker-row {
  position: relative;
  display: grid;
  grid-template-columns: minmax(5.5rem, 7rem) minmax(0, 1fr);
  gap: 0.75rem;
  align-items: start;
  border-radius: 0.375rem;
  border: 1px solid hsl(var(--border));
  background: hsl(var(--card));
  padding: 0.75rem;
  transition: background-color 150ms ease, border-color 150ms ease;
}

.sticker-row:hover {
  background: hsl(var(--muted) / 0.3);
}

.sticker-row.selected {
  border-color: hsl(var(--primary));
  background: hsl(var(--primary) / 0.05);
}

.sticker-row.disabled {
  opacity: 0.6;
}

.select-box {
  position: absolute;
  left: 0.5rem;
  top: 0.5rem;
  z-index: 10;
  display: inline-flex;
  height: 1.75rem;
  width: 1.75rem;
  align-items: center;
  justify-content: center;
  border-radius: 0.375rem;
  border: 1px solid hsl(var(--border));
  background: hsl(var(--background));
  color: hsl(var(--muted-foreground));
  box-shadow: 0 1px 2px rgb(0 0 0 / 0.04);
}

.select-box:hover {
  color: hsl(var(--foreground));
}

.preview {
  height: 7rem;
  width: 100%;
  min-width: 0;
  overflow: hidden;
  border-radius: 0.375rem;
  border: 1px solid hsl(var(--border));
  background: hsl(var(--muted));
}

.sticker-fields {
  display: grid;
  grid-template-columns: minmax(0, 7rem) minmax(0, 1fr);
  gap: 0.5rem;
}

.sticker-footer {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}

.sticker-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.25rem;
}

@media (max-width: 640px) {
  .sticker-row {
    grid-template-columns: minmax(4.5rem, 6rem) minmax(0, 1fr);
  }

  .preview {
    height: 6rem;
  }

  .sticker-fields {
    grid-template-columns: minmax(0, 1fr);
  }

  .sticker-footer {
    align-items: flex-start;
    flex-direction: column;
  }
}

@media (max-width: 420px) {
  .sticker-row {
    grid-template-columns: minmax(0, 1fr);
  }

  .preview {
    height: 9rem;
  }
}

.preview img {
  height: 100%;
  width: 100%;
  object-fit: cover;
}

.chip {
  display: inline-flex;
  height: 1.5rem;
  align-items: center;
  border-radius: 0.25rem;
  border: 1px solid hsl(var(--primary) / 0.3);
  background: hsl(var(--primary) / 0.1);
  padding: 0 0.5rem;
  font-size: 0.75rem;
  color: hsl(var(--primary));
}

.chip.muted {
  border-color: hsl(var(--border));
  background: hsl(var(--muted));
  color: hsl(var(--muted-foreground));
}

.tagging-overlay {
  position: fixed;
  inset: 0;
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
  background: hsl(var(--background) / 0.78);
  backdrop-filter: blur(6px);
  padding: 1rem;
}

.tagging-panel {
  display: flex;
  width: min(26rem, 100%);
  flex-direction: column;
  align-items: center;
  gap: 0.85rem;
  border-radius: 0.5rem;
  border: 1px solid hsl(var(--border));
  background: hsl(var(--card));
  padding: 1.5rem;
  box-shadow: 0 18px 50px rgb(0 0 0 / 0.16);
}

.tagging-spinner {
  display: flex;
  height: 3rem;
  width: 3rem;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  background: hsl(var(--primary));
  color: hsl(var(--primary-foreground));
  animation: pulseTagging 1.4s ease-in-out infinite;
}

.tagging-progress {
  position: relative;
  height: 0.45rem;
  width: 100%;
  overflow: hidden;
  border-radius: 999px;
  background: hsl(var(--muted));
}

.tagging-progress span {
  position: absolute;
  inset-block: 0;
  width: 42%;
  border-radius: inherit;
  background: hsl(var(--primary));
  animation: sweepTagging 1.5s ease-in-out infinite;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.15s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

@keyframes sweepTagging {
  0% {
    transform: translateX(-115%);
  }
  100% {
    transform: translateX(240%);
  }
}

@keyframes pulseTagging {
  0%,
  100% {
    transform: scale(1);
  }
  50% {
    transform: scale(1.06);
  }
}
</style>
