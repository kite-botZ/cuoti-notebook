<template>
  <main class="bank-page">
    <header class="bank-header">
      <button class="back-button" type="button" @click="router.push('/home')">
        ← <span>我的题库</span>
      </button>
      <div class="header-actions">
        <button type="button" @click="scrollToQuestions">管理题目</button>
      </div>
    </header>

    <section v-if="loading" class="status-state">加载中…</section>

    <section v-else-if="bank" class="bank-content">
      <div class="bank-hero">
        <div>
          <p class="eyebrow">QUESTION BANK</p>
          <h1>{{ bank.name }}</h1>
          <p>{{ bank.description || '在这里选择适合自己的练习方式。' }}</p>
        </div>
        <span class="bank-subject">{{ bank.subject }}</span>
      </div>

      <button
        class="all-practice"
        type="button"
        :disabled="normalQuestions.length === 0"
        @click="startPractice('sequential')"
      >
        <span class="play-icon">▶</span>
        <span>
          <strong>开始顺序练习</strong>
          <small>从第 1 题开始，完成全部 {{ normalQuestions.length }} 道题</small>
        </span>
        <i>→</i>
      </button>

      <section class="feature-section">
        <div class="section-heading">
          <div>
            <p class="eyebrow">MY COLLECTION</p>
            <h2>题库内容</h2>
          </div>
          <span>{{ questions.length }} 道题目</span>
        </div>
        <div class="feature-grid">
          <button type="button" class="feature-card wrong" :disabled="wrongQuestions.length === 0" @click="startPractice('wrong')">
            <span class="feature-icon">×</span>
            <strong>我的错题</strong>
            <small>{{ wrongQuestions.length }} 道待巩固</small>
          </button>
          <button type="button" class="feature-card favorite" :disabled="favoriteQuestions.length === 0" @click="startPractice('favorite')">
            <span class="feature-icon">★</span>
            <strong>我的收藏</strong>
            <small>{{ favoriteQuestions.length }} 道重点题</small>
          </button>
          <button type="button" class="feature-card cut" :disabled="cutQuestions.length === 0" @click="openCutDialog">
            <span class="feature-icon">✂</span>
            <strong>我的斩题</strong>
            <small>{{ cutQuestions.length }} 道已移出练习</small>
          </button>
          <button type="button" class="feature-card note" :disabled="noteQuestions.length === 0" @click="showNotes = true">
            <span class="feature-icon">✎</span>
            <strong>我的笔记</strong>
            <small>{{ noteQuestions.length }} 条学习笔记</small>
          </button>
        </div>
      </section>

      <section class="feature-section">
        <div class="section-heading">
          <div>
            <p class="eyebrow">PRACTICE METHODS</p>
            <h2>选择练习方式</h2>
          </div>
        </div>
        <div class="practice-grid">
          <button type="button" :disabled="normalQuestions.length === 0" @click="startPractice('sequential')">
            <span class="method-icon green">≡</span>
            <strong>顺序练习</strong>
            <small>按题库顺序逐题完成</small>
            <em>{{ normalQuestions.length }} 题</em>
          </button>
          <button type="button" :disabled="normalQuestions.length === 0" @click="startPractice('random')">
            <span class="method-icon blue">⌘</span>
            <strong>随机练习</strong>
            <small>随机抽取，避免记住顺序</small>
            <em>{{ normalQuestions.length }} 题</em>
          </button>
          <button type="button" :disabled="normalQuestions.length === 0" @click="startPractice('sequential')">
            <span class="method-icon orange">☷</span>
            <strong>全部题目</strong>
            <small>从第一题开始刷整库</small>
            <em>{{ normalQuestions.length }} 题</em>
          </button>
        </div>
      </section>

      <section id="questions" class="question-manager">
        <div class="manager-heading">
          <div>
            <p class="eyebrow">QUESTION LIST</p>
            <h2>全部题目</h2>
            <p>{{ visibleQuestions.length }} 道题目；已斩题不会进入常规练习。</p>
          </div>
          <div class="manager-actions">
            <input v-model.trim="query" type="search" placeholder="搜索题目或知识点" />
            <button type="button" class="outline-button" :disabled="!visibleQuestions.length" @click="toggleSelectAll">
              {{ allSelected ? '取消全选' : '全选' }}
            </button>
            <button type="button" class="outline-button batch-cut-btn" :disabled="selectedIds.length === 0 || batchCutting" @click="batchCut(true)">
              {{ batchCutting ? '处理中…' : `批量斩题（${selectedIds.length}）` }}
            </button>
            <button type="button" class="outline-button" @click="openImport">导入题目</button>
            <button type="button" class="outline-button" @click="showQuestionDialog = true">新增题目</button>
            <button type="button" class="select-practice" :disabled="selectedIds.length === 0" @click="startPractice('selected')">
              开始练习（{{ selectedIds.length }}）
            </button>
          </div>
        </div>

        <div v-if="visibleQuestions.length" class="question-list">
          <label
            v-for="question in visibleQuestions"
            :key="question.id"
            class="question-row"
            :class="{ selected: selectedIds.includes(question.id), cutted: question.is_cut }"
          >
            <input
              type="checkbox"
              :disabled="question.is_cut"
              :checked="selectedIds.includes(question.id)"
              @change="toggleSelection(question.id)"
            />
            <span class="row-type">{{ typeLabel(question.question_type) }}</span>
            <div class="row-main">
              <strong>{{ question.stem }}</strong>
              <p>{{ question.note || '暂无笔记' }}</p>
              <small>
                {{ question.is_cut
                  ? '已斩题，可在「我的斩题」中恢复'
                  : `错题次数：${question.wrong_count}` }}
              </small>
            </div>
            <div class="row-actions">
              <button
                type="button"
                class="row-btn"
                :class="{ active: question.is_favorite }"
                @click.prevent="toggleFavorite(question.id)"
              >
                {{ question.is_favorite ? '★ 已收藏' : '☆ 收藏' }}
              </button>
              <button
                type="button"
                class="row-btn cut"
                :class="{ active: question.is_cut }"
                @click.prevent="toggleCut(question.id)"
              >
                {{ question.is_cut ? '↺ 恢复' : '✂ 斩题' }}
              </button>
              <button
                type="button"
                class="row-btn delete"
                @click.prevent="confirmDeleteQuestion(question)"
              >
                ✕ 删除
              </button>
            </div>
          </label>
        </div>

        <div v-else class="empty-questions">
          <strong>还没有匹配的题目</strong>
          <p>可以新增题目、批量导入，或调整搜索内容。</p>
        </div>
      </section>
    </section>

    <section v-else class="not-found">
      <h1>没有找到这个题库</h1>
      <p>题库可能已被删除，或地址不正确。</p>
      <button type="button" @click="router.push('/home')">返回我的题库</button>
    </section>

    <!-- 笔记弹窗 -->
    <div v-if="showNotes" class="modal-backdrop" @click.self="showNotes = false">
      <section class="modal note-modal">
        <div class="modal-head">
          <div>
            <p class="eyebrow">MY NOTES</p>
            <h2>我的笔记</h2>
          </div>
          <button type="button" @click="showNotes = false">关闭</button>
        </div>
        <div v-for="question in noteQuestions" :key="question.id" class="note-item">
          <strong>{{ question.stem }}</strong>
          <p>{{ question.note }}</p>
        </div>
      </section>
    </div>

    <!-- 新增题目弹窗 -->
    <div v-if="showQuestionDialog" class="modal-backdrop" @click.self="showQuestionDialog = false">
      <form class="modal question-modal" @submit.prevent="addQuestion">
        <div class="modal-head">
          <div>
            <p class="eyebrow">NEW QUESTION</p>
            <h2>新增题目</h2>
          </div>
          <button type="button" @click="showQuestionDialog = false">关闭</button>
        </div>
        <label for="question-stem">题目</label>
        <input id="question-stem" v-model.trim="newQuestion.stem" placeholder="请输入题干" required />
        <label for="question-explanation">解析或易错点</label>
        <textarea id="question-explanation" v-model.trim="newQuestion.explanation" placeholder="写下解题思路或易错原因"></textarea>
        <div class="form-grid">
          <div>
            <label for="question-type">题型</label>
            <select id="question-type" v-model="newQuestion.question_type">
              <option value="single">单选题</option>
              <option value="judge">判断题</option>
            </select>
          </div>
          <div>
            <label for="question-answer">正确答案</label>
            <select id="question-answer" v-model.number="newQuestion.correct_answer">
              <option :value="0">选项 A</option>
              <option :value="1">选项 B</option>
            </select>
          </div>
        </div>
        <div class="form-grid">
          <div>
            <label for="option-a">选项 A</label>
            <input id="option-a" v-model.trim="newQuestion.options[0]" placeholder="选项内容" required />
          </div>
          <div>
            <label for="option-b">选项 B</label>
            <input id="option-b" v-model.trim="newQuestion.options[1]" placeholder="选项内容" required />
          </div>
        </div>
        <button class="modal-submit" type="submit" :disabled="creating">
          {{ creating ? '保存中…' : '保存题目' }}
        </button>
      </form>
    </div>

    <!-- 批量导入弹窗 -->
    <div v-if="showImportDialog" class="modal-backdrop" @click.self="closeImport">
      <section class="modal import-modal">
        <div class="modal-head">
          <div>
            <p class="eyebrow">IMPORT QUESTIONS</p>
            <h2>批量导入题目</h2>
          </div>
          <button type="button" @click="closeImport">关闭</button>
        </div>

        <p class="import-tip">
          支持 <b>JSON</b> / <b>Excel (.xlsx)</b> / <b>Word (.docx)</b> / <b>PDF</b>，单文件不超过 10MB。
        </p>

        <label class="import-drop" :class="{ 'has-file': importFile }">
          <input type="file" accept=".json,.xlsx,.xls,.docx,.pdf" @change="onFileChange" />
          <template v-if="!importFile">
            <span class="drop-icon">⬆</span>
            <strong>点击选择文件</strong>
            <small>或把文件拖到这里</small>
          </template>
          <template v-else>
            <span class="drop-icon">📄</span>
            <strong>{{ importFile.name }}</strong>
            <small>{{ formatSize(importFile.size) }}</small>
          </template>
        </label>

        <p v-if="importError" class="import-error">{{ importError }}</p>
        <p v-if="importSuccess" class="import-success">✓ {{ importSuccess }}</p>

        <div class="template-row">
          <span>下载模板：</span>
          <button type="button" class="link-button" @click="downloadJsonTemplate">JSON</button>
          <a class="link-button" href="/templates/题目导入模板.xlsx" download>Excel</a>
          <a class="link-button" href="/templates/题目导入模板.docx" download>Word</a>
        </div>

        <details class="format-details">
          <summary>查看导入格式说明</summary>
          <div class="format-body">
            <p><b>JSON</b>：数组，每项含 <code>stem</code>、<code>options</code>、<code>correct_answer</code>、<code>explanation</code>。</p>
            <p><b>Excel</b>：第一行表头必须有「题干」「选项A」「选项B」…「正确答案」「解析」。</p>
            <p><b>Word / PDF</b>：每题按「<code>1. 题干</code> / <code>A. 选项</code> / <code>答案：B</code> / <code>解析：xxx</code>」格式。</p>
          </div>
        </details>

        <button class="modal-submit" type="button" :disabled="!importFile || importing" @click="submitImport">
          {{ importing ? '导入中…' : '开始导入' }}
        </button>
      </section>
    </div>

    <!-- 我的斩题弹窗 -->
    <div v-if="showCutDialog" class="modal-backdrop" @click.self="closeCutDialog">
      <section class="modal cut-modal">
        <div class="modal-head">
          <div>
            <p class="eyebrow">CUT QUESTIONS</p>
            <h2>我的斩题</h2>
            <p class="cut-hint">共 {{ cutList.length }} 道 · 已移出常规练习</p>
          </div>
          <button type="button" @click="closeCutDialog">关闭</button>
        </div>

        <div v-if="cutList.length" class="cut-toolbar">
          <label class="cut-check-all">
            <input type="checkbox" :checked="allCutSelected" @change="toggleAllCutSelected" />
            <span>{{ allCutSelected ? '取消全选' : '全选' }}</span>
          </label>
          <span class="cut-selected-count">已选 {{ cutSelectedIds.length }}</span>

          <div class="cut-toolbar-actions">
            <button type="button" class="cut-tool-btn restore" :disabled="cutSelectedIds.length === 0 || restoringBatch" @click="restoreSelectedCut">
              {{ restoringBatch ? '恢复中…' : `恢复选中（${cutSelectedIds.length}）` }}
            </button>
            <button type="button" class="cut-tool-btn restore-all" :disabled="restoringBatch" @click="restoreAllCut">
              {{ restoringBatch ? '恢复中…' : '全部恢复' }}
            </button>
            <button type="button" class="cut-tool-btn primary" @click="practiceAllCut">
              练习全部（{{ cutList.length }}）
            </button>
          </div>
        </div>

        <div v-if="cutList.length" class="cut-grid">
          <article
            v-for="(question, idx) in cutList"
            :key="question.id"
            class="cut-card"
            :class="{ selected: cutSelectedIds.includes(question.id) }"
          >
            <header class="cut-card-head">
              <label class="cut-card-check">
                <input type="checkbox" :checked="cutSelectedIds.includes(question.id)" @change="toggleCutSelected(question.id)" />
                <span class="cut-card-index">第 {{ idx + 1 }} 题</span>
              </label>
              <span class="cut-card-tag">{{ typeLabel(question.question_type) }}</span>
            </header>

            <p class="cut-card-stem">{{ question.stem }}</p>

            <ul class="cut-card-options">
              <li v-for="(opt, i) in question.options" :key="i" :class="{ correct: i === question.correct_answer }">
                <span class="opt-key">{{ String.fromCharCode(65 + i) }}</span>
                <span>{{ opt }}</span>
              </li>
            </ul>

            <p v-if="question.explanation" class="cut-card-explanation">
              <b>解析</b>{{ question.explanation }}
            </p>

            <footer class="cut-card-actions">
              <button type="button" class="row-btn" @click="practiceOneCut(question)">练习这题</button>
              <button type="button" class="row-btn restore" :disabled="restoring === question.id" @click="restoreFromDialog(question.id)">
                {{ restoring === question.id ? '恢复中…' : '恢复' }}
              </button>
            </footer>
          </article>
        </div>

        <p v-else class="empty-cut">还没有斩过的题。</p>
      </section>
    </div>
  </main>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import request from '@/api/request'
