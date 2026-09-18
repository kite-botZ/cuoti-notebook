<template>
  <Teleport to="body">
    <div class="toast-container">
      <TransitionGroup name="toast">
        <div
          v-for="item in state.items"
          :key="item.id"
          class="toast"
          :class="item.type"
          @click="remove(item.id)"
        >
          <span class="toast-icon">{{ iconOf(item.type) }}</span>
          <span class="toast-msg">{{ item.message }}</span>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { useToastState } from '@/composables/useToast'
import type { ToastType } from '@/composables/useToast'

const state = useToastState()

function iconOf(type: ToastType) {
  return {
    success: '✓',
    error: '✕',
    warning: '!',
    info: 'i',
  }[type]
}

function remove(id: number) {
  const idx = state.items.findIndex(t => t.id === id)
  if (idx !== -1) state.items.splice(idx, 1)
}
</script>

<style scoped>
.toast-container {
  position: fixed;
  top: 24px;
  right: 24px;
  z-index: 9999;
  display: flex;
  flex-direction: column;
  gap: 10px;
  pointer-events: none;
}

.toast {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 240px;
  max-width: 380px;
  padding: 12px 16px;
  border: 1px solid #e0e8e3;
  border-radius: 10px;
  background: #fff;
  box-shadow: 0 8px 24px rgba(19, 49, 37, .12);
  color: #2d4238;
  font-size: 14px;
  line-height: 1.5;
  cursor: pointer;
  pointer-events: auto;
  transition: transform .18s, box-shadow .18s;
}

.toast:hover {
  transform: translateY(-1px);
  box-shadow: 0 12px 28px rgba(19, 49, 37, .16);
}

.toast-icon {
  display: grid;
  place-items: center;
  flex: 0 0 22px;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  color: #fff;
  font-size: 12px;
  font-weight: 700;
}

.toast-msg {
  flex: 1;
  word-break: break-word;
}

/* 成功 */
.toast.success {
  border-color: #ccebdd;
  background: #f1f9f5;
  color: #17644f;
}
.toast.success .toast-icon {
  background: #28735f;
}

/* 错误 */
.toast.error {
  border-color: #f3d6d1;
  background: #fff4f2;
  color: #a13c31;
}
.toast.error .toast-icon {
  background: #bf4b3f;
}

/* 警告 */
.toast.warning {
  border-color: #f0dfc0;
  background: #fff9ee;
  color: #765126;
}
.toast.warning .toast-icon {
  background: #c7823d;
}

/* 普通信息 */
.toast.info {
  border-color: #d6dfd9;
  background: #f7faf8;
  color: #4a675a;
}
.toast.info .toast-icon {
  background: #587168;
}

/* 进入 / 离开动画 */
.toast-enter-active,
.toast-leave-active {
  transition: opacity .22s ease, transform .22s ease;
}
.toast-enter-from {
  opacity: 0;
  transform: translateX(20px);
}
.toast-leave-to {
  opacity: 0;
  transform: translateX(20px);
}

@media (max-width: 600px) {
  .toast-container {
    top: 14px;
    right: 14px;
    left: 14px;
  }
  .toast {
    min-width: 0;
    max-width: none;
  }
}
</style>