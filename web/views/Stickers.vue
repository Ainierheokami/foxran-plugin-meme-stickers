<template>
  <div class="stk-page">
    <!-- 标题与入口 -->
    <header class="stk-header">
      <div class="min-w-0">
        <h2 class="stk-h2">表情包池</h2>
        <p class="stk-sub">
          共 {{ totalCount }} 张<template v-if="disabledCount"> · {{ disabledCount }} 张已停用</template>
          · 拖入或粘贴图片可直接添加
        </p>
      </div>
      <div class="stk-header-actions">
        <button class="btn-secondary h-9" @click="openDraw('generate')">
          <Wand class="i4" />
          AI 生成
        </button>
        <button class="btn-primary h-9" @click="openAdd('file')">
          <Plus class="i4" />
          添加表情包
        </button>
      </div>
    </header>

    <!-- 筛选 -->
    <section class="stk-toolbar">
      <div class="stk-search">
        <Search class="i4 stk-search-icon" />
        <input v-model="filters.q" class="field pl-9" placeholder="搜索说明、标签、URL" />
      </div>
      <select v-model="filters.tag" class="field stk-select">
        <option value="">全部标签</option>
        <option v-for="tag in availableTags" :key="tag" :value="tag">{{ tag }}</option>
      </select>
      <select v-model="filters.emotion" class="field stk-select">
        <option value="">全部情绪</option>
        <option v-for="emotion in availableEmotions" :key="emotion" :value="emotion">{{ emotion }}</option>
      </select>
      <select v-model="filters.source" class="field stk-select">
        <option value="">全部来源</option>
        <option v-for="source in sourceOptions" :key="source" :value="source">{{ sourceLabel(source) }}</option>
      </select>
      <div class="segmented" role="tablist">
        <button v-for="opt in statusOptions" :key="opt.value" :class="{ active: statusFilter === opt.value }" @click="statusFilter = opt.value">
          {{ opt.label }}
        </button>
      </div>
      <button class="icon-btn" title="刷新" :disabled="loading" @click="fetchStickers">
        <RefreshCcw class="i4" :class="{ spinning: loading }" />
      </button>
    </section>

    <!-- 表情网格 -->
    <section class="stk-grid-wrap">
      <div v-if="loading && items.length === 0" class="stk-empty">加载中...</div>
      <div v-else-if="visibleItems.length === 0" class="stk-empty">
        <template v-if="hasFilters">没有符合筛选条件的表情包</template>
        <template v-else>
          <SmilePlus class="i8 muted-icon" />
          <div>还没有表情包，拖入几张图开始建立池子</div>
          <div class="stk-empty-actions">
            <button class="btn-primary h-9" @click="openAdd('file')"><Plus class="i4" />添加表情包</button>
            <button class="btn-secondary h-9" @click="openDraw('generate')"><Wand class="i4" />AI 生成</button>
          </div>
        </template>
      </div>
      <div v-else class="stk-grid">
        <article
          v-for="item in visibleItems"
          :key="item.id"
          class="stk-card"
          :class="{ selected: selectedIds.has(item.id), disabled: !item.enabled, fresh: item.id === freshId, selecting: selectedIds.size > 0 }"
        >
          <button class="stk-thumb" :title="item.summary || item.id" @click="onCardClick(item, $event)">
            <img :src="imageSrc(item)" :alt="item.summary || item.id" loading="lazy" decoding="async" />
            <span v-if="!item.enabled" class="stk-badge">已停用</span>
            <span v-if="item.source && item.source !== 'upload'" class="stk-source" :class="`source-${item.source}`">{{ sourceLabel(item.source) }}</span>
          </button>
          <button class="stk-check" :aria-label="`选择 ${item.id}`" @click.stop="toggleSelection(item.id)">
            <CheckSquare v-if="selectedIds.has(item.id)" class="i4" />
            <Square v-else class="i4" />
          </button>
          <div class="stk-meta" @click="openEditor(item)">
            <div class="stk-summary" :class="{ placeholder: !item.summary }">{{ item.summary || '未填写说明' }}</div>
            <div class="stk-chips">
              <span v-if="item.emotion" class="chip">{{ item.emotion }}</span>
              <span v-for="tag in item.tags.slice(0, 2)" :key="tag" class="chip muted">{{ tag }}</span>
              <span v-if="item.tags.length > 2" class="chip muted">+{{ item.tags.length - 2 }}</span>
              <span v-if="!item.emotion && !item.tags.length" class="chip warn">未标注</span>
            </div>
          </div>
        </article>
      </div>
    </section>

    <!-- 批量操作栏 -->
    <Transition name="bar">
      <div v-if="selectedIds.size" class="stk-bulkbar">
        <div class="stk-bulkbar-inner">
          <span class="stk-bulk-count">已选 {{ selectedIds.size }}</span>
          <button class="btn-ghost h-8" @click="toggleSelectAll">{{ allVisibleSelected ? '取消全选' : '全选当前' }}</button>
          <span class="stk-bulk-sep" />
          <button class="btn-secondary h-8" @click="bulkDialog = true"><Tags class="i4" />批量标注</button>
          <button class="btn-secondary h-8" @click="autoTagDialog = true"><Sparkles class="i4" />LLM 打标</button>
          <button class="btn-secondary h-8" :disabled="bulkBusy" @click="bulkSetEnabled(true)"><Eye class="i4" />启用</button>
          <button class="btn-secondary h-8" :disabled="bulkBusy" @click="bulkSetEnabled(false)"><EyeOff class="i4" />停用</button>
          <button class="btn-danger h-8" :disabled="bulkBusy" @click="bulkDelete"><Trash2 class="i4" />删除</button>
          <button class="icon-btn h-8 w-8" title="清空选择" @click="clearSelection"><X class="i4" /></button>
        </div>
      </div>
    </Transition>

    <!-- 页面级拖放提示 -->
    <Teleport to="body">
      <Transition name="fade">
        <div v-if="pageDragging" class="stk-drop-overlay">
          <UploadCloud class="i8" />
          <div>松开即可添加到表情包池</div>
        </div>
      </Transition>
    </Teleport>

    <!-- 添加：本地图片 / 图片链接 -->
    <StickerSheet :open="addDialog" title="添加表情包" width="38rem" :locked="importing" @close="closeAdd">
      <div class="tabs" role="tablist">
        <button :class="{ active: addTab === 'file' }" @click="addTab = 'file'">
          <ImagePlus class="i4" />本地图片<span v-if="staged.length" class="tab-count">{{ staged.length }}</span>
        </button>
        <button :class="{ active: addTab === 'url' }" @click="addTab = 'url'">
          <LinkIcon class="i4" />图片链接<span v-if="linkUrls.length" class="tab-count">{{ linkUrls.length }}</span>
        </button>
      </div>

      <div v-show="addTab === 'file'" class="space-y">
        <label
          class="dropzone"
          :class="{ 'is-dragging': zoneDragging }"
          @dragenter.prevent="zoneDragging = true"
          @dragover.prevent="zoneDragging = true"
          @dragleave.prevent="zoneDragging = false"
          @drop.prevent.stop="onZoneDrop"
        >
          <UploadCloud class="i6 text-primary" />
          <span class="dropzone-title">拖入、粘贴或点击选择图片</span>
          <span class="hint">支持 PNG、JPG、WebP、GIF，可多选</span>
          <input class="hidden" type="file" accept="image/*" multiple @change="onFileInput" />
        </label>
        <div v-if="staged.length" class="staged-grid">
          <div v-for="(entry, index) in staged" :key="entry.url" class="staged-item">
            <img :src="entry.url" :alt="entry.file.name" />
            <button class="staged-remove" title="移除" @click="unstage(index)"><X class="i3" /></button>
          </div>
        </div>
      </div>

      <div v-show="addTab === 'url'" class="space-y">
        <textarea
          v-model="linkText"
          class="field textarea"
          rows="5"
          placeholder="一行一个图片地址，支持 http(s)、/api/media/cache/ 和 file://；也可以粘贴一段含图片链接的文本"
        />
        <div class="hint">识别到 {{ linkUrls.length }} 个链接</div>
      </div>

      <div class="divider" />
      <div class="section-label">统一标注（可留空，之后用 LLM 打标补齐）</div>
      <div class="form-grid">
        <label class="form-field span-2">
          <span>说明</span>
          <input v-model="addMeta.summary" class="field" placeholder="这些表情的共同含义" />
        </label>
        <label class="form-field">
          <span>情绪</span>
          <input v-model="addMeta.emotion" class="field" list="stk-emotions" placeholder="如 happy" />
        </label>
        <label class="form-field">
          <span>标签</span>
          <input v-model="addMeta.tags" class="field" placeholder="逗号分隔" />
        </label>
      </div>

      <template #footer>
        <span class="hint mr-auto">{{ importSummary }}</span>
        <button class="btn-secondary h-9" :disabled="importing" @click="closeAdd">取消</button>
        <button class="btn-primary h-9" :disabled="!canImport" @click="runImport">
          <Loader2 v-if="importing" class="i4 spinning" />
          导入
        </button>
      </template>
    </StickerSheet>

    <!-- AI 生成 / 复刻 -->
    <StickerSheet :open="drawDialog" title="AI 生成表情包" width="36rem" @close="drawDialog = false">
      <div class="tabs" role="tablist">
        <button v-for="mode in drawModes" :key="mode.value" :class="{ active: drawForm.mode === mode.value }" @click="drawForm.mode = mode.value">
          <component :is="mode.icon" class="i4" />{{ mode.label }}
        </button>
        <span class="tabs-status" :class="{ warn: !modeAvailable }">{{ statusText }}</span>
      </div>

      <div class="space-y">
        <template v-if="drawForm.mode === 'remake'">
          <div v-if="drawForm.reference" class="reference-card">
            <img :src="imageSrc(drawForm.reference)" :alt="drawForm.reference.summary || drawForm.reference.id" />
            <div class="min-w-0 flex-1">
              <div class="hint">参考表情包</div>
              <div class="truncate">{{ drawForm.reference.summary || drawForm.reference.id }}</div>
            </div>
            <button class="icon-btn" title="改用链接" @click="drawForm.reference = null"><X class="i4" /></button>
          </div>
          <label v-else class="form-field">
            <span>参考图</span>
            <input v-model="drawForm.referenceUrl" class="field" placeholder="图片 URL；也可以在表情详情里点“用它复刻”" />
          </label>
        </template>

        <label class="form-field">
          <span>{{ drawForm.mode === 'generate' ? '画面描述' : '修改要求' }}</span>
          <textarea
            v-model="drawForm.prompt"
            class="field textarea"
            rows="3"
            :placeholder="drawForm.mode === 'generate'
              ? '角色、动作、表情，例如“一只叉腰得意的橘色狐狸，眯眼坏笑”'
              : '可留空表示原样复刻，例如“换成一只白色小猫，保留动作”'"
          />
        </label>
        <div class="form-grid three">
          <label class="form-field">
            <span>配字</span>
            <input v-model="drawForm.caption" class="field" placeholder="可选，2~8 字" />
          </label>
          <label class="form-field">
            <span>情绪</span>
            <input v-model="drawForm.emotion" class="field" list="stk-emotions" placeholder="如 happy" />
          </label>
          <label class="form-field">
            <span>标签</span>
            <input v-model="drawForm.tags" class="field" placeholder="逗号分隔" />
          </label>
        </div>
        <div class="persona-row">
          <label class="persona-check" :class="{ muted: !personaRoles.length }">
            <input v-model="drawForm.asSelf" type="checkbox" :disabled="!personaRoles.length" />
            <span>{{ drawForm.mode === 'generate' ? '画人设角色本人' : '主角换成人设角色' }}</span>
          </label>
          <select v-if="drawForm.asSelf && personaRoles.length > 1" v-model="drawForm.roleId" class="field persona-select">
            <option v-for="role in personaRoles" :key="role.id" :value="role.id">{{ role.id }}（{{ role.ref_count }} 张）</option>
          </select>
          <span class="hint">
            {{ personaRoles.length
              ? '照人设卡的形象参考图画，外貌和她本人一致'
              : '先在「Agent 人设」页给角色上传形象参考图（需要 image_edit 模型）' }}
          </span>
        </div>
        <div v-if="drawing" class="progress-note">
          <div class="progress"><span /></div>
          {{ drawMessage || '绘图模型正在作画' }}，通常需要几十秒到两分钟；可以关掉这个窗口，画好后会自动存进表情包池。
        </div>
      </div>

      <template #footer>
        <button class="btn-secondary h-9" @click="drawDialog = false">{{ drawing ? '后台继续画' : '取消' }}</button>
        <button class="btn-primary h-9" :disabled="!canDraw" @click="drawSticker">
          <Loader2 v-if="drawing" class="i4 spinning" />
          <Wand v-else class="i4" />
          {{ drawForm.mode === 'generate' ? '生成' : '复刻' }}
        </button>
      </template>
    </StickerSheet>

    <!-- 单张编辑抽屉 -->
    <StickerSheet :open="!!editing" side="right" width="26rem" title="表情详情" @close="editing = null">
      <template v-if="editing">
        <div class="detail-preview" :class="{ disabled: !editing.enabled }">
          <img :src="normalizeMediaUrl(editing.url)" :alt="editing.summary || editing.id" />
        </div>
        <div class="detail-facts">
          <span v-if="editing.source" class="chip source" :class="`source-${editing.source}`">{{ sourceLabel(editing.source) }}</span>
          <span class="chip muted">已发送 {{ editing.usage_count || 0 }} 次</span>
          <span v-if="editing.created_at" class="chip muted">{{ formatDate(editing.created_at) }}</span>
        </div>
        <div class="detail-id" :title="editing.id">{{ editing.id }}</div>

        <div class="space-y mt-4">
          <label class="form-field">
            <span>说明</span>
            <textarea v-model="editDraft.summary" class="field textarea" rows="2" placeholder="这张表情的含义和适用场合" />
          </label>
          <label class="form-field">
            <span>情绪</span>
            <input v-model="editDraft.emotion" class="field" list="stk-emotions" placeholder="如 happy" @keydown.enter="saveEditing" />
          </label>
          <label class="form-field">
            <span>标签</span>
            <input v-model="editDraft.tagsText" class="field" placeholder="逗号分隔" @keydown.enter="saveEditing" />
          </label>
          <p class="hint">{{ TAGGING_TIP }}</p>
          <label class="switch-row">
            <span>
              <b>允许 Agent 使用</b>
              <small>停用后保留在池子里，但不会被选中发送。</small>
            </span>
            <input v-model="editDraft.enabled" type="checkbox" />
          </label>
        </div>

        <div class="detail-tools">
          <button class="btn-secondary h-8" @click="startRemake(editing)"><Copy class="i4" />用它复刻</button>
          <button class="btn-secondary h-8" :disabled="autoTagging" @click="autoTagOne(editing)"><Sparkles class="i4" />LLM 打标</button>
          <button class="btn-secondary h-8" @click="openSticker(editing)"><ExternalLink class="i4" />原图</button>
        </div>
      </template>
      <template #footer>
        <button class="btn-danger-ghost h-9 mr-auto" @click="editing && removeSticker(editing)"><Trash2 class="i4" />删除</button>
        <button class="btn-secondary h-9" @click="editing = null">关闭</button>
        <button class="btn-primary h-9" :disabled="!editDirty || savingEdit" @click="saveEditing">
          <Loader2 v-if="savingEdit" class="i4 spinning" />
          <Save v-else class="i4" />
          保存
        </button>
      </template>
    </StickerSheet>

    <!-- 批量标注 -->
    <StickerSheet :open="bulkDialog" :title="`批量标注 ${selectedIds.size} 张`" width="30rem" :locked="bulkBusy" @close="bulkDialog = false">
      <div class="space-y">
        <label class="form-field">
          <span>情绪</span>
          <input v-model="bulkForm.emotion" class="field" list="stk-emotions" placeholder="留空则不修改" />
        </label>
        <label class="form-field">
          <span>标签</span>
          <input v-model="bulkForm.tags" class="field" placeholder="逗号分隔" />
        </label>
        <div class="segmented wide">
          <button :class="{ active: bulkForm.mode === 'merge' }" @click="bulkForm.mode = 'merge'">追加到已有标签</button>
          <button :class="{ active: bulkForm.mode === 'replace' }" @click="bulkForm.mode = 'replace'">替换已有标签</button>
        </div>
        <p v-if="bulkForm.mode === 'replace' && !bulkForm.tags.trim()" class="warn-text">标签留空并选择替换，会清空所选表情的全部标签。</p>
        <p class="hint">{{ TAGGING_TIP }}</p>
      </div>
      <template #footer>
        <button class="btn-secondary h-9" :disabled="bulkBusy" @click="bulkDialog = false">取消</button>
        <button class="btn-primary h-9" :disabled="bulkBusy || (bulkForm.mode === 'merge' && !bulkForm.emotion.trim() && !bulkForm.tags.trim())" @click="applyBulkTags">
          <Loader2 v-if="bulkBusy" class="i4 spinning" />
          应用
        </button>
      </template>
    </StickerSheet>

    <!-- LLM 视觉打标 -->
    <StickerSheet :open="autoTagDialog" title="LLM 视觉打标" width="28rem" :locked="autoTagging" @close="autoTagDialog = false">
      <div class="space-y">
        <p>视觉模型会逐张查看所选的 {{ selectedIds.size }} 张表情，生成说明、情绪和标签。</p>
        <p v-if="selectedIds.size > AUTO_TAG_LIMIT" class="warn-text">一次最多 {{ AUTO_TAG_LIMIT }} 张，请减少选择。</p>
        <label class="switch-row">
          <span>
            <b>覆盖已有标注</b>
            <small>不勾选时只补齐空着的字段。</small>
          </span>
          <input v-model="autoOverwrite" type="checkbox" />
        </label>
        <div v-if="autoTagging" class="progress-note">
          <div class="progress"><span /></div>
          正在分析，图片多时会稍慢一些。
        </div>
      </div>
      <template #footer>
        <button class="btn-secondary h-9" :disabled="autoTagging" @click="autoTagDialog = false">取消</button>
        <button class="btn-primary h-9" :disabled="autoTagging || selectedIds.size === 0 || selectedIds.size > AUTO_TAG_LIMIT" @click="applyAutoTags">
          <Loader2 v-if="autoTagging" class="i4 spinning" />
          <Sparkles v-else class="i4" />
          开始打标
        </button>
      </template>
    </StickerSheet>

    <datalist id="stk-emotions">
      <option v-for="emotion in emotionSuggestions" :key="emotion" :value="emotion" />
    </datalist>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import {
  CheckSquare,
  Copy,
  ExternalLink,
  Eye,
  EyeOff,
  ImagePlus,
  Link as LinkIcon,
  Loader2,
  Plus,
  RefreshCcw,
  Save,
  Search,
  SmilePlus,
  Sparkles,
  Square,
  Tags,
  Trash2,
  UploadCloud,
  Wand,
  X,
} from 'lucide-vue-next'
import StickerSheet from '../components/StickerSheet.vue'
import {
  autoTagStickers,
  bulkTagStickers,
  createSticker,
  deleteSticker,
  generateSticker,
  getGenerationStatus,
  listStickers,
  remakeSticker,
  updateSticker,
  uploadStickers,
  type DrawJob,
  type GenerationStatus,
  type StickerItem,
} from '../services/stickers'
import { getApiOrigin } from '../services/api'

