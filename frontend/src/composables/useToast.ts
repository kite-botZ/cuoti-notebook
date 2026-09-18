import { reactive } from 'vue'

export type ToastType = 'success' | 'error' | 'warning' | 'info'

export type ToastItem = {
  id: number
  type: ToastType
  message: string
}

// 全局唯一的 toast 列表
const state = reactive<{ items: ToastItem[] }>({
  items: [],
})

let nextId = 1

// 每个 toast 默认存活时间（毫秒）
const DEFAULT_DURATION = 2600

function push(type: ToastType, message: string, duration = DEFAULT_DURATION) {
  const id = nextId++
  state.items.push({ id, type, message })

  if (duration > 0) {
    window.setTimeout(() => remove(id), duration)
  }
  return id
}

function remove(id: number) {
  const idx = state.items.findIndex(t => t.id === id)
  if (idx !== -1) state.items.splice(idx, 1)
}

function clear() {
  state.items.splice(0, state.items.length)
}

// 对外的 API
export const toast = {
  success: (msg: string, duration?: number) => push('success', msg, duration),
  error: (msg: string, duration?: number) => push('error', msg, duration),
  warning: (msg: string, duration?: number) => push('warning', msg, duration),
  info: (msg: string, duration?: number) => push('info', msg, duration),
  clear,
}

// 给 ToastContainer.vue 用的只读状态
export function useToastState() {
  return state
}