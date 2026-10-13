import type { AxiosInstance } from 'axios'

export function getApiOrigin(): string {
  const raw = localStorage.getItem('api_base_url') || ''
  let base = raw.trim()
  if (!base) return window.location.origin
  if (!/^https?:\/\//i.test(base)) {
    const scheme = window.location.protocol === 'https:' ? 'https' : 'http'
    base = `${scheme}://${base}`
  }
  try {
    const url = new URL(base)
    return `${url.protocol}//${url.host}`
  } catch {
    return window.location.origin
  }
}

// The WebUI's axios instance: baseURL /api and the logged-in user's credentials.
const api = (window as any).Foxran.api as AxiosInstance

export default api
