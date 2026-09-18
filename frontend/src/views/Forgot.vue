<template>
  <main class="recovery-page">
    <router-link to="/login" class="brand">
      <span>错</span>错题本
    </router-link>

    <section class="recovery-card">
      <router-link to="/login" class="back-link">返回登录</router-link>

      <header>
        <p class="eyebrow">ACCOUNT RECOVERY</p>
        <h1>重设密码</h1>
        <p>验证账号后，为你的账户设置一个新密码。</p>
      </header>

      <div class="steps" aria-label="找回密码进度">
        <span :class="{ active: step >= 1 }">1</span>
        <i></i>
        <span :class="{ active: step >= 2 }">2</span>
        <i></i>
        <span :class="{ active: step >= 3 }">3</span>
      </div>

      <form v-if="step === 1" @submit.prevent="sendCode">
        <label for="account">账号或邮箱</label>
        <input
          id="account"
          v-model.trim="username"
          type="text"
          placeholder="请输入注册时使用的账号"
        />
        <p v-if="error" class="message error">{{ error }}</p>
        <button class="primary-button" :disabled="loading">
          {{ loading ? '正在发送...' : '获取验证码' }}
        </button>
      </form>

      <form v-else-if="step === 2" @submit.prevent="verifyCode">
        <label for="code">验证码</label>
        <input
          id="code"
          v-model.trim="code"
          inputmode="numeric"
          maxlength="6"
          placeholder="请输入 6 位验证码"
        />
        <p class="hint">验证码已发送至账号 {{ username }}</p>
        <p v-if="demoCode" class="message notice">开发环境验证码：{{ demoCode }}</p>
        <p v-if="error" class="message error">{{ error }}</p>
        <button class="primary-button" :disabled="loading">
          {{ loading ? '正在验证...' : '验证并继续' }}
        </button>
        <button
          type="button"
          class="text-button"
          :disabled="loading"
          @click="step = 1"
        >
          更换账号
        </button>
      </form>

      <form v-else @submit.prevent="resetPassword">
        <p class="hint">身份验证通过，请设置新密码。</p>

        <label for="new-password">新密码</label>
        <input
          id="new-password"
          v-model="newPassword"
          type="password"
          autocomplete="new-password"
          placeholder="至少 6 位字符"
        />

        <label for="confirm-password" class="next-label">确认新密码</label>
        <input
          id="confirm-password"
          v-model="confirmPassword"
          type="password"
          autocomplete="new-password"
          placeholder="再次输入新密码"
        />

        <p v-if="error" class="message error">{{ error }}</p>
        <button class="primary-button" :disabled="loading || complete">
          {{ loading ? '正在保存...' : complete ? '密码已更新' : '保存新密码' }}
        </button>
      </form>

      <p v-if="complete" class="success-message">
        密码已更新，正在返回登录页...
      </p>
    </section>
  </main>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import request from '@/api/request'

const router = useRouter()

const step = ref(1)
const username = ref('')
const code = ref('')
const demoCode = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const loading = ref(false)
const error = ref('')
const complete = ref(false)

async function sendCode() {
  error.value = ''
  if (!username.value) {
    error.value = '请输入账号或邮箱'
    return
  }

  loading.value = true
  try {
    const data = await request.post('/send-code', {
      username: username.value,
    }) as { code?: string }

    demoCode.value = data.code ?? ''
    step.value = 2
  } catch (e) {
    error.value = e instanceof Error ? e.message : '验证码发送失败'
  } finally {
    loading.value = false
  }
}

async function verifyCode() {
  error.value = ''
  if (code.value.length !== 6) {
    error.value = '请输入 6 位验证码'
    return
  }

  loading.value = true
  try {
    await request.post('/verify-code', {
      username: username.value,
      code: code.value,
    })
    step.value = 3
  } catch (e) {
    error.value = e instanceof Error ? e.message : '验证码错误'
  } finally {
    loading.value = false
  }
}