// 宿主 4.4.0 起在 window.Foxran.ui 提供 toast 和 confirm；旧宿主退回浏览器自带的提示。
const hostUi = (window as any).Foxran?.ui || {}
const toast = {
  success: (msg: string) => (hostUi.toast ? hostUi.toast.success(msg) : console.log(msg)),
  error: (msg: string) => (hostUi.toast ? hostUi.toast.error(msg) : window.alert(msg)),
  warning: (msg: string) => (hostUi.toast ? hostUi.toast.warning(msg) : window.alert(msg)),
}
const confirmAction = async (msg: string, title = '操作确认'): Promise<boolean> => (
  hostUi.confirm ? hostUi.confirm(msg, title) : window.confirm(msg)
)

const TAGGING_TIP = '情绪写用途分类，如 happy、thanks、agree、tease、awkward、surprised、comfort、sorry、confused；标签写触发场景，如 开心、赞同、捧场、疑惑、安慰、调侃、道歉、震惊、卖萌、摸鱼。'
const COMMON_EMOTIONS = ['happy', 'thanks', 'agree', 'tease', 'awkward', 'surprised', 'comfort', 'sorry', 'confused']
const AUTO_TAG_LIMIT = 12

// ---------- 列表与筛选 ----------
const items = ref<StickerItem[]>([])
const totalCount = ref(0)
const availableTags = ref<string[]>([])
const availableEmotions = ref<string[]>([])
const availableSources = ref<string[]>([])
const loading = ref(false)
const freshId = ref('')

