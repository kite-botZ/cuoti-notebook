import axios from 'axios'

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
  (res) => res.data,

  // 失败：统一取出后端的错误信息
  // FastAPI 的错误在 err.response.data.detail 里
  (err) => {
    const msg = err.response?.data?.detail || '请求失败'
    return Promise.reject(new Error(msg))
  }
)


// 导出，其他文件 import 后就能用
export default request