async function resetPassword() {
  error.value = ''
  if (newPassword.value.length < 6) {
    error.value = '密码至少需要 6 位'
    return
  }
  if (newPassword.value !== confirmPassword.value) {
    error.value = '两次输入的密码不一致'
    return
  }

  loading.value = true
  try {
    await request.post('/reset-password', {
      username: username.value,
      new_password: newPassword.value,
    })
    complete.value = true
    window.setTimeout(() => router.push('/login'), 700)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '密码更新失败'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.recovery-page {
  min-height: 100vh;
  padding: 34px clamp(24px, 6vw, 80px);
  background: #f7f8f6;
}

.brand {
  display: inline-flex;
  gap: 10px;
  align-items: center;
  color: #1e392f;
  text-decoration: none;
  font-weight: 700;
}
.brand span {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  color: #fff;
  background: #173d35;
  font-size: 14px;
}

.recovery-card {
  width: 100%;
  max-width: 420px;
  margin: 11vh auto 0;
}
.back-link {
  display: inline-block;
  margin-bottom: 28px;
  color: #587168;
  text-decoration: none;
  font-size: 13px;
}
.back-link:hover {
  color: #28735f;
}

.eyebrow {
  margin: 0 0 12px;
  color: #6b867d;
  font-size: 11px;
  letter-spacing: 1.4px;
  font-weight: 700;
}
h1 {
  margin: 0;
  color: #18231f;
  font-size: 30px;
  font-weight: 650;
}
header > p:last-child {
  margin: 10px 0 0;
  color: #728079;
  font-size: 14px;
}

.steps {
  display: flex;
  align-items: center;
  margin: 35px 0 30px;
}
.steps span {
  display: grid;
  place-items: center;
  width: 23px;
  height: 23px;
  border: 1px solid #cbd5cf;
  border-radius: 50%;
  color: #829087;
  background: #fff;
  font-size: 12px;
}
.steps span.active {
  border-color: #28735f;
  color: #fff;
  background: #28735f;
}
.steps i {
  height: 1px;
  flex: 1;
  margin: 0 10px;
  background: #d6dfd9;
}

label {
  display: block;
  margin: 0 0 8px;
  color: #3b4943;
  font-size: 14px;
  font-weight: 600;
}
.next-label {
  margin-top: 18px;
}
input {
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
input:focus {
  border-color: #28735f;
  box-shadow: 0 0 0 3px rgba(40, 115, 95, .12);
}

.hint {
  margin: 9px 0 0;
  color: #728079;
  font-size: 12px;
}

.message {
  margin: 14px 0;
  padding: 9px 11px;
  font-size: 13px;
  border-radius: 4px;
}
.error {
  border-left: 3px solid #bf4b3f;
  color: #a13c31;
  background: #fff4f2;
}
.notice {
  border-left: 3px solid #c7823d;
  color: #765126;
  background: #fff9ee;
}

.primary-button {
  width: 100%;
  height: 49px;
  margin-top: 22px;
  border: 1px solid #1f6956;
  border-radius: 6px;
  color: #fff;
  background: #1f6956;
  font-weight: 600;
  cursor: pointer;
  transition: background .18s;
}
.primary-button:hover:not(:disabled) {
  background: #175746;
}
.primary-button:disabled {
  opacity: .65;
  cursor: not-allowed;
}

.text-button {
  display: block;
  width: 100%;
  margin-top: 16px;
  border: 0;
  color: #28735f;
  background: transparent;
  font-size: 13px;
  cursor: pointer;
}
.text-button:hover:not(:disabled) {
  text-decoration: underline;
}
.text-button:disabled {
  opacity: .6;
  cursor: not-allowed;
}

.success-message {
  margin: 16px 0 0;
  color: #28735f;
  font-size: 13px;
}

@media (max-width: 600px) {
  .recovery-page {
    padding: 28px 24px;
  }
  .recovery-card {
    margin-top: 80px;
  }
}
</style>