const filters = reactive({ q: '', tag: '', emotion: '', source: '' })
type StatusFilter = 'all' | 'enabled' | 'disabled'
const statusFilter = ref<StatusFilter>('all')
const statusOptions: Array<{ value: StatusFilter; label: string }> = [
  { value: 'all', label: '全部' },
  { value: 'enabled', label: '启用' },
  { value: 'disabled', label: '停用' },
]

const SOURCE_LABELS: Record<string, string> = {
  upload: '上传',
  url: 'URL 导入',
  collected: 'Agent 收集',
  generated: 'AI 生成',
  remade: 'AI 复刻',
}
const sourceOptions = computed(() => [...new Set([...Object.keys(SOURCE_LABELS), ...availableSources.value])])
const emotionSuggestions = computed(() => [...new Set([...availableEmotions.value, ...COMMON_EMOTIONS])])

const visibleItems = computed(() => {
  if (statusFilter.value === 'enabled') return items.value.filter((item) => item.enabled)
  if (statusFilter.value === 'disabled') return items.value.filter((item) => !item.enabled)
  return items.value
})
const disabledCount = computed(() => items.value.filter((item) => !item.enabled).length)
const hasFilters = computed(() => !!(filters.q || filters.tag || filters.emotion || filters.source || statusFilter.value !== 'all'))

