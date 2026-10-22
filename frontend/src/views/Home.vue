<template>
  <main class="home-page">
    <header class="topbar">
      <router-link to="/home" class="brand">
        <span>错</span>错题本
      </router-link>
      <nav>
        <a class="active" href="#banks">我的题库</a>
        <router-link to="/knowledge">知识库</router-link>
        <router-link to="/stats">学习报告</router-link>
      </nav>
      <div class="user-actions" @click="openProfile">
        <span class="avatar">{{ userInitial }}</span>
        <span class="username-label">{{ username }}</span>
        <span class="user-arrow">›</span>
      </div>
    </header>

    <section id="banks" class="home-content">
      <div class="heading">
        <div>
          <p class="eyebrow">MY QUESTION BANKS</p>
          <h1>选择一个题库开始学习</h1>
          <p>进入题库后，可以管理题目、查看错题与笔记，并选择练习方式。</p>
        </div>
        <button class="create-button" type="button" @click="showBankDialog = true">
          新建题库
        </button>
      </div>

      <p v-if="loading" class="loading-tip">正在加载题库…</p>

      <div v-else class="bank-grid">
        <div
          v-for="bank in banks"
          :key="bank.id"
          class="bank-card"
          @click="router.push(`/banks/${bank.id}`)"
        >
          <span class="subject">{{ bank.subject }}</span>
          <strong>{{ bank.name }}</strong>
          <p>{{ bank.description || '点击进入题库中心' }}</p>
          <footer>
            <span>{{ bank.question_count }} 道题</span>
            <i>进入题库 →</i>
          </footer>
          <button
            class="delete-bank-btn"
            type="button"
            title="删除题库"
            @click.stop="confirmDeleteBank(bank)"
          >
            ✕
          </button>
        </div>

        <button
          class="bank-card new-bank"
          type="button"
          @click="showBankDialog = true"
        >
          <span class="plus">＋</span>
          <strong>创建新题库</strong>
          <p>按学科或专题整理你的题目</p>
        </button>
      </div>
    </section>

        <!-- 用户中心弹窗 -->
    <div v-if="showProfileDialog" class="modal-backdrop" @click.self="closeProfile">
      <section class="profile-modal">
        <div class="profile-head">
          <div class="profile-avatar">{{ userInitial }}</div>
          <div>
            <h2>{{ profileData.username }}</h2>
            <p>注册于 {{ formatDate(profileData.created_at) }}</p>
          </div>
          <button class="profile-close" type="button" @click="closeProfile">✕</button>
        </div>

        <div class="profile-section">
          <h3>修改密码</h3>
          <div class="profile-field">
            <label for="old-pwd">原密码</label>
            <input
              id="old-pwd"
              v-model="pwdForm.old_password"
              type="password"
              autocomplete="current-password"
              placeholder="请输入当前密码"
            />
          </div>
          <div class="profile-field">
            <label for="new-pwd">新密码</label>
            <input
              id="new-pwd"
              v-model="pwdForm.new_password"
              type="password"
              autocomplete="new-password"
              placeholder="至少 6 位"
            />
          </div>
          <div class="profile-field">
            <label for="confirm-pwd">确认新密码</label>
            <input
              id="confirm-pwd"
              v-model="pwdForm.confirm"
              type="password"
              autocomplete="new-password"
              placeholder="再次输入新密码"
            />
          </div>
          <button
            class="profile-submit"
            type="button"
            :disabled="changingPwd"
            @click="changePassword"
          >
            {{ changingPwd ? '提交中…' : '修改密码' }}
          </button>
        </div>

        <div class="profile-section">
          <button class="profile-logout" type="button" @click="logoutFromProfile">退出登录</button>
        </div>
      </section>
    </div>


    <div
      v-if="showBankDialog"
      class="modal-backdrop"
      @click.self="showBankDialog = false"
    >
      <form class="dialog" @submit.prevent="addBank">
        <div class="dialog-head">
          <div>
            <p class="eyebrow">NEW QUESTION BANK</p>
            <h2>新建题库</h2>
          </div>
          <button type="button" @click="showBankDialog = false">关闭</button>
        </div>

        <label for="bank-name">题库名称</label>
        <input
          id="bank-name"
          v-model.trim="newBank.name"
          placeholder="例如：高一数学专项练习"
          required
        />

        <div class="form-grid">
          <div>
            <label for="bank-subject">科目</label>
            <select id="bank-subject" v-model="newBank.subject">
              <option v-for="item in subjects" :key="item" :value="item">
                {{ item }}
              </option>
            </select>
          </div>
          <div>
            <label for="bank-description">简介</label>
            <input
              id="bank-description"
              v-model.trim="newBank.description"
              placeholder="例如：函数与方程"
            />
          </div>
        </div>

        <button class="save-button" type="submit" :disabled="creating">
          {{ creating ? '创建中…' : '创建题库' }}
        </button>
      </form>
    </div>
  </main>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import request from '@/api/request'
