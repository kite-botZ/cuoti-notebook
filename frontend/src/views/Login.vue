<template>
  <main class="auth-page">
    <section class="brand-panel" aria-label="错题本">
      <router-link to="/login" class="brand-mark" aria-label="错题本首页">错</router-link>
      <div class="brand-copy">
        <p class="eyebrow">STUDY NOTEBOOK</p>
        <h1>把每一道错题，<br />变成下一次的底气。</h1>
        <p>为复盘留出清晰、安静的空间。</p>
      </div>
      <div class="brand-footer"><span class="status-dot"></span>学习记录，持续沉淀</div>
    </section>

    <section class="auth-content">
      <div class="auth-card">
        <div class="mobile-brand"><span>错</span>错题本</div>
        <header>
          <p class="eyebrow">WELCOME BACK</p>
          <h2>登录账号</h2>
          <p class="intro">继续整理你的学习思路。</p>
        </header>

        <form @submit.prevent="handleLogin" novalidate>
          <div class="field">
            <label for="username">账号或邮箱</label>
            <input
              id="username"
              v-model.trim="form.username"
              type="text"
              autocomplete="username"
              placeholder="请输入账号或邮箱"
              @blur="validateUsername"
            />
            <p v-if="errors.username" class="error-msg">{{ errors.username }}</p>
          </div>

          <div class="field">
            <label for="password">密码</label>
            <div class="password-field">
              <input
                id="password"
                v-model="form.password"
                :type="showPassword ? 'text' : 'password'"
                autocomplete="current-password"
                placeholder="请输入密码"
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

          <div class="form-options">
            <label class="check-label">
              <input v-model="rememberMe" type="checkbox" />
              <span>记住登录状态</span>
            </label>
            <router-link to="/forgot">忘记密码</router-link>
          </div>

          <button
            class="primary-button"
            type="submit"
            :disabled="isLoading || loginSuccess"
          >
            {{ isLoading ? '正在登录...' : loginSuccess ? '登录成功' : '登录' }}
          </button>
        </form>

        <p class="auth-switch">
          还没有账号？<router-link to="/register">创建账号</router-link>
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
const form = reactive({ username: '', password: '' })
const errors = reactive({ username: '', password: '' })
const showPassword = ref(false)
const rememberMe = ref(false)
const isLoading = ref(false)
const loginSuccess = ref(false)

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

async function handleLogin() {
  if (!validateUsername() || !validatePassword()) return

  isLoading.value = true
  try {
    const data = await request.post('/login', form) as {
      token: string
      username: string
    }

    localStorage.setItem('token', data.token)
    localStorage.setItem('username', data.username)
    localStorage.setItem('rememberMe', String(rememberMe.value))

    loginSuccess.value = true
    toast.success('登录成功')
    window.setTimeout(() => router.push('/home'), 500)
  } catch (error) {
    toast.error(error instanceof Error ? error.message : '登录失败，请稍后重试')
  } finally {
    isLoading.value = false
  }
}
</script>

<style scoped>
.auth-page {
  min-height: 100vh;
  display: grid;
  grid-template-columns: minmax(360px, 42%) 1fr;
  background: #f7f8f6;
}

.brand-panel {
  min-height: 100vh;
  padding: 44px clamp(36px, 6vw, 92px);
  display: flex;
  flex-direction: column;
  color: #eff9f5;
  background: #173d35;
}
.brand-mark {
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  border: 1px solid rgba(255, 255, 255, .38);
  color: #fff;
  text-decoration: none;
  font-weight: 700;
  font-size: 18px;
}
.brand-copy {
  margin: auto 0;
}
.eyebrow {
  margin: 0 0 14px;
  color: #6b867d;
  font-size: 11px;
  letter-spacing: 1.4px;
  font-weight: 700;
}
.brand-panel .eyebrow {
  color: #a7c6bb;
}
.brand-copy h1 {
  margin: 0;
  font-size: clamp(30px, 3.1vw, 48px);
  line-height: 1.3;
  letter-spacing: 0;
  font-weight: 650;
}
.brand-copy > p:last-child {
  margin: 22px 0 0;
  color: #b8d0c7;
  font-size: 15px;
}
.brand-footer {
  display: flex;
  align-items: center;
  gap: 9px;
  color: #a7c6bb;
  font-size: 13px;
}
.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #7bd0a9;
}

