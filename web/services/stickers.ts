import api from './api'

export type StickerItem = {
  id: string
  url: string
  summary: string
  emotion: string
  tags: string[]
  usage_count: number
  enabled: boolean
  source?: string
  storage_filename?: string
  created_at?: string
  updated_at?: string
  last_used_at?: string
  thumb_url?: string
  prompt?: string
  reference_id?: string
}

export type StickerListResponse = {
  total: number
  items: StickerItem[]
  tags: string[]
  emotions: string[]
  sources?: string[]
}

export type GenerationStatus = {
  enabled: boolean
  can_generate: boolean
  can_remake: boolean
  used_today: number
  max_per_day: number
  size: string
  /** 上传过形象参考图的人设（宿主 4.9.21 起） */
  persona_roles?: Array<{ id: string; ref_count: number }>
  default_role?: string
}

export type DrawPayload = {
  prompt?: string
  caption?: string
  summary?: string
  emotion?: string
  tags?: string[]
  /** 照人设卡的形象参考图画该角色 */
  as_self?: boolean
  role_id?: string
}

export type DrawJob = {
  id: string
  status: 'running' | 'done' | 'error'
  progress: number
  message: string
  item?: StickerItem
  error?: string
}

export type DrawProgress = (job: DrawJob) => void

const JOB_POLL_MS = 2000
const JOB_TIMEOUT_MS = 10 * 60 * 1000

/** 绘图在后台跑，轮询到画完；轮询时偶发的网络错误只重试，不算失败。 */
async function waitForJob(job: DrawJob, onProgress?: DrawProgress): Promise<StickerItem> {
  const deadline = Date.now() + JOB_TIMEOUT_MS
  let current = job
  while (current.status === 'running') {
    onProgress?.(current)
    if (Date.now() > deadline) throw new Error('绘图超时，稍后刷新表情包池看看是否已经画好')
    await new Promise((resolve) => setTimeout(resolve, JOB_POLL_MS))
    try {
      const res = await api.get<{ job: DrawJob }>(`/stickers/jobs/${job.id}`)
      current = res.data.job
    } catch (e: any) {
      if (e?.response?.status === 404) throw new Error('绘图任务丢失（后端可能重启过），稍后刷新看看')
    }
  }
  if (current.status === 'error' || !current.item) throw new Error(current.error || '绘图失败')
  return current.item
}

export async function listStickers(params: { q?: string; tag?: string; emotion?: string; source?: string; limit?: number }) {
  const res = await api.get<StickerListResponse>('/stickers', { params })
  return res.data
}

export async function createSticker(payload: {
  url: string
  summary?: string
  emotion?: string
  tags?: string[]
}) {
  const res = await api.post<{ item: StickerItem }>('/stickers', payload)
  return res.data.item
}

export async function uploadStickers(files: File[], meta: { summary?: string; emotion?: string; tags?: string[] }) {
  const formData = new FormData()
  files.forEach((file) => formData.append('files', file))
  formData.append('summary', meta.summary || '')
  formData.append('emotion', meta.emotion || '')
  formData.append('tags', (meta.tags || []).join(','))
  const res = await api.post<{ items: StickerItem[]; failures: Array<{ filename?: string; error: string }> }>(
    '/stickers/upload',
    formData,
  )
  return res.data
}

export async function updateSticker(id: string, payload: Partial<Pick<StickerItem, 'url' | 'summary' | 'emotion' | 'tags' | 'enabled'>>) {
  const res = await api.patch<{ item: StickerItem }>(`/stickers/${id}`, payload)
  return res.data.item
}

export async function bulkTagStickers(payload: {
  ids: string[]
  tags: string[]
  emotion?: string
  mode?: 'merge' | 'replace'
}) {
  const res = await api.post<{ updated: number; items: StickerItem[] }>('/stickers/bulk-tag', payload)
  return res.data
}

export async function autoTagStickers(payload: {
  ids: string[]
  overwrite?: boolean
}) {
  const res = await api.post<{ updated: number; items: StickerItem[]; skipped?: Array<{ id: string; reason: string }> }>('/stickers/auto-tag', payload)
  return res.data
}

export async function deleteSticker(id: string) {
  await api.delete(`/stickers/${id}`)
}

export async function getGenerationStatus() {
  const res = await api.get<GenerationStatus>('/stickers/generation/status')
  return res.data
}

export async function generateSticker(payload: DrawPayload, onProgress?: DrawProgress) {
  const res = await api.post<{ job: DrawJob }>('/stickers/generate', payload)
  return waitForJob(res.data.job, onProgress)
}

/** Remake a library sticker (`id`) or any image URL (`url`). */
export async function remakeSticker(reference: { id?: string; url?: string }, payload: DrawPayload, onProgress?: DrawProgress) {
  const res = reference.id
    ? await api.post<{ job: DrawJob }>(`/stickers/${reference.id}/remake`, payload)
    : await api.post<{ job: DrawJob }>('/stickers/remake', { ...payload, url: reference.url || '' })
  return waitForJob(res.data.job, onProgress)
}

export type StickerConfig = {
  prompt: {
    enabled: boolean
    always_show_capability: boolean
    min_messages_between_prompts: number
    cooldown_seconds: number
    persist_until_sent: boolean
    max_persistent_turns: number
    allowed_platforms: string[]
    blocked_keywords: string[]
  }
  generation: {
    enabled: boolean
    style_prompt: string
    size: string
    max_per_day: number
    hint_enabled: boolean
  }
  collection: {
    suggest_collect: boolean
    sticker_summary_keywords: string[]
  }
  sending: {
    max_side: number
    quality: number
    max_kb: number
    max_frames: number
  }
}

export async function getStickerConfig() {
  const res = await api.get<{ config: StickerConfig }>('/stickers/config')
  return res.data.config
}

export async function saveStickerConfig(config: StickerConfig) {
  const res = await api.post<{ config: StickerConfig }>('/stickers/config', config)
  return res.data.config
}