function sourceLabel(source: string) {
  return SOURCE_LABELS[source] || source
}

function parseTags(text: string) {
  return text
    .split(/[,，\s]+/)
    .map((tag) => tag.trim().toLowerCase())
    .filter(Boolean)
}

function formatDate(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString()
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

let fetchSeq = 0
async function fetchStickers() {
  const seq = ++fetchSeq
  loading.value = true
  try {
    const data = await listStickers({ ...filters, limit: 500 })
    if (seq !== fetchSeq) return
    items.value = (data.items || []).map((item) => ({ ...item, tags: item.tags || [] }))
    totalCount.value = data.total ?? items.value.length
    availableTags.value = data.tags || []
    availableEmotions.value = data.emotions || []
    availableSources.value = data.sources || []
    const visibleIds = new Set(items.value.map((item) => item.id))
    selectedIds.value = new Set([...selectedIds.value].filter((id) => visibleIds.has(id)))
    if (editing.value) {
      const latest = items.value.find((item) => item.id === editing.value?.id)
      if (latest) editing.value = latest
    }
  } catch (e) {
    if (seq === fetchSeq) toast.error('加载表情包失败')
  } finally {
    if (seq === fetchSeq) loading.value = false
  }
}

let filterTimer: number | undefined
watch(() => ({ ...filters }), () => {
  window.clearTimeout(filterTimer)
  filterTimer = window.setTimeout(fetchStickers, 250)
})

// ---------- 选择与批量 ----------
const selectedIds = ref(new Set<string>())
const bulkBusy = ref(false)
const bulkDialog = ref(false)
const bulkForm = reactive({ emotion: '', tags: '', mode: 'merge' as 'merge' | 'replace' })
const autoTagDialog = ref(false)
const autoTagging = ref(false)
const autoOverwrite = ref(false)

const allVisibleSelected = computed(() => visibleItems.value.length > 0 && visibleItems.value.every((item) => selectedIds.value.has(item.id)))

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
  selectedIds.value = new Set(visibleItems.value.map((item) => item.id))
}

function clearSelection() {
  selectedIds.value = new Set()
}

// 已经在多选时，点卡片切换选中；按住 Ctrl/⌘/Shift 点击也是多选。否则打开详情。
function onCardClick(item: StickerItem, event: MouseEvent) {
  if (selectedIds.value.size > 0 || event.ctrlKey || event.metaKey || event.shiftKey) {
    toggleSelection(item.id)
    return
  }
  openEditor(item)
}

async function applyBulkTags() {
  bulkBusy.value = true
  try {
    const ids = [...selectedIds.value]
    await bulkTagStickers({
      ids,
      tags: parseTags(bulkForm.tags),
      emotion: bulkForm.emotion.trim(),
      mode: bulkForm.mode,
    })
    await fetchStickers()
    bulkDialog.value = false
    bulkForm.emotion = ''
    bulkForm.tags = ''
    toast.success(`已更新 ${ids.length} 个表情包`)
  } catch (e) {
    toast.error('批量标注失败')
  } finally {
    bulkBusy.value = false
  }
}

async function runAutoTag(ids: string[], overwrite: boolean) {
  autoTagging.value = true
  try {
    const result = await autoTagStickers({ ids, overwrite })
    await fetchStickers()
    const skipped = result.skipped?.length || 0
    toast.success(`LLM 已标注 ${result.updated} 个表情包${skipped ? `，${skipped} 个未识别已跳过` : ''}`)
    return true
  } catch (e: any) {
    toast.error(e?.response?.data?.detail || 'LLM 自动打标失败')
    return false
  } finally {
    autoTagging.value = false
  }
}

async function applyAutoTags() {
  const ids = [...selectedIds.value]
  if (ids.length === 0 || ids.length > AUTO_TAG_LIMIT) return
  if (await runAutoTag(ids, autoOverwrite.value)) autoTagDialog.value = false
}

async function bulkSetEnabled(enabled: boolean) {
  const ids = [...selectedIds.value]
  bulkBusy.value = true
  try {
    const results = await Promise.allSettled(ids.map((id) => updateSticker(id, { enabled })))
    const failed = results.filter((r) => r.status === 'rejected').length
    await fetchStickers()
    if (failed) toast.error(`${failed} 个表情包状态更新失败`)
    else toast.success(`已${enabled ? '启用' : '停用'} ${ids.length} 个表情包`)
  } finally {
    bulkBusy.value = false
  }
}

async function bulkDelete() {
  const ids = [...selectedIds.value]
  if (!await confirmAction(`确定删除选中的 ${ids.length} 个表情包吗？删除后无法恢复。`, '删除表情包')) return
  bulkBusy.value = true
  try {
    const results = await Promise.allSettled(ids.map((id) => deleteSticker(id)))
    const failed = results.filter((r) => r.status === 'rejected').length
    clearSelection()
    await fetchStickers()
    if (failed) toast.error(`${failed} 个表情包删除失败`)
    else toast.success(`已删除 ${ids.length} 个表情包`)
  } finally {
    bulkBusy.value = false
  }
}

// ---------- 单张编辑 ----------
const editing = ref<StickerItem | null>(null)
const editDraft = reactive({ summary: '', emotion: '', tagsText: '', enabled: true })
const savingEdit = ref(false)

function openEditor(item: StickerItem) {
  editing.value = item
}

watch(() => editing.value?.id, () => {
  const item = editing.value
  if (!item) return
  editDraft.summary = item.summary || ''
  editDraft.emotion = item.emotion || ''
  editDraft.tagsText = (item.tags || []).join(', ')
  editDraft.enabled = item.enabled
})

// 后台刷新（例如 LLM 打标）后，未改动的字段跟着更新。
watch(editing, (item, previous) => {
  if (!item || !previous || item.id !== previous.id) return
  if (editDraft.summary === (previous.summary || '')) editDraft.summary = item.summary || ''
  if (editDraft.emotion === (previous.emotion || '')) editDraft.emotion = item.emotion || ''
  if (editDraft.tagsText === (previous.tags || []).join(', ')) editDraft.tagsText = (item.tags || []).join(', ')
  if (editDraft.enabled === previous.enabled) editDraft.enabled = item.enabled
})

const editDirty = computed(() => {
  const item = editing.value
  if (!item) return false
  return editDraft.summary !== (item.summary || '')
    || editDraft.emotion !== (item.emotion || '')
    || parseTags(editDraft.tagsText).join(',') !== (item.tags || []).join(',')
    || editDraft.enabled !== item.enabled
})

async function saveEditing() {
  const item = editing.value
  if (!item || !editDirty.value || savingEdit.value) return
  savingEdit.value = true
  try {
    await updateSticker(item.id, {
      summary: editDraft.summary.trim(),
      emotion: editDraft.emotion.trim(),
      tags: parseTags(editDraft.tagsText),
      enabled: editDraft.enabled,
    })
    await fetchStickers()
    toast.success('已保存')
  } catch (e) {
    toast.error('保存失败')
  } finally {
    savingEdit.value = false
  }
}