import { toast } from '@/composables/useToast'

type Bank = {
  id: number
  name: string
  subject: string
  description: string
  question_count: number
}

const router = useRouter()

const username = localStorage.getItem('username') || '同学'
const userInitial = computed(() => username.slice(0, 1).toUpperCase())
const subjects = ['数学', '英语', '物理', '化学', '综合']

const banks = ref<Bank[]>([])
const loading = ref(false)

async function loadBanks() {
  loading.value = true
  try {
    banks.value = await request.get('/banks') as unknown as Bank[]
  } catch (e: any) {
    toast.error(e.message || '题库加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(loadBanks)

const showBankDialog = ref(false)
const creating = ref(false)
const newBank = ref({ name: '', subject: '数学', description: '' })

async function addBank() {
  if (!newBank.value.name.trim()) {
    toast.warning('请输入题库名称')
    return
  }

  creating.value = true
  try {
    const created = await request.post('/banks', newBank.value) as unknown as Bank
    showBankDialog.value = false
    newBank.value = { name: '', subject: '数学', description: '' }
    await loadBanks()
    toast.success('题库创建成功')
    router.push(`/banks/${created.id}`)
  } catch (e: any) {
    toast.error(e.message || '创建失败')
  } finally {
    creating.value = false
  }
}

async function confirmDeleteBank(bank: Bank) {
  const confirmed = window.confirm(
    `确定删除题库「${bank.name}」吗？\n\n题库下的所有题目、答题记录、收藏、笔记都会一并删除，无法恢复。`
  )
  if (!confirmed) return

  try {
    await request.delete(`/banks/${bank.id}`)
    banks.value = banks.value.filter(b => b.id !== bank.id)
    toast.success('题库已删除')
  } catch (e: any) {
    toast.error(e.message || '删除失败')
  }
}

// ==================== 用户中心 ====================
const showProfileDialog = ref(false)
const changingPwd = ref(false)
const profileData = ref({ username: '', created_at: '' })

const pwdForm = reactive({
  old_password: '',
  new_password: '',
  confirm: '',
})

async function openProfile() {
  showProfileDialog.value = true
  pwdForm.old_password = ''
  pwdForm.new_password = ''
  pwdForm.confirm = ''

  try {
    const data = await request.get('/user/me') as { id: number; username: string; created_at: string }
    profileData.value = { username: data.username, created_at: data.created_at }
  } catch (e: any) {
    toast.error(e.message || '加载失败')
  }
}

function closeProfile() {
  if (changingPwd.value) return
  showProfileDialog.value = false
}

function formatDate(s: string) {
  if (!s) return '未知'
  return s.slice(0, 10)
}

async function changePassword() {
  if (!pwdForm.old_password) {
    toast.warning('请输入原密码')
    return
  }
  if (pwdForm.new_password.length < 6) {
    toast.warning('新密码至少 6 位')
    return
  }
  if (pwdForm.new_password !== pwdForm.confirm) {
    toast.warning('两次输入的新密码不一致')
    return
  }
  if (pwdForm.old_password === pwdForm.new_password) {
    toast.warning('新密码不能与原密码相同')
    return
  }

  changingPwd.value = true
  try {
    await request.post('/user/change-password', {
      old_password: pwdForm.old_password,
      new_password: pwdForm.new_password,
    })
    toast.success('密码已修改，请重新登录')
    setTimeout(() => {
      localStorage.removeItem('token')
      localStorage.removeItem('username')
      router.push('/login')
    }, 800)
  } catch (e: any) {
    toast.error(e.message || '修改失败')
  } finally {
    changingPwd.value = false
  }
}

function logoutFromProfile() {
  localStorage.removeItem('token')
  localStorage.removeItem('username')
  router.push('/login')
}
</script>

<style scoped>

/* ============ 用户中心入口 ============ */
.user-actions {
  cursor: pointer;
  padding: 6px 10px;
  border-radius: 8px;
  transition: background .18s;
}
.user-actions:hover {
  background: #f1f8f5;
}
.user-arrow {
  margin-left: 4px;
  color: #b0bcc9;
  font-size: 14px;
}

/* ============ 用户中心弹窗 ============ */
.profile-modal {
  width: min(100%, 460px);
  border-radius: 16px;
  background: #fff;
  box-shadow: 0 18px 48px rgba(19, 49, 37, .2);
  overflow: hidden;
}

.profile-head {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 24px;
  background: linear-gradient(135deg, #f1f9f5, #eaf6f0);
  position: relative;
}
.profile-avatar {
  display: grid;
  place-items: center;
  flex: 0 0 54px;
  width: 54px;
  height: 54px;
  border-radius: 50%;
  color: #fff;
  background: #c7853d;
  font-size: 22px;
  font-weight: 700;
}
.profile-head h2 {
  margin: 0;
  color: #1f2d3d;
  font-size: 19px;
}
.profile-head p {
  margin: 4px 0 0;
  color: #7a8b9b;
  font-size: 12px;
}
.profile-close {
  position: absolute;
  top: 16px;
  right: 16px;
  border: 0;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  color: #7e8c85;
  background: transparent;
  font-size: 14px;
  cursor: pointer;
  transition: background .18s;
}
.profile-close:hover {
  background: rgba(255, 255, 255, .7);
}

.profile-section {
  padding: 20px 24px;
  border-top: 1px solid #eef2f0;
}
.profile-section h3 {
  margin: 0 0 14px;
  color: #2d4238;
  font-size: 14px;
  font-weight: 650;
}

.profile-field {
  margin-bottom: 12px;
}
.profile-field label {
  display: block;
  margin-bottom: 6px;
  color: #47594f;
  font-size: 13px;
  font-weight: 600;
}
.profile-field input {
  width: 100%;
  height: 42px;
  border: 1px solid #d8e4de;
  border-radius: 8px;
  padding: 0 12px;
  color: #2d4238;
  background: #fff;
  outline: none;
  box-sizing: border-box;
  font-size: 14px;
  transition: border-color .18s, box-shadow .18s;
}
.profile-field input:focus {
  border-color: #28735f;
  box-shadow: 0 0 0 3px rgba(40, 115, 95, .12);
}

.profile-submit {
  width: 100%;
  height: 42px;
  margin-top: 6px;
  border: 1px solid #1f6956;
  border-radius: 8px;
  color: #fff;
  background: #1f6956;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: background .18s;
}
.profile-submit:hover:not(:disabled) {
  background: #175746;
}
.profile-submit:disabled {
  opacity: .6;
  cursor: not-allowed;
}

.profile-logout {
  width: 100%;
  height: 42px;
  border: 1px solid #f3d6d1;
  border-radius: 8px;
  color: #bf4b3f;
  background: #fff;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: background .18s;
}
.profile-logout:hover {
  background: #fff4f2;
}



.home-page {
  min-height: 100vh;
  color: #20332b;
  background: #f5f8f6;
}

.topbar {
  height: 66px;
  display: flex;
  align-items: center;
  gap: 44px;
  padding: 0 clamp(20px, 6vw, 80px);
  border-bottom: 1px solid #e0e8e3;
  background: #fff;
}
.brand {
  display: inline-flex;
  align-items: center;
  gap: 9px;
  color: #1e3e33;
  text-decoration: none;
  font-weight: 700;
}
.brand span {
  display: grid;
  place-items: center;
  width: 29px;
  height: 29px;
  color: #fff;
  background: #173d35;
  font-size: 13px;
}
.topbar nav {
  height: 100%;
}
.topbar nav a {
  display: grid;
  place-items: center;
  height: 100%;
  border-bottom: 2px solid #28735f;
  color: #1e6854;
  text-decoration: none;
  font-size: 14px;
  font-weight: 600;
}

.topbar nav {
  display: flex;
  gap: 24px;
}
.topbar nav a,
.topbar nav .router-link-active {
  display: grid;
  place-items: center;
  height: 100%;
  color: #5a6b7c;
  text-decoration: none;
  font-size: 14px;
  font-weight: 600;
  transition: color .18s;
  border-bottom: 2px solid transparent;
}
.topbar nav a:hover {
  color: #1e6854;
}
.topbar nav a.active {
  border-bottom-color: #28735f;
  color: #1e6854;
}

.user-actions {
  display: flex;
  align-items: center;
  gap: 9px;
  margin-left: auto;
  color: #4b5d54;
  font-size: 14px;
}
.avatar {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  color: #fff;
  background: #c7853d;
  font-size: 12px;
}
.user-actions button {
  border: 0;
  margin-left: 8px;
  color: #738078;
  background: transparent;
  font-size: 13px;
  cursor: pointer;
}
.user-actions button:hover {
  color: #bf4b3f;
}

.home-content {
  max-width: 1080px;
  margin: 0 auto;
  padding: 60px 28px 80px;
}
.heading {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 22px;
}
.eyebrow {
  margin: 0 0 11px;
  color: #6e8f82;
  font-size: 11px;
  letter-spacing: 1.35px;
  font-weight: 700;
}
.heading h1 {
  margin: 0;
  font-size: clamp(28px, 4vw, 38px);
  font-weight: 650;
}
.heading p:last-child {
  margin: 11px 0 0;
  color: #74827b;
  font-size: 14px;
}
.create-button,
.save-button {
  border: 1px solid #1f795f;
  border-radius: 8px;
  padding: 12px 16px;
  color: #fff;
  background: #1f795f;
  font-weight: 600;
  cursor: pointer;
  transition: background .18s;
}
.create-button:hover,
.save-button:hover:not(:disabled) {
  background: #175746;
}
.save-button:disabled {
  opacity: .6;
  cursor: not-allowed;
}
.loading-tip {
  margin-top: 40px;
  color: #85928b;
  font-size: 14px;
}

.bank-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 15px;
  margin-top: 42px;
}
.bank-card {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  min-height: 210px;
  border: 1px solid #dfe8e2;
  border-radius: 14px;
  padding: 21px;
  color: #2d4138;
  background: #fff;
  text-align: left;
  cursor: pointer;
  transition: transform .18s, border-color .18s, box-shadow .18s;
}
.bank-card:hover {
  border-color: #8ec5b0;
  box-shadow: 0 10px 22px rgba(29, 76, 60, .09);
  transform: translateY(-2px);
}
.subject {
  padding: 6px 9px;
  border-radius: 6px;
  color: #28755e;
  background: #e6f4ed;
  font-size: 12px;
}
.bank-card strong {
  margin-top: 22px;
  font-size: 18px;
}
.bank-card p {
  margin: 9px 0 0;
  color: #77857e;
  font-size: 13px;
  line-height: 1.6;
}
.bank-card footer {
  display: flex;
  justify-content: space-between;
  width: 100%;
  margin-top: auto;
  color: #909b95;
  font-size: 12px;
}
.bank-card footer i {
  color: #2a8167;
  font-style: normal;
  font-weight: 600;
}
.new-bank {
  justify-content: center;
  border-style: dashed;
  background: transparent;
}
.new-bank strong {
  margin-top: 15px;
}
.new-bank p {
  margin-bottom: auto;
}
.plus {
  display: grid;
  place-items: center;
  width: 43px;
  height: 43px;
  border-radius: 50%;
  color: #2a8066;
  background: #e4f4ed;
  font-size: 24px;
}

.delete-bank-btn {
  position: absolute;
  top: 12px;
  right: 12px;
  width: 26px;
  height: 26px;
  display: grid;
  place-items: center;
  border: 1px solid transparent;
  border-radius: 50%;
  background: transparent;
  color: #b0bcc9;
  font-size: 13px;
  line-height: 1;
  cursor: pointer;
  opacity: 0;
  transition: opacity .18s, color .18s, background .18s, border-color .18s;
}
.bank-card:hover .delete-bank-btn {
  opacity: 1;
}
.delete-bank-btn:hover {
  border-color: #bf4b3f;
  color: #bf4b3f;
  background: #fff4f2;
}

.modal-backdrop {
  position: fixed;
  z-index: 5;
  inset: 0;
  display: grid;
  place-items: center;
  padding: 20px;
  background: rgba(20, 45, 35, .35);
}
.dialog {
  width: min(100%, 510px);
  border-radius: 15px;
  padding: 25px;
  background: #fff;
  box-shadow: 0 18px 48px rgba(19, 49, 37, .2);
}
.dialog-head {
  display: flex;
  justify-content: space-between;
  align-items: start;
  margin-bottom: 22px;
}
.dialog-head h2 {
  margin: 0;
  font-size: 21px;
}
.dialog-head button {
  border: 0;
  color: #7b8982;
  background: transparent;
  font-size: 13px;
  cursor: pointer;
}
.dialog label {
  display: block;
  margin: 16px 0 8px;
  color: #46584e;
  font-size: 13px;
  font-weight: 600;
}
.dialog input,
.dialog select {
  width: 100%;
  height: 42px;
  border: 1px solid #d7e2dc;
  border-radius: 8px;
  padding: 0 10px;
  color: #34473d;
  background: #fff;
  outline: none;
  box-sizing: border-box;
}
.dialog input:focus,
.dialog select:focus {
  border-color: #28735f;
  box-shadow: 0 0 0 3px rgba(40, 115, 95, .12);
}
.form-grid {
  display: grid;
  grid-template-columns: 140px 1fr;
  gap: 14px;
}
.save-button {
  width: 100%;
  margin-top: 24px;
}

@media (max-width: 720px) {
  .topbar {
    padding: 0 20px;
  }
  .topbar nav,
  .user-actions > span:not(.avatar) {
    display: none;
  }
  .home-content {
    padding: 38px 20px 60px;
  }
  .heading {
    align-items: flex-start;
    flex-direction: column;
  }
  .bank-grid {
    grid-template-columns: 1fr;
    margin-top: 28px;
  }
  .bank-card {
    min-height: 175px;
  }
  .form-grid {
    grid-template-columns: 1fr;
    gap: 0;
  }
}
</style>