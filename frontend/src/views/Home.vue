<template>
  <main class="home-page">
    <header class="topbar">
      <router-link to="/home" class="brand">
        <span>错</span>错题本
      </router-link>
      <nav>
        <a class="active" href="#banks">我的题库</a>
      </nav>
      <div class="user-actions">
        <span class="avatar">{{ userInitial }}</span>
        <span>{{ username }}</span>
        <button type="button" @click="logout">退出</button>
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
import { computed, onMounted, ref } from 'vue'
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

function logout() {
  localStorage.removeItem('token')
  localStorage.removeItem('username')
  router.push('/login')
}
</script>

<style scoped>
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