async function autoTagOne(item: StickerItem) {
  await runAutoTag([item.id], true)
}

async function removeSticker(item: StickerItem) {
  if (!await confirmAction(`确定删除这张表情包吗？删除后无法恢复。`, '删除表情包')) return
  try {
    await deleteSticker(item.id)
    if (editing.value?.id === item.id) editing.value = null
    const next = new Set(selectedIds.value)
    next.delete(item.id)
    selectedIds.value = next
    await fetchStickers()
    toast.success('已删除表情包')
  } catch (e) {
    toast.error('删除失败')
  }
}

// ---------- 添加：本地图片 / 链接 ----------
type AddTab = 'file' | 'url'
const addDialog = ref(false)
const addTab = ref<AddTab>('file')
const staged = ref<Array<{ file: File; url: string }>>([])
const linkText = ref('')
const addMeta = reactive({ summary: '', emotion: '', tags: '' })
const importing = ref(false)
const zoneDragging = ref(false)

function extractImageUrls(text: string) {
  const urls: string[] = []
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim()
    // 整行就是一个地址时原样接受（不要求图片后缀）
    if (/^(?:https?:\/\/|file:\/\/|\/api\/media\/cache\/)\S+$/i.test(line)) {
      urls.push(line)
      continue
    }
    const matches = line.match(/(?:https?:\/\/[^\s"'<>]+|file:\/\/\/?[^\s"'<>]+|\/api\/media\/cache\/[^\s"'<>]+)/gi) || []
    for (const match of matches) {
      const url = match.replace(/[),，。；;]+$/g, '')
      const clean = url.split('?')[0].toLowerCase()
      if (clean.startsWith('/api/media/cache/') || /\.(png|jpe?g|webp|gif|bmp|svg)$/i.test(clean)) urls.push(url)
    }
  }
  return [...new Set(urls)]
}

const linkUrls = computed(() => extractImageUrls(linkText.value))
const canImport = computed(() => !importing.value && (staged.value.length > 0 || linkUrls.value.length > 0))
const importSummary = computed(() => {
  const parts = []
  if (staged.value.length) parts.push(`${staged.value.length} 张图片`)
  if (linkUrls.value.length) parts.push(`${linkUrls.value.length} 个链接`)
  return parts.length ? `将导入 ${parts.join('、')}` : ''
})

function openAdd(tab: AddTab) {
  addTab.value = tab
  addDialog.value = true
}

function stageFiles(files: File[]) {
  const images = files.filter((file) => file.type.startsWith('image/'))
  if (images.length === 0) {
    if (files.length) toast.warning('请选择图片文件')
    return
  }
  staged.value = [...staged.value, ...images.map((file) => ({ file, url: URL.createObjectURL(file) }))]
  openAdd('file')
}

function unstage(index: number) {
  const [entry] = staged.value.splice(index, 1)
  if (entry) URL.revokeObjectURL(entry.url)
}

function resetAdd() {
  staged.value.forEach((entry) => URL.revokeObjectURL(entry.url))
  staged.value = []
  linkText.value = ''
  addMeta.summary = ''
  addMeta.emotion = ''
  addMeta.tags = ''
}

function closeAdd() {
  if (importing.value) return
  addDialog.value = false
}

function onFileInput(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || [])
  input.value = ''
  stageFiles(files)
}

function onZoneDrop(event: DragEvent) {
  zoneDragging.value = false
  pageDragging.value = false
  dragDepth = 0
  stageFiles(Array.from(event.dataTransfer?.files || []))
}

async function runImport() {
  if (!canImport.value) return
  importing.value = true
  const meta = { summary: addMeta.summary.trim(), emotion: addMeta.emotion.trim(), tags: parseTags(addMeta.tags) }
  let added = 0
  let failed = 0
  try {
    if (staged.value.length) {
      try {
        const result = await uploadStickers(staged.value.map((entry) => entry.file), meta)
        added += result.items.length
        failed += result.failures.length
      } catch (e) {
        failed += staged.value.length
      }
    }
    if (linkUrls.value.length) {
      const results = await Promise.allSettled(linkUrls.value.map((url) => createSticker({ url, ...meta })))
      added += results.filter((r) => r.status === 'fulfilled').length
      failed += results.filter((r) => r.status === 'rejected').length
    }
    await fetchStickers()
    if (added) {
      toast.success(`已添加 ${added} 个表情包${failed ? `，${failed} 个失败` : ''}`)
      resetAdd()
      addDialog.value = false
    } else {
      toast.error('导入失败')
    }
  } finally {
    importing.value = false
  }
}

// 页面任意位置拖入图片或粘贴图片/链接，都进入“添加”弹窗
const pageDragging = ref(false)
let dragDepth = 0

function hasFiles(event: DragEvent) {
  return Array.from(event.dataTransfer?.types || []).includes('Files')
}

function onWindowDragEnter(event: DragEvent) {
  if (!hasFiles(event) || addDialog.value) return
  dragDepth += 1
  pageDragging.value = true
}

function onWindowDragOver(event: DragEvent) {
  if (hasFiles(event)) event.preventDefault()
}

function onWindowDragLeave(event: DragEvent) {
  if (!hasFiles(event) || addDialog.value) return
  dragDepth = Math.max(0, dragDepth - 1)
  if (dragDepth === 0) pageDragging.value = false
}

function onWindowDrop(event: DragEvent) {
  if (!hasFiles(event)) return
  event.preventDefault()
  dragDepth = 0
  pageDragging.value = false
  stageFiles(Array.from(event.dataTransfer?.files || []))
}

function isTextTarget(target: EventTarget | null) {
  const el = target as HTMLElement | null
  return !!el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable)
}

function onWindowPaste(event: ClipboardEvent) {
  const clipboard = event.clipboardData
  if (!clipboard) return
  if (drawDialog.value || editing.value || bulkDialog.value || autoTagDialog.value) return
  const files = [
    ...Array.from(clipboard.files || []),
    ...Array.from(clipboard.items || [])
      .filter((item) => item.kind === 'file' && item.type.startsWith('image/'))
      .map((item) => item.getAsFile())
      .filter((file): file is File => !!file),
  ].filter((file) => file.type.startsWith('image/'))
  if (files.length) {
    event.preventDefault()
    // clipboard.files 与 items 往往是同一张图，按大小和类型去重
    const unique = files.filter((file, index) => files.findIndex((f) => f.size === file.size && f.type === file.type) === index)
    stageFiles(unique)
    return
  }
  if (isTextTarget(event.target)) return
  const urls = extractImageUrls(clipboard.getData('text/plain') || '')
  if (urls.length) {
    event.preventDefault()
    linkText.value = [linkText.value.trim(), ...urls].filter(Boolean).join('\n')
    openAdd('url')
  }
}