import { toast } from '@/composables/useToast'

type Bank = {
  id: number
  name: string
  subject: string
  description: string
  question_count: number
}

type Question = {
  id: number
  bank_id: number
  stem: string
  question_type: string
  options: string[]
  created_at: string
  is_favorite: boolean
  is_cut: boolean
  note: string
  wrong_count: number
}

type CutQuestion = Question & {
  correct_answer: number
  explanation: string
}

const router = useRouter()
const route = useRoute()
const bankId = Number(route.params.id)

const loading = ref(true)
const creating = ref(false)
const bank = ref<Bank | null>(null)
const questions = ref<Question[]>([])

const query = ref('')
const selectedIds = ref<number[]>([])
const showNotes = ref(false)
const showQuestionDialog = ref(false)

const newQuestion = ref({
  stem: '',
  explanation: '',
  question_type: 'single',
  options: ['', ''] as [string, string],
  correct_answer: 0,
})

const showImportDialog = ref(false)
const importFile = ref<File | null>(null)
const importing = ref(false)
const importError = ref('')
const importSuccess = ref('')

const showCutDialog = ref(false)
const cutList = ref<CutQuestion[]>([])
const restoring = ref<number | null>(null)
const batchCutting = ref(false)
const cutSelectedIds = ref<number[]>([])
const restoringBatch = ref(false)

