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

      <!-- 我的收藏类 -->
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

      <!-- 分题型练习 -->
      <section class="feature-section">
        <div class="section-heading">
          <div>
            <p class="eyebrow">BY TYPE</p>
            <h2>分题型练习</h2>
          </div>
          <span>按类型专项训练</span>
        </div>
        <div class="type-grid">
          <button
            v-for="t in typeList"
            :key="t.key"
            type="button"
            class="type-card"
            :disabled="t.count === 0"
            @click="startPracticeByType(t.key)"
          >
            <span class="type-count">{{ t.count }}</span>
            <strong>{{ t.label }}</strong>
            <small>{{ t.desc }}</small>
          </button>
        </div>
      </section>

      <!-- 练习方式 -->
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

      <!-- 题目列表 -->
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
            <button type="button" class="outline-button" @click="openAddDialog">新增题目</button>
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
            <span class="row-type">{{ typeLabel(question) }}</span>
            <div class="row-main">
              <strong>{{ plainStem(question.stem) }}</strong>
              <p>{{ question.note || '暂无笔记' }}</p>
              <small>
                {{ question.is_cut
                  ? '已斩题，可在「我的斩题」中恢复'
                  : `错题次数：${question.wrong_count}` }}
              </small>
            </div>
            <div class="row-actions">
              <button type="button" class="row-btn" @click.prevent="openEditDialog(question)">✎ 编辑</button>
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
              <button type="button" class="row-btn delete" @click.prevent="confirmDeleteQuestion(question)">✕ 删除</button>
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
          <strong>{{ plainStem(question.stem) }}</strong>
          <p>{{ question.note }}</p>
        </div>
      </section>
    </div>

    <!-- 新增 / 编辑题目弹窗 -->
    <div v-if="showQuestionDialog" class="modal-backdrop" @click.self="closeQuestionDialog">
      <form class="modal question-modal" @submit.prevent="saveQuestion">
        <div class="modal-head">
          <div>
            <p class="eyebrow">{{ editingId ? 'EDIT QUESTION' : 'NEW QUESTION' }}</p>
            <h2>{{ editingId ? '编辑题目' : '新增题目' }}</h2>
          </div>
          <button type="button" @click="closeQuestionDialog">关闭</button>
        </div>

        <label>题型</label>
        <div class="type-picker">
          <button
            v-for="t in allTypes"
            :key="t.value"
            type="button"
            class="type-pick-btn"
            :class="{ active: newQuestion.question_type === t.value }"
            @click="newQuestion.question_type = t.value"
          >{{ t.label }}</button>
        </div>

        <label for="q-stem">题干</label>
        <textarea id="q-stem" v-model.trim="newQuestion.stem" placeholder="请输入题干；如需插图片，点击下方「插入图片」按钮" required></textarea>

        <div class="image-actions">
          <label class="image-upload-btn">
            <input type="file" accept="image/*" @change="onStemImageUpload" />
            {{ uploadingStem ? '上传中…' : '📷 插入图片' }}
          </label>
          <small>图片会插入到题干末尾</small>
        </div>

        <!-- 单选 / 多选 -->
        <template v-if="['single', 'multiple'].includes(newQuestion.question_type)">
          <label>选项</label>
          <div class="option-editor">
            <div v-for="(opt, i) in newQuestion.options" :key="i" class="option-edit-row">
              <span class="option-letter">{{ letters[i] }}</span>
              <input v-model.trim="newQuestion.options[i]" :placeholder="`选项 ${letters[i]}`" />
              <button type="button" class="icon-btn" @click="removeOption(i)" :disabled="newQuestion.options.length <= 2">✕</button>
            </div>
            <button type="button" class="add-option-btn" @click="addOption" :disabled="newQuestion.options.length >= 8">＋ 添加选项</button>
          </div>

          <label>正确答案</label>
          <div class="answer-picker">
            <template v-if="newQuestion.question_type === 'single'">
              <button
                v-for="(_, i) in newQuestion.options"
                :key="i"
                type="button"
                class="answer-pick-btn"
                :class="{ active: newQuestion.correct_answer === letters[i] }"
                @click="newQuestion.correct_answer = letters[i]"
              >{{ letters[i] }}</button>
            </template>
            <template v-else>
              <button
                v-for="(_, i) in newQuestion.options"
                :key="i"
                type="button"
                class="answer-pick-btn"
                :class="{ active: newQuestion.correct_answer.includes(letters[i]) }"
                @click="toggleMultiAnswer(letters[i])"
              >{{ letters[i] }}</button>
            </template>
          </div>
        </template>

        <!-- 判断题 -->
        <template v-else-if="newQuestion.question_type === 'judge'">
          <label>正确答案</label>
          <div class="answer-picker">
            <button type="button" class="answer-pick-btn" :class="{ active: newQuestion.correct_answer === 'A' }" @click="newQuestion.correct_answer = 'A'">正确</button>
            <button type="button" class="answer-pick-btn" :class="{ active: newQuestion.correct_answer === 'B' }" @click="newQuestion.correct_answer = 'B'">错误</button>
          </div>
        </template>

        <!-- 填空 / 简答 / 计算 -->
        <template v-else>
          <label for="q-answer">参考答案</label>
          <textarea
            id="q-answer"
            v-model.trim="newQuestion.correct_answer"
            rows="3"
            placeholder="标准答案（可以插入图片，图片型答案将无法自动判分）"
            required
          ></textarea>
          <div class="image-actions">
            <label class="image-upload-btn">
              <input type="file" accept="image/*" @change="onAnswerImageUpload" />
              {{ uploadingAnswer ? '上传中…' : '📷 插入答案图片' }}
            </label>
            <small>图片会追加到参考答案末尾</small>
          </div>
          <small class="tip">填空 / 简答 / 计算题的答案使用宽松匹配（忽略空格和标点）</small>
        </template>

        <label for="q-explanation">解析（可选）</label>
        <textarea id="q-explanation" v-model.trim="newQuestion.explanation" placeholder="解题思路或易错原因"></textarea>

        <button class="modal-submit" type="submit" :disabled="saving">
          {{ saving ? '保存中…' : (editingId ? '保存修改' : '保存题目') }}
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
            <p><b>JSON</b>：数组，每项含 <code>stem</code>、<code>question_type</code>、<code>options</code>、<code>correct_answer</code>、<code>explanation</code>。</p>
            <p><b>题型</b>：<code>single</code> / <code>multiple</code> / <code>judge</code> / <code>blank</code> / <code>short</code> / <code>calc</code>。</p>
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
              <span class="cut-card-tag">{{ typeLabel(question) }}</span>
            </header>

            <p class="cut-card-stem">{{ plainStem(question.stem) }}</p>

            <ul v-if="question.options && question.options.length" class="cut-card-options">
              <li v-for="(opt, i) in question.options" :key="i" :class="{ correct: isCorrectOption(question, i) }">
                <span class="opt-key">{{ letters[i] }}</span>
                <span>{{ opt }}</span>
              </li>
            </ul>
            <p v-else class="cut-card-answer">
              <b>参考答案</b>{{ question.correct_answer }}
            </p>

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