// ---------- AI 生成 / 复刻 ----------
type DrawMode = 'generate' | 'remake'
const drawModes: Array<{ value: DrawMode; label: string; icon: any }> = [
  { value: 'generate', label: '凭描述生成', icon: Wand },
  { value: 'remake', label: '照参考图复刻', icon: Copy },
]
const drawDialog = ref(false)
const drawForm = reactive({
  mode: 'generate' as DrawMode,
  prompt: '',
  caption: '',
  emotion: '',
  tags: '',
  reference: null as StickerItem | null,
  referenceUrl: '',
  asSelf: false,
  roleId: '',
})
const generationStatus = ref<GenerationStatus | null>(null)
const drawing = ref(false)
const drawMessage = ref('')
const personaRoles = computed(() => generationStatus.value?.persona_roles || [])

const quotaLeft = computed(() => {
  const status = generationStatus.value
  if (!status || !status.max_per_day) return Infinity
  return Math.max(0, status.max_per_day - status.used_today)
})

const modeAvailable = computed(() => {
  const status = generationStatus.value
  if (!status) return false
  // 照人设形象画走 image edit
  return drawForm.mode === 'generate' && !drawForm.asSelf ? status.can_generate : status.can_remake
})

const statusText = computed(() => {
  const status = generationStatus.value
  if (!status) return '正在检查绘图模型...'
  if (!status.enabled) return '已在表情包设置中关闭生成'
  if (!modeAvailable.value) {
    return drawForm.mode === 'generate' && !drawForm.asSelf ? '没有可用的 image_generation 模型' : '没有可用的 image_edit 模型'
  }
  if (quotaLeft.value <= 0) return `今日额度已用完（${status.used_today}/${status.max_per_day}）`
  const quota = status.max_per_day ? `今日 ${status.used_today}/${status.max_per_day}` : `今日已生成 ${status.used_today}`
  return `${quota} · ${status.size}`
})

const canDraw = computed(() => {
  if (drawing.value || !modeAvailable.value || quotaLeft.value <= 0) return false
  if (drawForm.mode === 'generate') return !!drawForm.prompt.trim()
  return !!(drawForm.reference || drawForm.referenceUrl.trim())
})

async function fetchGenerationStatus() {
  try {
    generationStatus.value = await getGenerationStatus()
    const roles = generationStatus.value.persona_roles || []
    if (!roles.some((role) => role.id === drawForm.roleId)) {
      const preferred = roles.find((role) => role.id === generationStatus.value?.default_role)
      drawForm.roleId = (preferred || roles[0])?.id || ''
    }
    if (!roles.length) drawForm.asSelf = false
  } catch (e) {
    generationStatus.value = null
  }
}

function openDraw(mode: DrawMode) {
  drawForm.mode = mode
  drawDialog.value = true
  fetchGenerationStatus()
}

function startRemake(item: StickerItem) {
  drawForm.reference = item
  drawForm.referenceUrl = ''
  if (!drawForm.emotion) drawForm.emotion = item.emotion || ''
  editing.value = null
  openDraw('remake')
}

async function drawSticker() {
  if (!canDraw.value) return
  drawing.value = true
  const mode = drawForm.mode
  const payload = {
    prompt: drawForm.prompt.trim(),
    caption: drawForm.caption.trim(),
    emotion: drawForm.emotion.trim(),
    tags: parseTags(drawForm.tags),
    as_self: drawForm.asSelf,
    role_id: drawForm.asSelf ? drawForm.roleId : '',
  }
  drawMessage.value = ''
  const onProgress = (job: DrawJob) => { drawMessage.value = job.message }
  try {
    const item = mode === 'generate'
      ? await generateSticker(payload, onProgress)
      : await remakeSticker(
        drawForm.reference ? { id: drawForm.reference.id } : { url: drawForm.referenceUrl.trim() },
        payload,
        onProgress,
      )
    freshId.value = item.id
    drawForm.prompt = ''
    drawForm.caption = ''
    drawDialog.value = false
    await Promise.all([fetchStickers(), fetchGenerationStatus()])
    toast.success(mode === 'generate' ? '已生成表情包并存入池子' : '已复刻表情包并存入池子')
  } catch (e: any) {
    toast.error(e?.response?.data?.detail || e?.message || (mode === 'generate' ? '生成失败' : '复刻失败'))
  } finally {
    drawing.value = false
  }
}

onMounted(() => {
  fetchStickers()
  fetchGenerationStatus()
  window.addEventListener('paste', onWindowPaste)
  window.addEventListener('dragenter', onWindowDragEnter)
  window.addEventListener('dragover', onWindowDragOver)
  window.addEventListener('dragleave', onWindowDragLeave)
  window.addEventListener('drop', onWindowDrop)
})

onBeforeUnmount(() => {
  window.clearTimeout(filterTimer)
  window.removeEventListener('paste', onWindowPaste)
  window.removeEventListener('dragenter', onWindowDragEnter)
  window.removeEventListener('dragover', onWindowDragOver)
  window.removeEventListener('dragleave', onWindowDragLeave)
  window.removeEventListener('drop', onWindowDrop)
  staged.value.forEach((entry) => URL.revokeObjectURL(entry.url))
})
</script>

<style scoped>
/* ---------- 基础 ---------- */
.stk-page {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  padding: 1rem;
  padding-bottom: 5rem;
}

@media (min-width: 768px) {
  .stk-page {
    padding: 0 0 5rem;
  }
}

.min-w-0 { min-width: 0; }
.flex-1 { flex: 1 1 0%; }
.mr-auto { margin-right: auto; }
.mt-4 { margin-top: 1rem; }
.hidden { display: none; }
.truncate { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.text-primary { color: hsl(var(--primary)); }
.space-y > * + * { margin-top: 0.75rem; }

.i3 { height: 0.75rem; width: 0.75rem; }
.i4 { height: 1rem; width: 1rem; flex: 0 0 auto; }
.i6 { height: 1.5rem; width: 1.5rem; }
.i8 { height: 2rem; width: 2rem; }
.h-8 { height: 2rem; }
.h-9 { height: 2.25rem; }
.w-8 { width: 2rem; }
.muted-icon { color: hsl(var(--muted-foreground)); opacity: 0.6; }
.spinning { animation: spin 0.9s linear infinite; }

.hint {
  color: hsl(var(--muted-foreground));
  font-size: 0.75rem;
  line-height: 1.1rem;
}

.warn-text {
  color: hsl(var(--destructive));
  font-size: 0.8125rem;
}

.field {
  height: 2.25rem;
  min-width: 0;
  width: 100%;
  border-radius: 0.375rem;
  border: 1px solid hsl(var(--input));
  background: hsl(var(--background));
  color: hsl(var(--foreground));
  padding: 0 0.75rem;
  font-size: 0.875rem;
  box-shadow: 0 1px 2px rgb(0 0 0 / 0.04);
  outline: none;
}

.field:focus {
  box-shadow: 0 0 0 1px hsl(var(--ring));
}

.field.pl-9 { padding-left: 2.25rem; }

.field.textarea {
  height: auto;
  min-height: 4.5rem;
  resize: vertical;
  padding: 0.5rem 0.75rem;
  line-height: 1.4;
}

.btn-primary,
.btn-secondary,
.btn-ghost,
.btn-danger,
.btn-danger-ghost,
.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.4rem;
  border-radius: 0.375rem;
  padding: 0 0.75rem;
  font-size: 0.875rem;
  font-weight: 500;
  white-space: nowrap;
  transition: background-color 150ms ease, color 150ms ease, border-color 150ms ease;
}

.btn-primary:disabled,
.btn-secondary:disabled,
.btn-ghost:disabled,
.btn-danger:disabled,
.btn-danger-ghost:disabled,
.icon-btn:disabled {
  pointer-events: none;
  opacity: 0.5;
}