const normalQuestions = computed(() => questions.value.filter(q => !q.is_cut))
const wrongQuestions = computed(() => questions.value.filter(q => q.wrong_count > 0 && !q.is_cut))
const favoriteQuestions = computed(() => questions.value.filter(q => q.is_favorite && !q.is_cut))
const cutQuestions = computed(() => questions.value.filter(q => q.is_cut))
const noteQuestions = computed(() => questions.value.filter(q => q.note && q.note.length > 0))

const visibleQuestions = computed(() =>
  questions.value.filter(q => `${q.stem}${q.note}`.includes(query.value))
)

const allSelected = computed(() =>
  visibleQuestions.value.length > 0 &&
  visibleQuestions.value.every(q => selectedIds.value.includes(q.id))
)

const allCutSelected = computed(() =>
  cutList.value.length > 0 &&
  cutList.value.every(q => cutSelectedIds.value.includes(q.id))
)

function typeLabel(type: string) {
  const map: Record<string, string> = {
    single: '单选题',
    multiple: '多选题',
    judge: '判断题',
    blank: '填空题',
  }
  return map[type] || type
}

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`
}

async function loadBank() {
  try {
    const list = await request.get('/banks') as unknown as Bank[]
    bank.value = list.find(b => b.id === bankId) || null
  } catch (e: any) {
    toast.error(e.message || '题库加载失败')
  }
}

async function loadQuestions() {
  try {
    questions.value = await request.get(`/banks/${bankId}/questions`) as unknown as Question[]
  } catch (e: any) {
    toast.error(e.message || '题目加载失败')
  }
}

async function loadAll() {
  loading.value = true
  await Promise.all([loadBank(), loadQuestions()])
  loading.value = false
}

onMounted(loadAll)

function scrollToQuestions() {
  document.getElementById('questions')?.scrollIntoView({ behavior: 'smooth' })
}

function toggleSelection(id: number) {
  selectedIds.value = selectedIds.value.includes(id)
    ? selectedIds.value.filter(item => item !== id)
    : [...selectedIds.value, id]
}

function toggleSelectAll() {
  if (allSelected.value) {
    const visibleIds = new Set(visibleQuestions.value.map(q => q.id))
    selectedIds.value = selectedIds.value.filter(id => !visibleIds.has(id))
  } else {
    const visibleIds = visibleQuestions.value.map(q => q.id)
    selectedIds.value = Array.from(new Set([...selectedIds.value, ...visibleIds]))
  }
}

async function toggleFavorite(id: number) {
  try {
    const res = await request.post(`/questions/${id}/favorite`) as unknown as { is_favorite: boolean }
    const target = questions.value.find(q => q.id === id)
    if (target) target.is_favorite = res.is_favorite
  } catch (e: any) {
    toast.error(e.message || '操作失败')
  }
}

async function toggleCut(id: number) {
  try {
    const res = await request.post(`/questions/${id}/cut`) as unknown as { is_cut: boolean }
    const target = questions.value.find(q => q.id === id)
    if (target) target.is_cut = res.is_cut
  } catch (e: any) {
    toast.error(e.message || '操作失败')
  }
}

async function batchCut(shouldCut: boolean) {
  if (batchCutting.value) return
  if (selectedIds.value.length === 0) {
    toast.warning('请先选择题目')
    return
  }

  batchCutting.value = true
  try {
    const res = await request.post(
      `/banks/${bankId}/questions/batch-cut`,
      { question_ids: selectedIds.value, is_cut: shouldCut }
    ) as unknown as { message: string }

    toast.success(res.message)
    selectedIds.value = []
    await loadQuestions()
    await loadBank()
  } catch (e: any) {
    toast.error(e.message || '操作失败')
  } finally {
    batchCutting.value = false
  }
}

async function confirmDeleteQuestion(question: Question) {
  const preview = question.stem.length > 60
    ? `${question.stem.slice(0, 60)}…`
    : question.stem
  const confirmed = window.confirm(
    `确定删除这道题吗？\n\n${preview}\n\n删除后无法恢复，答题记录也会一并删除。`
  )
  if (!confirmed) return

  try {
    await request.delete(`/questions/${question.id}`)
    questions.value = questions.value.filter(q => q.id !== question.id)
    await loadBank()
    toast.success('题目已删除')
  } catch (e: any) {
    toast.error(e.message || '删除失败')
  }
}

async function openCutDialog() {
  try {
    cutList.value = await request.get(
      `/banks/${bankId}/questions?filter_type=cut`
    ) as unknown as CutQuestion[]
    cutSelectedIds.value = []
    showCutDialog.value = true
  } catch (e: any) {
    toast.error(e.message || '加载失败')
  }
}

function closeCutDialog() {
  showCutDialog.value = false
}

async function restoreFromDialog(id: number) {
  restoring.value = id
  try {
    await request.post(`/questions/${id}/cut`)
    cutList.value = cutList.value.filter(q => q.id !== id)
    cutSelectedIds.value = cutSelectedIds.value.filter(x => x !== id)
    await loadQuestions()
    await loadBank()
    toast.success('已恢复')
  } catch (e: any) {
    toast.error(e.message || '恢复失败')
  } finally {
    restoring.value = null
  }
}

function toggleCutSelected(id: number) {
  cutSelectedIds.value = cutSelectedIds.value.includes(id)
    ? cutSelectedIds.value.filter(x => x !== id)
    : [...cutSelectedIds.value, id]
}

function toggleAllCutSelected() {
  if (allCutSelected.value) {
    cutSelectedIds.value = []
  } else {
    cutSelectedIds.value = cutList.value.map(q => q.id)
  }
}

async function restoreSelectedCut() {
  if (restoringBatch.value) return
  if (cutSelectedIds.value.length === 0) {
    toast.warning('请先选择题目')
    return
  }

  restoringBatch.value = true
  try {
    const res = await request.post(
      `/banks/${bankId}/questions/batch-cut`,
      { question_ids: cutSelectedIds.value, is_cut: false }
    ) as unknown as { message: string }

    toast.success(res.message)
    cutSelectedIds.value = []
    await refreshCutList()
    await loadQuestions()
    await loadBank()
  } catch (e: any) {
    toast.error(e.message || '恢复失败')
  } finally {
    restoringBatch.value = false
  }
}

async function restoreAllCut() {
  if (restoringBatch.value) return
  if (!cutList.value.length) return

  const confirmed = window.confirm(
    `确定恢复全部 ${cutList.value.length} 道题吗？\n\n恢复后它们会回到常规练习。`
  )
  if (!confirmed) return

  restoringBatch.value = true
  try {
    const res = await request.post(
      `/banks/${bankId}/questions/batch-cut`,
      { question_ids: cutList.value.map(q => q.id), is_cut: false }
    ) as unknown as { message: string }

    toast.success(res.message)
    cutSelectedIds.value = []
    await refreshCutList()
    await loadQuestions()
    await loadBank()
  } catch (e: any) {
    toast.error(e.message || '恢复失败')
  } finally {
    restoringBatch.value = false
  }
}

async function refreshCutList() {
  try {
    cutList.value = await request.get(
      `/banks/${bankId}/questions?filter_type=cut`
    ) as unknown as CutQuestion[]
  } catch (e: any) {
    toast.error(e.message || '刷新失败')
  }
}

function practiceAllCut() {
  if (!cutList.value.length) return
  const ids = cutList.value.map(q => q.id)
  sessionStorage.setItem('practice-selection', JSON.stringify(ids))
  router.push({ path: '/practice', query: { bank: bankId, source: 'cut' } })
}

function practiceOneCut(question: { id: number }) {
  sessionStorage.setItem('practice-selection', JSON.stringify([question.id]))
  router.push({ path: '/practice', query: { bank: bankId, source: 'selected' } })
}

function startPractice(source: 'sequential' | 'random' | 'wrong' | 'favorite' | 'cut' | 'selected') {
  const listMap: Record<string, Question[]> = {
    sequential: normalQuestions.value,
    random: normalQuestions.value,
    wrong: wrongQuestions.value,
    favorite: favoriteQuestions.value,
    cut: cutQuestions.value,
    selected: normalQuestions.value.filter(q => selectedIds.value.includes(q.id)),
  }
  const list = listMap[source]
  if (!list.length) return

  sessionStorage.setItem('practice-selection', JSON.stringify(list.map(q => q.id)))

  router.push({
    path: '/practice',
    query: { bank: bankId, source },
  })
}

async function addQuestion() {
  if (!newQuestion.value.stem.trim()) {
    toast.warning('请输入题目')
    return
  }
  if (newQuestion.value.options.some(o => !o.trim())) {
    toast.warning('选项不能为空')
    return
  }

  creating.value = true
  try {
    await request.post(`/banks/${bankId}/questions`, {
      stem: newQuestion.value.stem,
      question_type: newQuestion.value.question_type,
      options: newQuestion.value.options,
      correct_answer: newQuestion.value.correct_answer,
      explanation: newQuestion.value.explanation,
    })

    newQuestion.value = {
      stem: '',
      explanation: '',
      question_type: 'single',
      options: ['', ''],
      correct_answer: 0,
    }
    showQuestionDialog.value = false
    await loadQuestions()
    await loadBank()
    toast.success('题目已保存')
  } catch (e: any) {
    toast.error(e.message || '创建失败')
  } finally {
    creating.value = false
  }
}

function openImport() {
  showImportDialog.value = true
  importFile.value = null
  importError.value = ''
  importSuccess.value = ''
}

function closeImport() {
  if (importing.value) return
  showImportDialog.value = false
}

function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  importFile.value = file
  importError.value = ''
  importSuccess.value = ''
}

async function submitImport() {
  if (!importFile.value || importing.value) return

  const file = importFile.value
  if (file.size > 10 * 1024 * 1024) {
    toast.warning('文件超过 10MB')
    return
  }

  importing.value = true
  importError.value = ''
  importSuccess.value = ''

  try {
    const formData = new FormData()
    formData.append('file', file)

    const res = await request.post(
      `/banks/${bankId}/questions/import`,
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' } }
    ) as unknown as { message: string; imported: number }

    importSuccess.value = res.message
    importFile.value = null

    await loadQuestions()
    await loadBank()

    toast.success(res.message)
    setTimeout(() => { closeImport() }, 900)
  } catch (e: any) {
    importError.value = e.message || '导入失败'
    toast.error(e.message || '导入失败')
  } finally {
    importing.value = false
  }
}

function downloadJsonTemplate() {
  const sample = [
    {
      stem: '1 + 1 等于几？',
      question_type: 'single',
      options: ['1', '2', '3', '4'],
      correct_answer: 'B',
      explanation: '1 + 1 = 2',
    },
    {
      stem: '中国的首都是？',
      question_type: 'single',
      options: ['上海', '北京', '广州', '深圳'],
      correct_answer: 'B',
      explanation: '北京是中国的首都',
    },
  ]
  const blob = new Blob([JSON.stringify(sample, null, 2)], {
    type: 'application/json;charset=utf-8',
  })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = '题目导入模板.json'
  a.click()
  URL.revokeObjectURL(url)
}
</script>

<style scoped>
.bank-page {
  min-height: 100vh;
  color: #20332b;
  background: #f5f8f6;
}
.bank-header {
  height: 66px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 clamp(20px, 6vw, 86px);
  border-bottom: 1px solid #e0e8e3;
  background: rgba(255, 255, 255, .92);
}
.back-button,
.header-actions button {
  border: 0;
  color: #466056;
  background: transparent;
  font-size: 14px;
}
.back-button {
  display: flex;
  gap: 9px;
  align-items: center;
  color: #254b3f;
  font-weight: 600;
  font-size: 15px;
  cursor: pointer;
}
.bank-content {
  max-width: 1080px;
  margin: 0 auto;
  padding: 52px 28px 80px;
}
.bank-hero {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 20px;
}
.eyebrow {
  margin: 0 0 10px;
  color: #6f9083;
  font-size: 11px;
  letter-spacing: 1.3px;
  font-weight: 700;
}
.bank-hero h1 {
  margin: 0;
  font-size: clamp(28px, 4vw, 38px);
  font-weight: 650;
}
.bank-hero p:last-child {
  margin: 10px 0 0;
  color: #75847c;
  font-size: 14px;
}
.bank-subject {
  padding: 8px 12px;
  border-radius: 7px;
  color: #1a775e;
  background: #e3f4ec;
  font-size: 13px;
  font-weight: 600;
}
.all-practice {
  display: flex;
  align-items: center;
  gap: 16px;
  width: 100%;
  margin-top: 34px;
  border: 0;
  border-radius: 14px;
  padding: 20px;
  color: #fff;
  background: linear-gradient(120deg, #197b60, #2faf86);
  text-align: left;
  box-shadow: 0 12px 24px rgba(30, 133, 101, .17);
  cursor: pointer;
}
.all-practice:disabled,
.feature-card:disabled,
.practice-grid button:disabled {
  opacity: .48;
  cursor: not-allowed;
}
.play-icon {
  display: grid;
  place-items: center;
  flex: 0 0 42px;
  width: 42px;
  height: 42px;
  border-radius: 12px;
  background: rgba(255, 255, 255, .2);
  font-size: 16px;
}
.all-practice strong,
.all-practice small {
  display: block;
}
.all-practice strong {
  font-size: 17px;
}
.all-practice small {
  margin-top: 5px;
  opacity: .78;
  font-size: 13px;
}
.all-practice i {
  margin-left: auto;
  font-size: 24px;
  font-style: normal;
}
.feature-section {
  margin-top: 48px;
}
.section-heading {
  display: flex;
  justify-content: space-between;
  align-items: end;
  margin-bottom: 16px;
}
.section-heading h2 {
  margin: 0;
  font-size: 20px;
}
.section-heading > span {
  color: #85928b;
  font-size: 13px;
}
.feature-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 13px;
}
.feature-card,
.practice-grid button {
  min-height: 155px;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  border: 1px solid #e0e8e3;
  border-radius: 13px;
  padding: 17px;
  color: #2d4238;
  background: #fff;
  text-align: left;
  transition: transform .16s, box-shadow .16s, border-color .16s;
  cursor: pointer;
}
.feature-card:hover:not(:disabled),
.practice-grid button:hover:not(:disabled) {
  border-color: #94cdb7;
  box-shadow: 0 8px 18px rgba(31, 83, 66, .08);
  transform: translateY(-2px);
}
.feature-icon {
  display: grid;
  place-items: center;
  width: 35px;
  height: 35px;
  margin-bottom: auto;
  border-radius: 10px;
  font-size: 17px;
  font-weight: 700;
}
.wrong .feature-icon {
  color: #d05b54;
  background: #fff0ef;
}
.favorite .feature-icon {
  color: #df9929;
  background: #fff5de;
}
.cut .feature-icon {
  color: #5c7cd1;
  background: #eef2ff;
  font-size: 14px;
}
.note .feature-icon {
  color: #2b9677;
  background: #e8f8f1;
}
.feature-card strong,
.practice-grid strong {
  margin-top: 17px;
  font-size: 15px;
}
.feature-card small,
.practice-grid small {
  margin-top: 7px;
  color: #84918b;
  font-size: 12px;
}
.practice-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 13px;
}
.practice-grid button {
  position: relative;
  min-height: 175px;
}
.method-icon {
  display: grid;
  place-items: center;
  width: 43px;
  height: 43px;
  border-radius: 13px;
  font-size: 22px;
}
.green {
  color: #258568;
  background: #e4f5ed;
}
.blue {
  color: #477fbd;
  background: #e9f2fd;
}
.orange {
  color: #c17636;
  background: #fff0df;
}
.practice-grid em {
  margin-top: auto;
  color: #9aa59f;
  font-size: 12px;
  font-style: normal;
}
.modal-backdrop {
  position: fixed;
  z-index: 10;
  inset: 0;
  display: grid;
  place-items: center;
  padding: 20px;
  background: rgba(20, 45, 35, .35);
}
.modal {
  width: min(100%, 490px);
  max-height: min(650px, 85vh);
  overflow: auto;
  border-radius: 16px;
  padding: 24px;
  background: #fff;
  box-shadow: 0 18px 48px rgba(19, 49, 37, .2);
}
.modal-head {
  display: flex;
  justify-content: space-between;
  align-items: start;
  margin-bottom: 20px;
}
.modal-head h2 {
  margin: 0;
  font-size: 21px;
}
.modal-head button {
  border: 0;
  color: #7e8c85;
  background: transparent;
  font-size: 13px;
  cursor: pointer;
}
.note-item {
  padding: 14px 0;
  border-top: 1px solid #eef2f0;
}
.note-item strong {
  font-size: 14px;
}
.note-item p {
  margin: 8px 0 0;
  color: #718078;
  font-size: 13px;
  line-height: 1.65;
}
.not-found {
  padding: 150px 24px;
  text-align: center;
}
.not-found h1 {
  font-size: 25px;
}
.not-found p {
  color: #77857d;
}
.not-found button {
  margin-top: 12px;
  border: 0;
  border-radius: 8px;
  padding: 11px 15px;
  color: #fff;
  background: #217b61;
  cursor: pointer;
}
.status-state {
  padding: 150px 24px;
  text-align: center;
  color: #77857d;
}
.question-manager {
  margin-top: 48px;
  border-top: 1px solid #dfe8e2;
  padding-top: 28px;
}
.manager-heading {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 20px;
}
.manager-heading h2 {
  margin: 0;
  font-size: 20px;
}
.manager-heading p:last-child {
  margin: 7px 0 0;
  color: #819088;
  font-size: 13px;
}
.manager-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.manager-actions input {
  width: 190px;
  height: 40px;
  border: 1px solid #d8e3dd;
  border-radius: 7px;
  padding: 0 11px;
  color: #3d4c45;
  outline: none;
  font-size: 13px;
}
.outline-button,
.select-practice {
  height: 40px;
  border: 1px solid #238266;
  border-radius: 7px;
  padding: 0 13px;
  color: #1d775e;
  background: #fff;
  font-weight: 600;
  cursor: pointer;
}
.outline-button:disabled {
  opacity: .5;
  cursor: not-allowed;
}
.batch-cut-btn {
  border-color: #5c7cd1;
  color: #455993;
}
.batch-cut-btn:hover:not(:disabled) {
  background: #f4f6ff;
}
.select-practice {
  color: #fff;
  background: #238266;
}
.select-practice:disabled {
  opacity: .5;
  cursor: not-allowed;
}
.question-list {
  margin-top: 18px;
  border: 1px solid #e1e9e4;
  background: #fff;
}
.question-row {
  display: grid;
  grid-template-columns: 18px 64px minmax(0, 1fr) auto;
  gap: 14px;
  align-items: center;
  padding: 18px 20px;
  border-bottom: 1px solid #eaf0ec;
  cursor: pointer;
}
.question-row:last-child {
  border-bottom: 0;
}
.question-row.selected {
  background: #f2faf6;
}
.question-row.cutted {
  opacity: .62;
  background: #f8f9f8;
}
.question-row input {
  width: 16px;
  height: 16px;
  accent-color: #238266;
}
.row-type {
  padding: 6px 7px;
  color: #28775f;
  background: #e7f5ee;
  text-align: center;
  font-size: 12px;
}
.row-main strong {
  color: #263b31;
  font-size: 15px;
}
.row-main p {
  margin: 6px 0;
  color: #74827b;
  font-size: 13px;
}
.row-main small {
  color: #9aa59f;
  font-size: 12px;
}
.row-actions {
  display: flex;
  gap: 6px;
  align-items: center;
}
.row-btn {
  min-width: 78px;
  border: 1px solid #e0e8e3;
  border-radius: 6px;
  padding: 6px 10px;
  color: #6d8077;
  background: #fff;
  font-size: 12px;
  cursor: pointer;
  white-space: nowrap;
  transition: border-color .18s, color .18s, background .18s;
}
.row-btn:hover {
  border-color: #8ec5b0;
  color: #28735f;
  background: #f6fbf8;
}
.row-btn.active {
  border-color: #28735f;
  color: #28735f;
  background: #eaf6f0;
}
.row-btn.cut:hover {
  border-color: #8b9ee0;
  color: #455993;
  background: #f4f6ff;
}
.row-btn.cut.active {
  border-color: #5c7cd1;
  color: #455993;
  background: #eef2ff;
}
.row-btn.delete {
  border-color: #f3d6d1;
  color: #bf4b3f;
  background: #fff;
}
.row-btn.delete:hover {
  border-color: #bf4b3f;
  background: #fff4f2;
}
.empty-questions {
  margin-top: 18px;
  padding: 60px 20px;
  border: 1px solid #e1e9e4;
  text-align: center;
  background: #fff;
}
.empty-questions strong {
  color: #43564c;
}
.empty-questions p {
  color: #85928b;
  font-size: 13px;
}
.question-modal label {
  display: block;
  margin: 16px 0 8px;
  color: #47594f;
  font-size: 13px;
  font-weight: 600;
}
.question-modal input,
.question-modal select,
.question-modal textarea {
  width: 100%;
  border: 1px solid #d8e4de;
  border-radius: 8px;
  padding: 10px;
  color: #33473d;
  background: #fff;
  outline: none;
  box-sizing: border-box;
}
.question-modal textarea {
  min-height: 80px;
  resize: vertical;
  font-family: inherit;
}
.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.modal-submit {
  width: 100%;
  margin-top: 22px;
  border: 0;
  border-radius: 9px;
  padding: 12px;
  color: #fff;
  background: #238266;
  font-weight: 600;
  cursor: pointer;
}
.modal-submit:disabled {
  opacity: .6;
  cursor: not-allowed;
}

.import-modal {
  max-width: 520px;
}
.import-tip {
  margin: 0 0 16px;
  color: #718078;
  font-size: 13px;
  line-height: 1.7;
}
.import-tip b {
  color: #28735f;
}
.import-drop {
  display: grid;
  place-items: center;
  gap: 4px;
  width: 100%;
  min-height: 130px;
  border: 2px dashed #d8e3dd;
  border-radius: 12px;
  padding: 20px;
  color: #6d8077;
  background: #fafcfb;
  text-align: center;
  cursor: pointer;
  transition: border-color .18s, background .18s;
}
.import-drop:hover {
  border-color: #8ec5b0;
  background: #f4faf7;
}
.import-drop.has-file {
  border-style: solid;
  border-color: #28735f;
  background: #f1f9f5;
  color: #28735f;
}
.import-drop input {
  display: none;
}
.import-drop .drop-icon {
  font-size: 26px;
}
.import-drop strong {
  font-size: 15px;
  color: #2d4238;
}
.import-drop.has-file strong {
  color: #17644f;
}
.import-drop small {
  font-size: 12px;
}
.import-error {
  margin: 14px 0 0;
  padding: 9px 12px;
  border-left: 3px solid #bf4b3f;
  color: #a13c31;
  background: #fff4f2;
  font-size: 13px;
  border-radius: 4px;
}
.import-success {
  margin: 14px 0 0;
  padding: 9px 12px;
  border-left: 3px solid #28735f;
  color: #1f6956;
  background: #f1f9f5;
  font-size: 13px;
  border-radius: 4px;
}
.template-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 16px;
  color: #718078;
  font-size: 13px;
}
.link-button {
  border: 0;
  padding: 4px 6px;
  color: #28735f;
  background: transparent;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  border-radius: 6px;
  transition: background .18s;
}
.link-button:hover {
  background: #eaf6f0;
}
a.link-button {
  text-decoration: none;
  display: inline-block;
}
.format-details {
  margin-top: 12px;
  border: 1px solid #e0e8e3;
  border-radius: 10px;
  background: #fafcfb;
  overflow: hidden;
}
.format-details summary {
  padding: 10px 14px;
  color: #4a675a;
  font-size: 13px;
  cursor: pointer;
  list-style: none;
}
.format-details summary::marker {
  display: none;
}
.format-details summary::after {
  content: '▾';
  float: right;
  color: #8b9690;
  font-size: 11px;
  transition: transform .18s;
}
.format-details[open] summary::after {
  transform: rotate(180deg);
}
.format-body {
  padding: 4px 14px 12px;
  border-top: 1px solid #eef2f0;
  color: #6d8077;
  font-size: 12.5px;
  line-height: 1.7;
}
.format-body p {
  margin: 8px 0;
}
.format-body code {
  padding: 1px 5px;
  border-radius: 4px;
  background: #eef2f0;
  color: #1f6956;
  font-size: 12px;
}
.format-body b {
  color: #2d4238;
}

.cut-hint {
  margin: 6px 0 0;
  color: #85928b;
  font-size: 12px;
}
.cut-modal {
  width: min(100%, 640px);
  max-width: 640px;
  max-height: 85vh;
  display: flex;
  flex-direction: column;
  padding: 24px 0 0;
}
.cut-modal .modal-head {
  padding: 0 24px;
  margin-bottom: 16px;
}
.cut-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  padding: 0 24px 14px;
  border-bottom: 1px solid #eef2f0;
}
.cut-check-all {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: #4a675a;
  font-size: 13px;
  cursor: pointer;
}
.cut-check-all input {
  width: 15px;
  height: 15px;
  accent-color: #28735f;
}
.cut-selected-count {
  color: #85928b;
  font-size: 12px;
}
.cut-toolbar-actions {
  display: flex;
  gap: 8px;
  margin-left: auto;
  flex-wrap: wrap;
}
.cut-tool-btn {
  height: 36px;
  border-radius: 8px;
  padding: 0 12px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background .18s, border-color .18s;
}
.cut-tool-btn:disabled {
  opacity: .6;
  cursor: not-allowed;
}
.cut-tool-btn.restore {
  border: 1px solid #8b9ee0;
  color: #455993;
  background: #f4f6ff;
}
.cut-tool-btn.restore:hover:not(:disabled) {
  background: #e0e7ff;
}
.cut-tool-btn.restore-all {
  border: 1px solid #d8e3dd;
  color: #2c6f5a;
  background: #fff;
}
.cut-tool-btn.restore-all:hover:not(:disabled) {
  border-color: #8ec5b0;
  background: #f6fbf8;
}
.cut-tool-btn.primary {
  border: 1px solid #1f6956;
  color: #fff;
  background: #1f6956;
}
.cut-tool-btn.primary:hover:not(:disabled) {
  background: #175746;
}
.cut-grid {
  flex: 1;
  overflow-y: auto;
  padding: 16px 24px 24px;
  display: grid;
  gap: 14px;
}
.cut-card {
  border: 1px solid #e0e8e3;
  border-radius: 12px;
  padding: 16px 18px;
  background: #fff;
  transition: border-color .18s, box-shadow .18s, background .18s;
}
.cut-card:hover {
  border-color: #8ec5b0;
  box-shadow: 0 4px 14px rgba(31, 83, 66, .05);
}
.cut-card.selected {
  border-color: #28735f;
  background: #f6fbf8;
}
.cut-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.cut-card-check {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}
.cut-card-check input {
  width: 15px;
  height: 15px;
  accent-color: #28735f;
}
.cut-card-index {
  color: #7a8b9b;
  font-size: 12px;
  font-weight: 600;
}
.cut-card-tag {
  padding: 4px 8px;
  border-radius: 6px;
  color: #28775f;
  background: #e7f5ee;
  font-size: 12px;
  font-weight: 600;
}
.cut-card-stem {
  margin: 0 0 12px;
  color: #2d4238;
  font-size: 14.5px;
  font-weight: 600;
  line-height: 1.6;
}
.cut-card-options {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 6px;
}
.cut-card-options li {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 8px 11px;
  border: 1px solid #eef2f0;
  border-radius: 8px;
  color: #4d665b;
  background: #fafcfb;
  font-size: 13.5px;
}
.cut-card-options li.correct {
  border-color: #28735f;
  color: #17644f;
  background: #eaf6f0;
  font-weight: 600;
}
.cut-card-options .opt-key {
  display: grid;
  place-items: center;
  flex: 0 0 22px;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: #fff;
  border: 1px solid #dbe5df;
  font-size: 11px;
  font-weight: 700;
  color: #66766e;
}
.cut-card-options li.correct .opt-key {
  border-color: #28735f;
  color: #fff;
  background: #28735f;
}
.cut-card-explanation {
  margin: 12px 0 0;
  padding: 9px 12px;
  border-left: 3px solid #28735f;
  border-radius: 4px;
  background: #f1f9f5;
  color: #4d665b;
  font-size: 12.5px;
  line-height: 1.7;
}
.cut-card-explanation b {
  margin-right: 6px;
  color: #1f6956;
}
.cut-card-actions {
  display: flex;
  gap: 8px;
  margin-top: 14px;
}
.cut-card-actions .row-btn {
  flex: 1;
  min-width: 0;
  height: 36px;
  border: 1px solid #d8e3dd;
  border-radius: 8px;
  color: #4a675a;
  background: #fff;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: border-color .18s, background .18s, color .18s;
}
.cut-card-actions .row-btn:hover {
  border-color: #8ec5b0;
  background: #f6fbf8;
}
.cut-card-actions .row-btn.restore {
  border-color: #8b9ee0;
  color: #455993;
  background: #f4f6ff;
}
.cut-card-actions .row-btn.restore:hover:not(:disabled) {
  background: #e0e7ff;
}
.cut-card-actions .row-btn:disabled {
  opacity: .6;
  cursor: not-allowed;
}
.empty-cut {
  padding: 60px 24px;
  text-align: center;
  color: #9aa59f;
  font-size: 13px;
}

@media (max-width: 700px) {
  .bank-header {
    padding: 0 20px;
  }
  .bank-content {
    padding: 35px 20px 60px;
  }
  .feature-grid {
    grid-template-columns: repeat(2, 1fr);
  }
  .practice-grid {
    grid-template-columns: 1fr;
  }
  .practice-grid button {
    min-height: 130px;
  }
  .manager-heading {
    align-items: flex-start;
    flex-direction: column;
  }
  .manager-actions {
    width: 100%;
  }
  .manager-actions input {
    flex: 1;
    min-width: 170px;
  }
  .question-row {
    grid-template-columns: 18px 55px minmax(0, 1fr);
    padding: 15px;
  }
  .row-actions {
    grid-column: 3;
    justify-self: start;
    margin-top: 8px;
  }
  .form-grid {
    grid-template-columns: 1fr;
  }
  .cut-toolbar {
    padding: 0 16px 12px;
  }
  .cut-grid {
    padding: 14px 16px 20px;
  }
  .cut-toolbar-actions {
    width: 100%;
    margin-left: 0;
  }
  .cut-tool-btn {
    flex: 1;
  }
}
</style>