const letters = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H']

type Bank = { id: number; name: string; subject: string; description: string; question_count: number }

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
  correct_answer?: string
  explanation?: string
}

type CutQuestion = Question & { correct_answer: string; explanation: string }

const router = useRouter()
const route = useRoute()
const bankId = Number(route.params.id)

const loading = ref(true)
const saving = ref(false)
const uploadingStem = ref(false)
const uploadingAnswer = ref(false)
const bank = ref<Bank | null>(null)
const questions = ref<Question[]>([])

const query = ref('')
const selectedIds = ref<number[]>([])
const showNotes = ref(false)
const showQuestionDialog = ref(false)

const editingId = ref<number | null>(null)
const newQuestion = ref({
  stem: '',
  explanation: '',
  question_type: 'single',
  options: ['', ''] as string[],
  correct_answer: '',
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

// ==================== 计算 ====================

const normalQuestions = computed(() => questions.value.filter(q => !q.is_cut))
const wrongQuestions = computed(() => questions.value.filter(q => q.wrong_count > 0 && !q.is_cut))
const favoriteQuestions = computed(() => questions.value.filter(q => q.is_favorite && !q.is_cut))
const cutQuestions = computed(() => questions.value.filter(q => q.is_cut))
const noteQuestions = computed(() => questions.value.filter(q => q.note && q.note.length > 0))

const visibleQuestions = computed(() =>
  questions.value.filter(q => plainStem(q.stem).includes(query.value) || q.note.includes(query.value))
)

const allSelected = computed(() =>
  visibleQuestions.value.length > 0 &&
  visibleQuestions.value.every(q => selectedIds.value.includes(q.id))
)

const allCutSelected = computed(() =>
  cutList.value.length > 0 && cutList.value.every(q => cutSelectedIds.value.includes(q.id))
)

const allTypes = [
  { value: 'single', label: '单选题' },
  { value: 'multiple', label: '多选题' },
  { value: 'judge', label: '判断题' },
  { value: 'blank', label: '填空题' },
  { value: 'short', label: '简答题' },
  { value: 'calc', label: '计算题' },
]

// 分题型：有图的题归入"看图题"，不出现在原题型里
const typeList = computed(() => {
  const imageQuestions = normalQuestions.value.filter(q => hasImage(q.stem))
  const plainQuestions = normalQuestions.value.filter(q => !hasImage(q.stem))

  const base = [
    { key: 'single', label: '单选题', desc: '单项选择' },
    { key: 'multiple', label: '多选题', desc: '多项选择' },
    { key: 'judge', label: '判断题', desc: '对或错' },
    { key: 'blank', label: '填空题', desc: '填写答案' },
    { key: 'short', label: '简答题', desc: '文字作答' },
    { key: 'calc', label: '计算题', desc: '计算过程' },
    { key: 'image', label: '看图题', desc: '题干含图片' },
  ]
  return base.map(t => {
    const count = t.key === 'image'
      ? imageQuestions.length
      : plainQuestions.filter(q => q.question_type === t.key).length
    return { ...t, count }
  })
})

// ==================== 工具 ====================

function hasImage(text: string) {
  return /!\[[^\]]*\]\([^)]+\)/.test(text || '')
}