.btn-primary {
  background: hsl(var(--primary));
  color: hsl(var(--primary-foreground));
  box-shadow: 0 1px 2px rgb(0 0 0 / 0.08);
}

.btn-primary:hover { background: hsl(var(--primary) / 0.9); }

.btn-secondary {
  border: 1px solid hsl(var(--input));
  background: hsl(var(--background));
  color: hsl(var(--foreground));
  box-shadow: 0 1px 2px rgb(0 0 0 / 0.04);
}

.btn-secondary:hover { background: hsl(var(--muted)); }

.btn-ghost { color: hsl(var(--muted-foreground)); }
.btn-ghost:hover { background: hsl(var(--muted)); color: hsl(var(--foreground)); }

.btn-danger {
  border: 1px solid hsl(var(--destructive) / 0.4);
  background: hsl(var(--destructive) / 0.08);
  color: hsl(var(--destructive));
}

.btn-danger:hover { background: hsl(var(--destructive) / 0.15); }

.btn-danger-ghost { color: hsl(var(--destructive)); padding: 0 0.5rem; }
.btn-danger-ghost:hover { background: hsl(var(--destructive) / 0.08); }

.icon-btn {
  height: 2.25rem;
  width: 2.25rem;
  padding: 0;
  border: 1px solid hsl(var(--input));
  background: hsl(var(--background));
  color: hsl(var(--muted-foreground));
}

.icon-btn:hover { background: hsl(var(--muted)); color: hsl(var(--foreground)); }

.segmented {
  display: inline-flex;
  height: 2.25rem;
  align-items: center;
  border-radius: 0.375rem;
  background: hsl(var(--muted));
  padding: 0.2rem;
}

.segmented button {
  height: 100%;
  border-radius: 0.25rem;
  padding: 0 0.7rem;
  font-size: 0.8125rem;
  color: hsl(var(--muted-foreground));
  white-space: nowrap;
}

.segmented button.active {
  background: hsl(var(--background));
  color: hsl(var(--foreground));
  box-shadow: 0 1px 2px rgb(0 0 0 / 0.08);
}

.segmented.wide { display: flex; width: 100%; }
.segmented.wide button { flex: 1 1 0; }

.chip {
  display: inline-flex;
  height: 1.375rem;
  max-width: 100%;
  align-items: center;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  border-radius: 0.25rem;
  border: 1px solid hsl(var(--primary) / 0.3);
  background: hsl(var(--primary) / 0.1);
  padding: 0 0.4rem;
  font-size: 0.7rem;
  color: hsl(var(--primary));
}

.chip.muted {
  border-color: hsl(var(--border));
  background: hsl(var(--muted));
  color: hsl(var(--muted-foreground));
}

.chip.warn {
  border-color: rgb(245 158 11 / 0.35);
  background: rgb(245 158 11 / 0.1);
  color: rgb(217 119 6);
}

.chip.source {
  border-color: hsl(var(--border));
  background: hsl(var(--background));
  color: hsl(var(--foreground));
}

.source-generated,
.source-remade {
  border-color: rgb(139 92 246 / 0.35) !important;
  background: rgb(139 92 246 / 0.12) !important;
  color: rgb(124 58 237) !important;
}

.source-collected {
  border-color: rgb(16 185 129 / 0.35) !important;
  background: rgb(16 185 129 / 0.12) !important;
  color: rgb(5 150 105) !important;
}

/* ---------- 标题与筛选 ---------- */
.stk-header {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-end;
  justify-content: space-between;
  gap: 0.75rem;
}

.stk-h2 {
  font-size: 1.5rem;
  font-weight: 600;
  letter-spacing: -0.01em;
}

.stk-sub {
  color: hsl(var(--muted-foreground));
  font-size: 0.875rem;
}

.stk-header-actions {
  display: flex;
  gap: 0.5rem;
}

.stk-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
}

.stk-search {
  position: relative;
  flex: 1 1 14rem;
  max-width: 22rem;
}

.stk-search-icon {
  pointer-events: none;
  position: absolute;
  left: 0.75rem;
  top: 0.625rem;
  color: hsl(var(--muted-foreground));
}

.stk-select {
  width: auto;
  flex: 0 1 9rem;
  padding-right: 0.5rem;
}

@media (max-width: 640px) {
  .stk-search { max-width: none; flex-basis: 100%; }
  .stk-select { flex: 1 1 30%; }
}

/* ---------- 网格 ---------- */
.stk-grid-wrap { min-height: 320px; }

.stk-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.75rem;
  border: 1px dashed hsl(var(--border));
  border-radius: 0.5rem;
  padding: 3rem 1rem;
  text-align: center;
  font-size: 0.875rem;
  color: hsl(var(--muted-foreground));
}

.stk-empty-actions {
  display: flex;
  gap: 0.5rem;
}

.stk-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(9.5rem, 1fr));
  gap: 0.75rem;
}