.auth-content {
  display: grid;
  place-items: center;
  padding: 48px 28px;
}
.auth-card {
  width: 100%;
  max-width: 420px;
}
.mobile-brand {
  display: none;
}
header {
  margin-bottom: 34px;
}
header h2 {
  margin: 0;
  font-size: 30px;
  font-weight: 650;
  letter-spacing: 0;
  color: #18231f;
}
.intro {
  margin: 10px 0 0;
  color: #728079;
  font-size: 14px;
}
.field {
  margin-bottom: 20px;
}
label {
  display: block;
  margin-bottom: 8px;
  color: #3b4943;
  font-size: 14px;
  font-weight: 600;
}
input[type='text'],
input[type='password'] {
  width: 100%;
  height: 48px;
  border: 1px solid #d7dfda;
  border-radius: 6px;
  padding: 0 13px;
  color: #18231f;
  background: #fff;
  outline: none;
  box-sizing: border-box;
  transition: border-color .18s, box-shadow .18s;
}
input::placeholder {
  color: #a0aaa5;
}
input:focus {
  border-color: #28735f;
  box-shadow: 0 0 0 3px rgba(40, 115, 95, .12);
}
.password-field {
  position: relative;
}
.password-field input {
  padding-right: 58px;
}
.password-toggle {
  position: absolute;
  right: 8px;
  top: 50%;
  transform: translateY(-50%);
  border: 0;
  padding: 5px 7px;
  color: #28735f;
  background: transparent;
  font-size: 13px;
  cursor: pointer;
}
.error-msg {
  margin: 7px 0 0;
  color: #bf4b3f;
  font-size: 12px;
}
.form-options {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin: 2px 0 25px;
  font-size: 13px;
}
.form-options a,
.auth-switch a {
  color: #1f6956;
  text-decoration: none;
  font-weight: 600;
}
.check-label {
  display: inline-flex;
  gap: 8px;
  align-items: center;
  margin: 0;
  color: #617069;
  font-size: 13px;
  font-weight: 400;
  cursor: pointer;
}
.check-label input {
  width: 15px;
  height: 15px;
  margin: 0;
  accent-color: #28735f;
}
.primary-button {
  width: 100%;
  height: 49px;
  border: 1px solid #1f6956;
  border-radius: 6px;
  color: #fff;
  background: #1f6956;
  font-weight: 600;
  cursor: pointer;
  transition: background .18s, transform .18s;
}
.primary-button:hover:not(:disabled) {
  background: #175746;
  transform: translateY(-1px);
}
.primary-button:disabled {
  opacity: .65;
  cursor: not-allowed;
}
.auth-switch {
  margin: 25px 0 0;
  color: #718079;
  text-align: center;
  font-size: 14px;
}

@media (max-width: 760px) {
  .auth-page {
    display: block;
  }
  .brand-panel {
    display: none;
  }
  .auth-content {
    min-height: 100vh;
    padding: 34px 24px;
    align-items: start;
  }
  .auth-card {
    max-width: 480px;
  }
  .mobile-brand {
    display: flex;
    gap: 9px;
    align-items: center;
    margin-bottom: 58px;
    font-weight: 700;
    color: #21372f;
  }
  .mobile-brand span {
    display: grid;
    place-items: center;
    width: 30px;
    height: 30px;
    color: #fff;
    background: #173d35;
    font-size: 14px;
  }
  header h2 {
    font-size: 27px;
  }
}
</style>