import axios from 'axios'

// 给 axios 配置加一个自己的标记位。用模块增强而不是到处 `as any`，
// 这样 `raw` 打错字或在别处误用时，类型检查会直接报出来。
declare module 'axios' {
  export interface AxiosRequestConfig {
    /** 让响应拦截器把完整 response 返回（分页要读 X-Total-Count 等响应头） */
    raw?: boolean
  }
}

const request = axios.create({
  baseURL: '/api',
  timeout: 10000,  // 请求超时时间：10 秒
})

request.interceptors.request.use((config) => {
  // 从 localStorage 拿 token
  const token = localStorage.getItem('token')

  // 如果有 token，自动加到请求头里
  // 格式：Authorization: Bearer xxxxx
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }

  return config
})

// 每次收到响应后，都会先执行这个函数
request.interceptors.response.use(
  // 成功：直接把 res.data 返回，调用方拿到的就是后端的 JSON
  // 不用再写 res.data.xxx
  //
  // 例外：带 `raw: true` 的请求（分页）需要读响应头，这时把整个 response
  // 原样返回，由 getPage() 去取 X-Total-Count / X-Has-More。
  (res) => {
    if (res.config.raw) return res
    return res.data
  },

  // 失败：统一取出后端的错误信息
  // FastAPI 的错误在 err.response.data.detail 里
  (err) => {
    const msg = err.response?.data?.detail || '请求失败'
    return Promise.reject(new Error(msg))
  }
)

/**
 * 分页请求：需要读 `X-Total-Count` / `X-Has-More` 响应头时用它。
 *
 * 为什么不能只看"这一页返回了几条"来判断有没有下一页：
 * 如果总数恰好是 page_size 的整数倍，最后一页也是满的，就会以为还有下一页，
 * 用户点「加载更多」拿到一个空页。所以必须让服务端说清楚。
 *
 * 类型说明：请求带了 `raw: true`，拦截器会把完整 response 返回，
 * 正好和 axios 声明的 AxiosResponse<T> 一致，所以这里不需要强转。
 */
export async function getPage<T>(url: string, params: Record<string, unknown> = {}) {
  const res = await request.get<T>(url, { params, raw: true })
  return {
    items: res.data,
    total: Number(res.headers['x-total-count'] ?? 0),
    hasMore: String(res.headers['x-has-more']) === 'true',
  }
}

// 导出，其他文件 import 后就能用
export default request