@media (max-width: 420px) {
  .stk-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

.stk-card {
  position: relative;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border-radius: 0.5rem;
  border: 1px solid hsl(var(--border));
  background: hsl(var(--card));
  transition: border-color 150ms ease, box-shadow 150ms ease;
}

.stk-card:hover {
  border-color: hsl(var(--primary) / 0.45);
  box-shadow: 0 4px 14px rgb(0 0 0 / 0.06);
}

.stk-card.selected {
  border-color: hsl(var(--primary));
  box-shadow: 0 0 0 2px hsl(var(--primary) / 0.25);
}

.stk-card.fresh {
  border-color: hsl(var(--primary));
  box-shadow: 0 0 0 3px hsl(var(--primary) / 0.3);
}

.stk-thumb {
  position: relative;
  display: block;
  aspect-ratio: 1 / 1;
  width: 100%;
  overflow: hidden;
  background: hsl(var(--muted));
}

.stk-thumb img {
  height: 100%;
  width: 100%;
  object-fit: contain;
}

.stk-card.disabled .stk-thumb img { opacity: 0.4; filter: grayscale(0.7); }

.stk-badge,
.stk-source {
  position: absolute;
  bottom: 0.4rem;
  border-radius: 0.25rem;
  padding: 0.05rem 0.35rem;
  font-size: 0.65rem;
  border: 1px solid transparent;
}

.stk-badge {
  left: 0.4rem;
  background: hsl(var(--foreground) / 0.75);
  color: hsl(var(--background));
}

.stk-source {
  right: 0.4rem;
  background: hsl(var(--background) / 0.85);
  color: hsl(var(--foreground));
}

.stk-check {
  position: absolute;
  left: 0.4rem;
  top: 0.4rem;
  display: inline-flex;
  height: 1.75rem;
  width: 1.75rem;
  align-items: center;
  justify-content: center;
  border-radius: 0.375rem;
  border: 1px solid hsl(var(--border));
  background: hsl(var(--background) / 0.9);
  color: hsl(var(--muted-foreground));
  opacity: 0;
  transition: opacity 120ms ease;
}

.stk-card:hover .stk-check,
.stk-card.selecting .stk-check,
.stk-card.selected .stk-check {
  opacity: 1;
}

.stk-card.selected .stk-check {
  border-color: hsl(var(--primary));
  background: hsl(var(--primary));
  color: hsl(var(--primary-foreground));
}

@media (hover: none) {
  .stk-check { opacity: 1; }
}

.stk-meta {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  padding: 0.5rem 0.6rem 0.6rem;
  cursor: pointer;
}

.stk-summary {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.8125rem;
  font-weight: 500;
}

.stk-summary.placeholder { color: hsl(var(--muted-foreground)); font-weight: 400; }

.stk-chips {
  display: flex;
  flex-wrap: nowrap;
  gap: 0.25rem;
  overflow: hidden;
}

/* ---------- 批量栏 ---------- */
.stk-bulkbar {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 1rem;
  z-index: 80;
  display: flex;
  justify-content: center;
  padding: 0 1rem;
  pointer-events: none;
}

.stk-bulkbar-inner {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 0.4rem;
  max-width: 100%;
  border-radius: 0.75rem;
  border: 1px solid hsl(var(--border));
  background: hsl(var(--card));
  padding: 0.5rem 0.6rem;
  box-shadow: 0 12px 36px rgb(0 0 0 / 0.18);
  pointer-events: auto;
}

.stk-bulk-count {
  padding: 0 0.4rem;
  font-size: 0.875rem;
  font-weight: 600;
}

.stk-bulk-sep {
  height: 1.25rem;
  width: 1px;
  background: hsl(var(--border));
}

/* ---------- 拖放 ---------- */
.stk-drop-overlay {
  position: fixed;
  inset: 0.75rem;
  z-index: 95;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.75rem;
  border: 2px dashed hsl(var(--primary));
  border-radius: 1rem;
  background: hsl(var(--background) / 0.85);
  color: hsl(var(--primary));
  font-weight: 600;
  pointer-events: none;
  backdrop-filter: blur(3px);
}

/* ---------- 弹窗内容 ---------- */
.tabs {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.25rem;
  margin-bottom: 1rem;
  border-bottom: 1px solid hsl(var(--border));
}

.tabs button {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  margin-bottom: -1px;
  border-bottom: 2px solid transparent;
  padding: 0.5rem 0.75rem;
  font-size: 0.875rem;
  color: hsl(var(--muted-foreground));
}

.tabs button.active {
  border-bottom-color: hsl(var(--primary));
  color: hsl(var(--foreground));
  font-weight: 500;
}

.tab-count {
  border-radius: 999px;
  background: hsl(var(--primary));
  color: hsl(var(--primary-foreground));
  padding: 0 0.4rem;
  font-size: 0.7rem;
  line-height: 1.1rem;
}

.tabs-status {
  margin-left: auto;
  padding: 0 0.25rem 0.4rem;
  font-size: 0.75rem;
  color: hsl(var(--muted-foreground));
}

.tabs-status.warn { color: hsl(var(--destructive)); }

.dropzone {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.35rem;
  cursor: pointer;
  border: 1px dashed hsl(var(--border));
  border-radius: 0.5rem;
  background: hsl(var(--muted) / 0.35);
  padding: 1.5rem 1rem;
  text-align: center;
  transition: background-color 150ms ease, border-color 150ms ease;
}

.dropzone:hover,
.dropzone.is-dragging {
  border-color: hsl(var(--primary));
  background: hsl(var(--primary) / 0.05);
}

.dropzone-title { font-size: 0.875rem; font-weight: 500; }

.staged-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(4.5rem, 1fr));
  gap: 0.5rem;
}

.staged-item {
  position: relative;
  aspect-ratio: 1 / 1;
  overflow: hidden;
  border-radius: 0.375rem;
  border: 1px solid hsl(var(--border));
  background: hsl(var(--muted));
}

.staged-item img { height: 100%; width: 100%; object-fit: contain; }

.staged-remove {
  position: absolute;
  right: 0.2rem;
  top: 0.2rem;
  display: inline-flex;
  height: 1.25rem;
  width: 1.25rem;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  background: rgb(0 0 0 / 0.6);
  color: white;
}

.divider {
  margin: 1rem 0 0.75rem;
  height: 1px;
  background: hsl(var(--border));
}

.section-label {
  margin-bottom: 0.5rem;
  font-size: 0.8125rem;
  font-weight: 500;
  color: hsl(var(--muted-foreground));
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.75rem;
}

.form-grid.three { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.form-grid .span-2 { grid-column: span 2 / span 2; }

@media (max-width: 520px) {
  .form-grid,
  .form-grid.three { grid-template-columns: minmax(0, 1fr); }
  .form-grid .span-2 { grid-column: auto; }
}

.form-field {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  font-size: 0.8125rem;
}

.form-field > span { font-weight: 500; }

.switch-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  border: 1px solid hsl(var(--border));
  border-radius: 0.5rem;
  padding: 0.65rem 0.75rem;
  cursor: pointer;
}

.switch-row b { display: block; font-size: 0.875rem; font-weight: 500; }
.switch-row small { display: block; font-size: 0.75rem; color: hsl(var(--muted-foreground)); }
.switch-row input { height: 1rem; width: 1rem; accent-color: hsl(var(--primary)); }

.reference-card {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  border-radius: 0.5rem;
  border: 1px solid hsl(var(--border));
  background: hsl(var(--background));
  padding: 0.5rem;
  font-size: 0.875rem;
}

.reference-card img {
  height: 3.5rem;
  width: 3.5rem;
  flex: 0 0 3.5rem;
  border-radius: 0.25rem;
  object-fit: contain;
  background: hsl(var(--muted));
}

.persona-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem 0.75rem;
}
.persona-check {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.875rem;
  cursor: pointer;
}
.persona-check.muted { opacity: 0.6; cursor: not-allowed; }
.persona-select { width: auto; min-width: 9rem; height: 2rem; }
.progress-note {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  font-size: 0.8125rem;
  color: hsl(var(--muted-foreground));
}

.progress {
  position: relative;
  height: 0.4rem;
  overflow: hidden;
  border-radius: 999px;
  background: hsl(var(--muted));
}

.progress span {
  position: absolute;
  inset-block: 0;
  width: 42%;
  border-radius: inherit;
  background: hsl(var(--primary));
  animation: sweep 1.5s ease-in-out infinite;
}

/* ---------- 详情抽屉 ---------- */
.detail-preview {
  display: flex;
  aspect-ratio: 1 / 1;
  max-height: 18rem;
  width: 100%;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  border-radius: 0.5rem;
  background:
    repeating-conic-gradient(hsl(var(--muted)) 0 25%, transparent 0 50%) 0 0 / 16px 16px,
    hsl(var(--background));
  border: 1px solid hsl(var(--border));
}

.detail-preview img { max-height: 100%; max-width: 100%; object-fit: contain; }
.detail-preview.disabled img { opacity: 0.45; }

.detail-facts {
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem;
  margin-top: 0.75rem;
}

.detail-id {
  margin-top: 0.4rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.7rem;
  color: hsl(var(--muted-foreground));
}

.detail-tools {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  margin-top: 1rem;
}

/* ---------- 动画 ---------- */
.fade-enter-active,
.fade-leave-active,
.bar-enter-active,
.bar-leave-active {
  transition: opacity 0.15s ease, transform 0.15s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

.bar-enter-from,
.bar-leave-to {
  opacity: 0;
  transform: translateY(0.75rem);
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

@keyframes sweep {
  0% { transform: translateX(-115%); }
  100% { transform: translateX(240%); }
}
</style>