function plainStem(text: string): string {
  if (!text) return ''
  return text.replace(/!\[[^\]]*\]\([^)]+\)/g, '［图片］').replace(/\n/g, ' ').trim()
}

// 有图 → "看图题"，无图 → 具体题型
function typeLabel(q: Question) {
  if (hasImage(q.stem)) return '看图题'
  return baseTypeLabel(q.question_type)
}

function baseTypeLabel(t: string) {
  const map: Record<string, string> = {
    single: '单选题',
    multiple: '多选题',
    judge: '判断题',
    blank: '填空题',
    short: '简答题',
    calc: '计算题',
  }
  return map[t] || t
}

function isCorrectOption(q: CutQuestion, index: number) {
  const ans = String(q.correct_answer || '').toUpperCase()
  return ans.includes(letters[index])
}

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`
}

// ==================== 加载 ====================

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

// ==================== 交互 ====================

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
  const preview = plainStem(question.stem).slice(0, 60)
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

// ==================== 新增 / 编辑弹窗 ====================

function openAddDialog() {
  editingId.value = null
  newQuestion.value = {
    stem: '',
    explanation: '',
    question_type: 'single',
    options: ['', ''],
    correct_answer: '',
  }
  showQuestionDialog.value = true
}

async function openEditDialog(q: Question) {
  editingId.value = q.id
  try {
    const detail = await loadQuestionDetail(q.id)
    newQuestion.value = {
      stem: detail.stem,
      explanation: detail.explanation || '',
      question_type: detail.question_type,
      options: detail.options && detail.options.length ? [...detail.options] : ['', ''],
      correct_answer: detail.correct_answer || '',
    }
    showQuestionDialog.value = true
  } catch (e: any) {
    toast.error(e.message || '加载题目失败')
  }
}

async function loadQuestionDetail(id: number): Promise<CutQuestion> {
  // 从斩题列表（带答案的）里找
  try {
    const list = await request.get(
      `/banks/${bankId}/questions?filter_type=cut`
    ) as unknown as CutQuestion[]
    const found = list.find(q => q.id === id)
    if (found) return found
  } catch { /* 忽略 */ }

  // 找不到就从当前列表取（可能没有答案）
  const q = questions.value.find(x => x.id === id)
  if (!q) throw new Error('找不到题目')
  return { ...q, correct_answer: '', explanation: '' }
}

function closeQuestionDialog() {
  if (saving.value || uploadingStem.value || uploadingAnswer.value) return
  showQuestionDialog.value = false
  editingId.value = null
}

function addOption() {
  if (newQuestion.value.options.length >= 8) return
  newQuestion.value.options.push('')
}

function removeOption(i: number) {
  if (newQuestion.value.options.length <= 2) return
  newQuestion.value.options.splice(i, 1)
}

function toggleMultiAnswer(letter: string) {
  const cur = newQuestion.value.correct_answer || ''
  if (cur.includes(letter)) {
    newQuestion.value.correct_answer = cur.replace(letter, '')
  } else {
    newQuestion.value.correct_answer = [...(cur + letter)].sort().join('')
  }
}

// 上传图片到题干
async function onStemImageUpload(e: Event) {
  await uploadTo('stem', e, uploadingStem)
}

// 上传图片到答案
async function onAnswerImageUpload(e: Event) {
  await uploadTo('correct_answer', e, uploadingAnswer)
}

async function uploadTo(
  field: 'stem' | 'correct_answer',
  e: Event,
  loadingRef: { value: boolean },
) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return

  loadingRef.value = true
  try {
    const fd = new FormData()
    fd.append('file', file)
    const res = await request.post('/upload', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }) as unknown as { url: string }

    const md = `\n\n![](${res.url})`
    newQuestion.value[field] = (newQuestion.value[field] || '') + md
    toast.success('图片已插入')
  } catch (e: any) {
    toast.error(e.message || '上传失败')
  } finally {
    loadingRef.value = false
    input.value = ''
  }
}

async function saveQuestion() {
  if (!newQuestion.value.stem.trim()) {
    toast.warning('请输入题干')
    return
  }

  // 判断题自动补默认答案
  if (newQuestion.value.question_type === 'judge' && !newQuestion.value.correct_answer) {
    newQuestion.value.correct_answer = 'A'
  }

  if (!newQuestion.value.correct_answer) {
    toast.warning('请设置正确答案')
    return
  }

  saving.value = true
  try {
    const payload = {
      stem: newQuestion.value.stem,
      question_type: newQuestion.value.question_type,
      options: ['single', 'multiple'].includes(newQuestion.value.question_type)
        ? newQuestion.value.options.filter(o => o.trim())
        : [],
      correct_answer: newQuestion.value.correct_answer,
      explanation: newQuestion.value.explanation,
    }

    if (editingId.value) {
      await request.put(`/questions/${editingId.value}`, payload)
      toast.success('题目已更新')
    } else {
      await request.post(`/banks/${bankId}/questions`, payload)
      toast.success('题目已保存')
    }

    showQuestionDialog.value = false
    editingId.value = null
    await loadQuestions()
    await loadBank()
  } catch (e: any) {
    toast.error(e.message || '保存失败')
  } finally {
    saving.value = false
  }
}

// ==================== 斩题弹窗 ====================

async function openCutDialog() {
  try {
    cutList.value = await request.get(`/banks/${bankId}/questions?filter_type=cut`) as unknown as CutQuestion[]
    cutSelectedIds.value = []
    showCutDialog.value = true
  } catch (e: any) {
    toast.error(e.message || '加载失败')
  }
}

function closeCutDialog() { showCutDialog.value = false }

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
  cutSelectedIds.value = allCutSelected.value ? [] : cutList.value.map(q => q.id)
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
  const confirmed = window.confirm(`确定恢复全部 ${cutList.value.length} 道题吗？`)
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
    cutList.value = await request.get(`/banks/${bankId}/questions?filter_type=cut`) as unknown as CutQuestion[]
  } catch (e: any) {
    toast.error(e.message || '刷新失败')
  }
}

// ==================== 练习跳转 ====================

function practiceAllCut() {
  if (!cutList.value.length) return
  sessionStorage.setItem('practice-selection', JSON.stringify(cutList.value.map(q => q.id)))
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
  router.push({ path: '/practice', query: { bank: bankId, source } })
}

function startPracticeByType(key: string) {
  if (key === 'image') {
    const list = normalQuestions.value.filter(q => hasImage(q.stem))
    if (!list.length) return
    sessionStorage.setItem('practice-selection', JSON.stringify(list.map(q => q.id)))
    router.push({ path: '/practice', query: { bank: bankId, source: 'image' } })
  } else {
    router.push({ path: '/practice', query: { bank: bankId, source: 'type', qtype: key } })
  }
}

// ==================== 批量导入 ====================

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
    setTimeout(() => closeImport(), 900)
  } catch (e: any) {
    importError.value = e.message || '导入失败'
    toast.error(e.message || '导入失败')
  } finally {
    importing.value = false
  }
}

function downloadJsonTemplate() {
  const sample = [
    { stem: '1 + 1 等于几？', question_type: 'single', options: ['1', '2', '3', '4'], correct_answer: 'B', explanation: '1+1=2' },
    { stem: '以下哪些是编程语言？', question_type: 'multiple', options: ['Python', 'HTML', 'Java', 'CSS'], correct_answer: 'AC', explanation: '' },
    { stem: '中国的首都是____。', question_type: 'blank', options: [], correct_answer: '北京', explanation: '' },
    { stem: '简述 TCP 三次握手。', question_type: 'short', options: [], correct_answer: '客户端发送SYN，服务端回复SYN+ACK，客户端再发送ACK', explanation: '' },
    { stem: '计算 12 × 8。', question_type: 'calc', options: [], correct_answer: '96', explanation: '' },
  ]
  const blob = new Blob([JSON.stringify(sample, null, 2)], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = '题目导入模板.json'
  a.click()
  URL.revokeObjectURL(url)
}
</script>

<style scoped>
.bank-page { min-height: 100vh; color: #20332b; background: #f5f8f6; }
.bank-header { height: 66px; display: flex; align-items: center; justify-content: space-between; padding: 0 clamp(20px, 6vw, 86px); border-bottom: 1px solid #e0e8e3; background: rgba(255,255,255,.92); }
.back-button, .header-actions button { border: 0; color: #466056; background: transparent; font-size: 14px; }
.back-button { display: flex; gap: 9px; align-items: center; color: #254b3f; font-weight: 600; font-size: 15px; cursor: pointer; }
.bank-content { max-width: 1080px; margin: 0 auto; padding: 52px 28px 80px; }
.bank-hero { display: flex; justify-content: space-between; align-items: flex-start; gap: 20px; }
.eyebrow { margin: 0 0 10px; color: #6f9083; font-size: 11px; letter-spacing: 1.3px; font-weight: 700; }
.bank-hero h1 { margin: 0; font-size: clamp(28px, 4vw, 38px); font-weight: 650; }
.bank-hero p:last-child { margin: 10px 0 0; color: #75847c; font-size: 14px; }
.bank-subject { padding: 8px 12px; border-radius: 7px; color: #1a775e; background: #e3f4ec; font-size: 13px; font-weight: 600; }
.all-practice { display: flex; align-items: center; gap: 16px; width: 100%; margin-top: 34px; border: 0; border-radius: 14px; padding: 20px; color: #fff; background: linear-gradient(120deg, #197b60, #2faf86); text-align: left; box-shadow: 0 12px 24px rgba(30,133,101,.17); cursor: pointer; }
.all-practice:disabled, .feature-card:disabled, .practice-grid button:disabled, .type-card:disabled { opacity: .48; cursor: not-allowed; }
.play-icon { display: grid; place-items: center; flex: 0 0 42px; width: 42px; height: 42px; border-radius: 12px; background: rgba(255,255,255,.2); font-size: 16px; }
.all-practice strong, .all-practice small { display: block; }
.all-practice strong { font-size: 17px; }
.all-practice small { margin-top: 5px; opacity: .78; font-size: 13px; }
.all-practice i { margin-left: auto; font-size: 24px; font-style: normal; }
.feature-section { margin-top: 48px; }
.section-heading { display: flex; justify-content: space-between; align-items: end; margin-bottom: 16px; }
.section-heading h2 { margin: 0; font-size: 20px; }
.section-heading > span { color: #85928b; font-size: 13px; }
.feature-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 13px; }
.feature-card, .practice-grid button { min-height: 155px; display: flex; flex-direction: column; align-items: flex-start; border: 1px solid #e0e8e3; border-radius: 13px; padding: 17px; color: #2d4238; background: #fff; text-align: left; transition: transform .16s, box-shadow .16s, border-color .16s; cursor: pointer; }
.feature-card:hover:not(:disabled), .practice-grid button:hover:not(:disabled), .type-card:hover:not(:disabled) { border-color: #94cdb7; box-shadow: 0 8px 18px rgba(31,83,66,.08); transform: translateY(-2px); }
.feature-icon { display: grid; place-items: center; width: 35px; height: 35px; margin-bottom: auto; border-radius: 10px; font-size: 17px; font-weight: 700; }
.wrong .feature-icon { color: #d05b54; background: #fff0ef; }
.favorite .feature-icon { color: #df9929; background: #fff5de; }
.cut .feature-icon { color: #5c7cd1; background: #eef2ff; font-size: 14px; }
.note .feature-icon { color: #2b9677; background: #e8f8f1; }
.feature-card strong, .practice-grid strong { margin-top: 17px; font-size: 15px; }
.feature-card small, .practice-grid small { margin-top: 7px; color: #84918b; font-size: 12px; }
.type-grid { display: grid; grid-template-columns: repeat(7, 1fr); gap: 10px; }
.type-card { display: flex; flex-direction: column; align-items: flex-start; border: 1px solid #e0e8e3; border-radius: 12px; padding: 14px; color: #2d4238; background: #fff; text-align: left; cursor: pointer; transition: transform .16s, border-color .16s, box-shadow .16s; }
.type-count { display: grid; place-items: center; min-width: 28px; height: 22px; padding: 0 8px; margin-bottom: 10px; border-radius: 6px; color: #28775f; background: #e7f5ee; font-size: 12px; font-weight: 700; }
.type-card strong { font-size: 14px; }
.type-card small { margin-top: 5px; color: #84918b; font-size: 11px; }
.practice-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 13px; }
.practice-grid button { position: relative; min-height: 175px; }
.method-icon { display: grid; place-items: center; width: 43px; height: 43px; border-radius: 13px; font-size: 22px; }
.green { color: #258568; background: #e4f5ed; }
.blue { color: #477fbd; background: #e9f2fd; }
.orange { color: #c17636; background: #fff0df; }
.practice-grid em { margin-top: auto; color: #9aa59f; font-size: 12px; font-style: normal; }
.modal-backdrop { position: fixed; z-index: 10; inset: 0; display: grid; place-items: center; padding: 20px; background: rgba(20,45,35,.35); }
.modal { width: min(100%, 490px); max-height: min(650px, 85vh); overflow: auto; border-radius: 16px; padding: 24px; background: #fff; box-shadow: 0 18px 48px rgba(19,49,37,.2); }
.modal-head { display: flex; justify-content: space-between; align-items: start; margin-bottom: 20px; }
.modal-head h2 { margin: 0; font-size: 21px; }
.modal-head button { border: 0; color: #7e8c85; background: transparent; font-size: 13px; cursor: pointer; }
.note-item { padding: 14px 0; border-top: 1px solid #eef2f0; }
.note-item strong { font-size: 14px; }
.note-item p { margin: 8px 0 0; color: #718078; font-size: 13px; line-height: 1.65; }
.not-found { padding: 150px 24px; text-align: center; }
.not-found h1 { font-size: 25px; }
.not-found p { color: #77857d; }
.not-found button { margin-top: 12px; border: 0; border-radius: 8px; padding: 11px 15px; color: #fff; background: #217b61; cursor: pointer; }
.status-state { padding: 150px 24px; text-align: center; color: #77857d; }
.question-manager { margin-top: 48px; border-top: 1px solid #dfe8e2; padding-top: 28px; }
.manager-heading { display: flex; align-items: end; justify-content: space-between; gap: 20px; }
.manager-heading h2 { margin: 0; font-size: 20px; }
.manager-heading p:last-child { margin: 7px 0 0; color: #819088; font-size: 13px; }
.manager-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.manager-actions input { width: 190px; height: 40px; border: 1px solid #d8e3dd; border-radius: 7px; padding: 0 11px; color: #3d4c45; outline: none; font-size: 13px; }
.outline-button, .select-practice { height: 40px; border: 1px solid #238266; border-radius: 7px; padding: 0 13px; color: #1d775e; background: #fff; font-weight: 600; cursor: pointer; }
.outline-button:disabled { opacity: .5; cursor: not-allowed; }
.batch-cut-btn { border-color: #5c7cd1; color: #455993; }
.batch-cut-btn:hover:not(:disabled) { background: #f4f6ff; }
.select-practice { color: #fff; background: #238266; }
.select-practice:disabled { opacity: .5; cursor: not-allowed; }
.question-list { margin-top: 18px; border: 1px solid #e1e9e4; background: #fff; }
.question-row { display: grid; grid-template-columns: 18px 84px minmax(0, 1fr) auto; gap: 14px; align-items: center; padding: 18px 20px; border-bottom: 1px solid #eaf0ec; cursor: pointer; }
.question-row:last-child { border-bottom: 0; }
.question-row.selected { background: #f2faf6; }
.question-row.cutted { opacity: .62; background: #f8f9f8; }
.question-row input { width: 16px; height: 16px; accent-color: #238266; }
.row-type { padding: 6px 7px; color: #28775f; background: #e7f5ee; text-align: center; font-size: 12px; white-space: nowrap; }
.row-main strong { color: #263b31; font-size: 15px; }
.row-main p { margin: 6px 0; color: #74827b; font-size: 13px; }
.row-main small { color: #9aa59f; font-size: 12px; }
.row-actions { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.row-btn { min-width: 68px; border: 1px solid #e0e8e3; border-radius: 6px; padding: 6px 10px; color: #6d8077; background: #fff; font-size: 12px; cursor: pointer; white-space: nowrap; transition: border-color .18s, color .18s, background .18s; }
.row-btn:hover { border-color: #8ec5b0; color: #28735f; background: #f6fbf8; }
.row-btn.active { border-color: #28735f; color: #28735f; background: #eaf6f0; }
.row-btn.cut:hover { border-color: #8b9ee0; color: #455993; background: #f4f6ff; }
.row-btn.cut.active { border-color: #5c7cd1; color: #455993; background: #eef2ff; }
.row-btn.delete { border-color: #f3d6d1; color: #bf4b3f; background: #fff; }
.row-btn.delete:hover { border-color: #bf4b3f; background: #fff4f2; }
.empty-questions { margin-top: 18px; padding: 60px 20px; border: 1px solid #e1e9e4; text-align: center; background: #fff; }
.empty-questions strong { color: #43564c; }
.empty-questions p { color: #85928b; font-size: 13px; }
.question-modal label { display: block; margin: 16px 0 8px; color: #47594f; font-size: 13px; font-weight: 600; }
.question-modal input, .question-modal select, .question-modal textarea { width: 100%; border: 1px solid #d8e4de; border-radius: 8px; padding: 10px; color: #33473d; background: #fff; outline: none; box-sizing: border-box; font-family: inherit; }
.question-modal textarea { min-height: 72px; resize: vertical; }
.question-modal .tip { display: block; margin-top: 6px; color: #85928b; font-size: 12px; }
.type-picker { display: flex; flex-wrap: wrap; gap: 6px; }
.type-pick-btn { border: 1px solid #d8e4de; border-radius: 8px; padding: 8px 12px; color: #4a675a; background: #fff; font-size: 13px; cursor: pointer; transition: border-color .18s, background .18s, color .18s; }
.type-pick-btn:hover { border-color: #8ec5b0; background: #f6fbf8; }
.type-pick-btn.active { border-color: #28735f; color: #28735f; background: #eaf6f0; font-weight: 600; }
.option-editor { display: grid; gap: 8px; }
.option-edit-row { display: flex; align-items: center; gap: 8px; }
.option-letter { display: grid; place-items: center; flex: 0 0 28px; width: 28px; height: 28px; border-radius: 50%; background: #eaf6f0; color: #28735f; font-size: 12px; font-weight: 700; }
.option-edit-row input { flex: 1; }
.icon-btn { flex: 0 0 30px; width: 30px; height: 30px; border: 1px solid #e0e8e3; border-radius: 6px; background: #fff; color: #b0bcc9; cursor: pointer; }
.icon-btn:hover:not(:disabled) { border-color: #bf4b3f; color: #bf4b3f; }
.icon-btn:disabled { opacity: .4; cursor: not-allowed; }
.add-option-btn { justify-self: start; border: 1px dashed #8ec5b0; border-radius: 8px; padding: 8px 14px; background: #f6fbf8; color: #28735f; font-size: 13px; cursor: pointer; }
.add-option-btn:disabled { opacity: .5; cursor: not-allowed; }
.answer-picker { display: flex; flex-wrap: wrap; gap: 6px; }
.answer-pick-btn { min-width: 44px; height: 36px; border: 1px solid #d8e4de; border-radius: 8px; background: #fff; color: #4a675a; font-size: 13px; font-weight: 600; cursor: pointer; padding: 0 12px; transition: border-color .18s, background .18s, color .18s; }
.answer-pick-btn:hover { border-color: #8ec5b0; background: #f6fbf8; }
.answer-pick-btn.active { border-color: #28735f; color: #fff; background: #28735f; }
.image-actions { display: flex; align-items: center; gap: 10px; margin-top: 8px; }
.image-upload-btn { display: inline-flex; align-items: center; gap: 6px; border: 1px solid #28735f; border-radius: 8px; padding: 8px 14px; color: #28735f; background: #fff; font-size: 13px; font-weight: 600; cursor: pointer; transition: background .18s; }
.image-upload-btn:hover { background: #eaf6f0; }
.image-upload-btn input { display: none; }
.image-actions small { color: #85928b; font-size: 12px; }
.modal-submit { width: 100%; margin-top: 22px; border: 0; border-radius: 9px; padding: 12px; color: #fff; background: #238266; font-weight: 600; cursor: pointer; }
.modal-submit:disabled { opacity: .6; cursor: not-allowed; }
.import-modal { max-width: 520px; }
.import-tip { margin: 0 0 16px; color: #718078; font-size: 13px; line-height: 1.7; }
.import-tip b { color: #28735f; }
.import-drop { display: grid; place-items: center; gap: 4px; width: 100%; min-height: 130px; border: 2px dashed #d8e3dd; border-radius: 12px; padding: 20px; color: #6d8077; background: #fafcfb; text-align: center; cursor: pointer; transition: border-color .18s, background .18s; }
.import-drop:hover { border-color: #8ec5b0; background: #f4faf7; }
.import-drop.has-file { border-style: solid; border-color: #28735f; background: #f1f9f5; color: #28735f; }
.import-drop input { display: none; }
.import-drop .drop-icon { font-size: 26px; }
.import-drop strong { font-size: 15px; color: #2d4238; }
.import-drop.has-file strong { color: #17644f; }
.import-drop small { font-size: 12px; }
.import-error { margin: 14px 0 0; padding: 9px 12px; border-left: 3px solid #bf4b3f; color: #a13c31; background: #fff4f2; font-size: 13px; border-radius: 4px; }
.import-success { margin: 14px 0 0; padding: 9px 12px; border-left: 3px solid #28735f; color: #1f6956; background: #f1f9f5; font-size: 13px; border-radius: 4px; }
.template-row { display: flex; align-items: center; gap: 8px; margin-top: 16px; color: #718078; font-size: 13px; }
.link-button { border: 0; padding: 4px 6px; color: #28735f; background: transparent; font-size: 13px; font-weight: 600; cursor: pointer; border-radius: 6px; transition: background .18s; }
.link-button:hover { background: #eaf6f0; }
a.link-button { text-decoration: none; display: inline-block; }
.format-details { margin-top: 12px; border: 1px solid #e0e8e3; border-radius: 10px; background: #fafcfb; overflow: hidden; }
.format-details summary { padding: 10px 14px; color: #4a675a; font-size: 13px; cursor: pointer; list-style: none; }
.format-details summary::marker { display: none; }
.format-details summary::after { content: '▾'; float: right; color: #8b9690; font-size: 11px; transition: transform .18s; }
.format-details[open] summary::after { transform: rotate(180deg); }
.format-body { padding: 4px 14px 12px; border-top: 1px solid #eef2f0; color: #6d8077; font-size: 12.5px; line-height: 1.7; }
.format-body p { margin: 8px 0; }
.format-body code { padding: 1px 5px; border-radius: 4px; background: #eef2f0; color: #1f6956; font-size: 12px; }
.format-body b { color: #2d4238; }
.cut-hint { margin: 6px 0 0; color: #85928b; font-size: 12px; }
.cut-modal { width: min(100%, 640px); max-width: 640px; max-height: 85vh; display: flex; flex-direction: column; padding: 24px 0 0; }
.cut-modal .modal-head { padding: 0 24px; margin-bottom: 16px; }
.cut-toolbar { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; padding: 0 24px 14px; border-bottom: 1px solid #eef2f0; }
.cut-check-all { display: inline-flex; align-items: center; gap: 6px; color: #4a675a; font-size: 13px; cursor: pointer; }
.cut-check-all input { width: 15px; height: 15px; accent-color: #28735f; }
.cut-selected-count { color: #85928b; font-size: 12px; }
.cut-toolbar-actions { display: flex; gap: 8px; margin-left: auto; flex-wrap: wrap; }
.cut-tool-btn { height: 36px; border-radius: 8px; padding: 0 12px; font-size: 13px; font-weight: 600; cursor: pointer; transition: background .18s, border-color .18s; }
.cut-tool-btn:disabled { opacity: .6; cursor: not-allowed; }
.cut-tool-btn.restore { border: 1px solid #8b9ee0; color: #455993; background: #f4f6ff; }
.cut-tool-btn.restore:hover:not(:disabled) { background: #e0e7ff; }
.cut-tool-btn.restore-all { border: 1px solid #d8e3dd; color: #2c6f5a; background: #fff; }
.cut-tool-btn.restore-all:hover:not(:disabled) { border-color: #8ec5b0; background: #f6fbf8; }
.cut-tool-btn.primary { border: 1px solid #1f6956; color: #fff; background: #1f6956; }
.cut-tool-btn.primary:hover:not(:disabled) { background: #175746; }
.cut-grid { flex: 1; overflow-y: auto; padding: 16px 24px 24px; display: grid; gap: 14px; }
.cut-card { border: 1px solid #e0e8e3; border-radius: 12px; padding: 16px 18px; background: #fff; transition: border-color .18s, box-shadow .18s, background .18s; }
.cut-card:hover { border-color: #8ec5b0; box-shadow: 0 4px 14px rgba(31,83,66,.05); }
.cut-card.selected { border-color: #28735f; background: #f6fbf8; }
.cut-card-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.cut-card-check { display: inline-flex; align-items: center; gap: 8px; cursor: pointer; }
.cut-card-check input { width: 15px; height: 15px; accent-color: #28735f; }
.cut-card-index { color: #7a8b9b; font-size: 12px; font-weight: 600; }
.cut-card-tag { padding: 4px 8px; border-radius: 6px; color: #28775f; background: #e7f5ee; font-size: 12px; font-weight: 600; }
.cut-card-stem { margin: 0 0 12px; color: #2d4238; font-size: 14.5px; font-weight: 600; line-height: 1.6; }
.cut-card-options { list-style: none; margin: 0; padding: 0; display: grid; gap: 6px; }
.cut-card-options li { display: flex; align-items: center; gap: 9px; padding: 8px 11px; border: 1px solid #eef2f0; border-radius: 8px; color: #4d665b; background: #fafcfb; font-size: 13.5px; }
.cut-card-options li.correct { border-color: #28735f; color: #17644f; background: #eaf6f0; font-weight: 600; }
.cut-card-options .opt-key { display: grid; place-items: center; flex: 0 0 22px; width: 22px; height: 22px; border-radius: 50%; background: #fff; border: 1px solid #dbe5df; font-size: 11px; font-weight: 700; color: #66766e; }
.cut-card-options li.correct .opt-key { border-color: #28735f; color: #fff; background: #28735f; }
.cut-card-answer { margin: 0; padding: 10px 12px; border-radius: 8px; background: #eaf6f0; color: #17644f; font-size: 13px; line-height: 1.6; }
.cut-card-answer b { margin-right: 6px; color: #1f6956; }
.cut-card-explanation { margin: 12px 0 0; padding: 9px 12px; border-left: 3px solid #28735f; border-radius: 4px; background: #f1f9f5; color: #4d665b; font-size: 12.5px; line-height: 1.7; }
.cut-card-explanation b { margin-right: 6px; color: #1f6956; }
.cut-card-actions { display: flex; gap: 8px; margin-top: 14px; }
.cut-card-actions .row-btn { flex: 1; min-width: 0; height: 36px; border: 1px solid #d8e3dd; border-radius: 8px; color: #4a675a; background: #fff; font-size: 13px; font-weight: 600; cursor: pointer; transition: border-color .18s, background .18s, color .18s; }
.cut-card-actions .row-btn:hover { border-color: #8ec5b0; background: #f6fbf8; }
.cut-card-actions .row-btn.restore { border-color: #8b9ee0; color: #455993; background: #f4f6ff; }
.cut-card-actions .row-btn.restore:hover:not(:disabled) { background: #e0e7ff; }
.cut-card-actions .row-btn:disabled { opacity: .6; cursor: not-allowed; }
.empty-cut { padding: 60px 24px; text-align: center; color: #9aa59f; font-size: 13px; }
@media (max-width: 900px) { .type-grid { grid-template-columns: repeat(4, 1fr); } }
@media (max-width: 700px) {
  .bank-header { padding: 0 20px; }
  .bank-content { padding: 35px 20px 60px; }
  .feature-grid { grid-template-columns: repeat(2, 1fr); }
  .type-grid { grid-template-columns: repeat(3, 1fr); }
  .practice-grid { grid-template-columns: 1fr; }
  .practice-grid button { min-height: 130px; }
  .manager-heading { align-items: flex-start; flex-direction: column; }
  .manager-actions { width: 100%; }
  .manager-actions input { flex: 1; min-width: 170px; }
  .question-row { grid-template-columns: 18px 74px minmax(0, 1fr); padding: 15px; }
  .row-actions { grid-column: 3; justify-self: start; margin-top: 8px; }
  .cut-toolbar { padding: 0 16px 12px; }
  .cut-grid { padding: 14px 16px 20px; }
  .cut-toolbar-actions { width: 100%; margin-left: 0; }
  .cut-tool-btn { flex: 1; }
}
</style>