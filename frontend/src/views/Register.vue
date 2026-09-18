<template>
  <main class="auth-page">
    <section class="brand-panel" aria-label="错题本">
      <router-link to="/login" class="brand-mark" aria-label="错题本首页">错</router-link>
      <div class="brand-copy">
        <p class="eyebrow">STUDY NOTEBOOK</p>
        <h1>从今天开始，<br />留下每一次进步。</h1>
        <p>把问题收集起来，答案会慢慢变得清晰。</p>
      </div>
      <div class="brand-footer"><span class="status-dot"></span>建立属于你的错题本</div>
    </section>

    <section class="auth-content">
      <div class="auth-card">
        <div class="mobile-brand"><span>错</span>错题本</div>
        <header>
          <p class="eyebrow">GET STARTED</p>
          <h2>创建账号</h2>
          <p class="intro">用一个账号保存所有复盘记录。</p>
        </header>

        <form @submit.prevent="handleRegister" novalidate>
          <div class="field">
            <label for="username">账号或邮箱</label>
            <input
              id="username"
              v-model.trim="form.username"
              type="text"
              autocomplete="username"
              placeholder="至少 3 个字符"
              @blur="validateUsername"
            />
            <p v-if="errors.username" class="error-msg">{{ errors.username }}</p>
          </div>

          <div class="field">
            <label for="password">设置密码</label>
            <div class="password-field">
              <input
                id="password"
                v-model="form.password"
                :type="showPassword ? 'text' : 'password'"
                autocomplete="new-password"
                placeholder="至少 6 位字符"
                @blur="validatePassword"
              />
              <button
                type="button"
                class="password-toggle"
                :aria-label="showPassword ? '隐藏密码' : '显示密码'"
                @click="showPassword = !showPassword"
              >
                {{ showPassword ? '隐藏' : '显示' }}
              </button>
            </div>
            <p v-if="errors.password" class="error-msg">{{ errors.password }}</p>
          </div>

          <div class="field">
            <label for="confirm">确认密码</label>
            <input
              id="confirm"
              v-model="form.confirm"
              type="password"
              autocomplete="new-password"
              placeholder="再次输入密码"
              @blur="validateConfirm"
            />
            <p v-if="errors.confirm" class="error-msg">{{ errors.confirm }}</p>
          </div>

          <button
            class="primary-button"
            type="submit"
            :disabled="isLoading || registerSuccess"
          >
            {{ isLoading ? '正在创建...' : registerSuccess ? '创建成功' : '创建账号' }}
          </button>
        </form>

        <p class="auth-switch">
          已有账号？<router-link to="/login">去登录</router-link>
        </p>
      </div>
    </section>
  </main>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import request from '@/api/request'
import { toast } from '@/composables/useToast'

const router = useRouter()
const form = reactive({ username: '', password: '', confirm: '' })
const errors = reactive({ username: '', password: '', confirm: '' })
const showPassword = ref(false)
const isLoading = ref(false)
const registerSuccess = ref(false)

function validateUsername() {
  if (!form.username) {
    errors.username = '请输入账号或邮箱'
    return false
  }
  if (form.username.length < 3) {
    errors.username = '账号至少需要 3 个字符'
    return false
  }
  errors.username = ''
  return true
}

function validatePassword() {
  if (!form.password) {
    errors.password = '请输入密码'
    return false
  }
  if (form.password.length < 6) {
    errors.password = '密码至少需要 6 位'
    return false
  }
  errors.password = ''
  return true
}

function validateConfirm() {
  if (!form.confirm) {
    errors.confirm = '请再次输入密码'
    return false
  }
  if (form.password !== form.confirm) {
    errors.confirm = '两次输入的密码不一致'
    return false
  }
  errors.confirm = ''
  return true
}

async function handleRegister() {
  if (!validateUsername() || !validatePassword() || !validateConfirm()) return

  isLoading.value = true
  try {
    await request.post('/register', {
      username: form.username,
      password: form.password,
    })

    registerSuccess.value = true
    toast.success('创建成功，请登录')
    window.setTimeout(() => router.push('/login'), 550)
  } catch (error) {
    toast.error(error instanceof Error ? error.message : '创建账号失败，请稍后重试')
  } finally {
    isLoading.value = false
  }
}
</script>

<style scoped>
/* 样式保持你原来的，不用动 */
</style>