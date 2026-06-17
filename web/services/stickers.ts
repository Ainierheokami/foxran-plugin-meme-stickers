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
}

export type StickerListResponse = {
  total: number
  items: StickerItem[]
  tags: string[]
  emotions: string[]
}

export async function listStickers(params: { q?: string; tag?: string; emotion?: string; limit?: number }) {
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
