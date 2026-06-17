import axios from 'axios'

function getApiBaseUrl(): string {
  const raw = localStorage.getItem('api_base_url') || ''
  let base = raw.trim() || '/api'
  if (base !== '/api' && !/^https?:\/\//i.test(base)) {
    const scheme = window.location.protocol === 'https:' ? 'https' : 'http'
    base = `${scheme}://${base}`
  }
  base = base.replace(/\/+$/, '')
  return base.endsWith('/api') ? base : `${base}/api`
}

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

const api = axios.create({ baseURL: getApiBaseUrl() })

api.interceptors.request.use((config: any) => {
  const token = localStorage.getItem('api_token') || ''
  const user = localStorage.getItem('api_user') || 'admin'
  const pass = localStorage.getItem('api_pass') || 'admin'
  config.baseURL = getApiBaseUrl()

  if (token && token !== 'change_me') {
    config.headers = {
      ...config.headers,
      'X-API-Token': token,
    }
  } else {
    const basic = btoa(`${user}:${pass}`)
    config.headers = {
      ...config.headers,
      Authorization: `Basic ${basic}`,
    }
  }
  return config
})

api.interceptors.response.use(
  (response) => response,
  (error) => {
    return Promise.reject(error)
  }
)

export default api
