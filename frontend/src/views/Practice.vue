<template>
  <main class="practice-page">
    <header class="practice-header">
      <button class="back-button" type="button" @click="backToBank">
        ← <span>返回题库</span>
      </button>
      <div class="mode-switch" role="tablist">
        <button type="button" :class="{ active: mode === 'answer' }" @click="mode = 'answer'">答题</button>
        <button type="button" :class="{ active: mode === 'review' }" @click="mode = 'review'">背题</button>
      </div>
      <div class="header-actions">
        <button class="header-action" type="button" @click="showGrid = true">题号导航</button>
        <button class="header-action cut-entry" type="button" @click="openCutPanel">我的斩题</button>
      </div>
    </header>

    <div class="practice-body">
      <section v-if="loading" class="status-block">
        <p>正在加载题目…</p>
      </section>

      <section v-else-if="!questions.length" class="status-block">
        <span class="status-icon">📭</span>
        <h1>没有可练习的题目</h1>
        <p>请回到题库里添加题目，或换一种练习方式。</p>
        <button class="primary-button" type="button" @click="backToBank">返回题库</button>
      </section>

      <section v-else-if="showCompletion" class="status-block">
        <span class="status-icon success">✓</span>
        <h1>本组题目已完成</h1>
        <p>共 {{ questions.length }} 道题 · 答对 {{ correctCount }} 道 · 答错 {{ wrongCount }} 道</p>
        <div class="status-actions">
          <button class="primary-button" type="button" @click="openGrid">查看全部题目</button>
          <button class="ghost-button" type="button" @click="backToBank">返回题库</button>
        </div>
      </section>

      <template v-else-if="currentQuestion">
        <section class="progress-box">
          <div class="progress-info">
            <span>练习进度</span>
            <strong>{{ completedCount }} <i>/ {{ questions.length }}</i></strong>
          </div>
          <div class="progress-track"><i :style="{ width: progressPercent + '%' }"></i></div>
        </section>

        <article class="question-card">
          <div class="question-toolbar">
            <span class="question-tag">{{ typeLabel(currentQuestion) }}</span>
            <div class="question-actions">
              <button
                class="text-button"
                type="button"
                :class="{ 'has-note': currentQuestion.note }"
                @click="openNoteEditor"
              >
                {{ currentQuestion.note ? '✎ 笔记' : '＋ 笔记' }}
              </button>
              <button class="text-button" type="button" @click="shuffleQuestions">打乱题序</button>
            </div>
          </div>

          <h1 class="question-stem" v-html="renderMarkdown(currentQuestion.stem)"></h1>

          <div v-if="mode === 'review'" class="review-hint">
            <span>✦ 背题模式</span>
            <small>点击任意选项可立即查看正确答案和解析</small>
          </div>

          <!-- 选项：单选 / 多选 / 判断 -->
          <div
            v-if="hasOptions(currentQuestion)"
            class="option-list"
          >
            <button
              v-for="(opt, i) in currentQuestion.options"
              :key="i"
              type="button"
              class="option"
              :class="optionClass(i)"
              :disabled="isSubmitted || submitting"
              @click="handleOptionClick(i)"
            >
              <span class="option-key">{{ letters[i] || i + 1 }}</span>
              <span class="option-text">{{ opt }}</span>
              <span v-if="showOptionState(i)" class="option-state">{{ optionStateIcon(i) }}</span>
            </button>
          </div>

          <!-- 输入框：填空 / 简答 / 计算 -->
          <div v-else class="input-area">
            <template v-if="currentQuestion.question_type === 'short' || currentQuestion.question_type === 'calc'">
              <textarea
                v-model="textInput"
                class="answer-textarea"
                rows="5"
                :disabled="isSubmitted || submitting"
                :placeholder="currentQuestion.question_type === 'calc' ? '请写出计算过程，也可以点击下方按钮上传图片' : '请写出你的答案，也可以上传图片'"
              ></textarea>

              <div class="answer-image-actions">
                <label class="answer-image-btn">
                  <input type="file" accept="image/*" :disabled="isSubmitted || submitting" @change="onAnswerImageUpload" />
                  {{ uploadingAnswer ? '上传中…' : '📷 上传图片' }}
                </label>
                <small>可上传手写过程、草稿照片；含图片的答案将改为自评</small>
              </div>
            </template>

            <input
              v-else
              v-model="textInput"
              type="text"
              class="answer-input"
              :disabled="isSubmitted || submitting"
              placeholder="请输入答案"
            />
          </div>

          <button
            v-if="mode === 'answer' && !isSubmitted"
            class="primary-button"
            type="button"
            :disabled="!canSubmit || submitting"
            @click="submitAnswer"
          >
            {{ submitting ? '提交中…' : '提交答案' }}
          </button>

          <section
            v-if="isSubmitted && currentAnswer"
            class="result-card"
            :class="{
              wrong: !currentAnswer.isCorrect && !currentAnswer.needSelfCheck,
              selfcheck: currentAnswer.needSelfCheck
            }"
          >
            <div class="result-head">
              <div class="result-icon">
                {{ currentAnswer.needSelfCheck ? 'i' : (currentAnswer.isCorrect ? '✓' : '✗') }}
              </div>
              <div>
                <strong v-if="currentAnswer.needSelfCheck">请对照参考答案自查</strong>
                <strong v-else-if="currentAnswer.isCorrect">回答正确，继续保持</strong>
                <strong v-else>回答错误</strong>
                <p v-if="!currentAnswer.isCorrect && !currentAnswer.needSelfCheck">
                  正确答案：{{ formatAnswer(currentAnswer.correctAnswer) }}
                </p>
              </div>
            </div>

            <!-- 用户提交的答案（可能含图片） -->
            <div
              v-if="currentAnswer.selectedAnswer && currentAnswer.needSelfCheck"
              class="user-answer"
            >
              <b>你的答案</b>
              <div class="user-answer-body" v-html="renderMarkdown(currentAnswer.selectedAnswer)"></div>
            </div>

            <div
              v-if="currentAnswer.needSelfCheck"
              class="self-check-answer"
              v-html="renderMarkdown(currentAnswer.correctAnswer)"
            ></div>

            <p v-if="currentAnswer.explanation" class="result-explanation">{{ currentAnswer.explanation }}</p>

            <!-- AI 解析 -->
            <div class="ai-explain-section">
              <button
                class="ai-explain-btn"
                type="button"
                :disabled="aiExplaining"
                @click="requestAiExplain"
              >
                {{ aiExplaining ? 'AI 正在分析…' : '✦ AI 解析' }}
              </button>
              <div
                v-if="aiExplanation"
                class="ai-explain-content"
                v-html="renderMarkdown(aiExplanation)"
              ></div>
            </div>
          </section>
        </article>

        <!-- 上一题 / 下一题 -->
        <div class="question-nav">
          <button
            class="nav-btn"
            type="button"
            :disabled="currentIndex === 0"
            @click="goToQuestion(currentIndex - 1)"
          >
            ← 上一题
          </button>
          <span class="nav-progress">{{ currentIndex + 1 }} / {{ questions.length }}</span>
          <button
            class="nav-btn"
            type="button"
            :disabled="currentIndex === questions.length - 1"
            @click="goToQuestion(currentIndex + 1)"
          >
            下一题 →
          </button>
        </div>
      </template>
    </div>

    <footer class="practice-footer">
      <button type="button" @click="backToBank"><span>⌂</span><small>题库</small></button>
      <button type="button" @click="toggleCurrentFavorite">
        <span :class="{ favored: currentQuestion?.is_favorite }">{{ currentQuestion?.is_favorite ? '★' : '☆' }}</span>
        <small>收藏</small>
      </button>
      <button type="button" @click="cutCurrentQuestion">
        <span class="cut-icon">✂</span>
        <small>斩题</small>
      </button>
      <div class="footer-divider"></div>
      <div class="metric correct-metric"><strong>{{ correctCount }}</strong><span>正确</span></div>
      <div class="metric wrong-metric"><strong>{{ wrongCount }}</strong><span>错误</span></div>
      <div class="metric"><strong>{{ completedCount }}/{{ questions.length }}</strong><span>已做题</span></div>
    </footer>

    <!-- 题号导航 -->
    <div v-if="showGrid" class="modal-backdrop" @click.self="showGrid = false">
      <section class="modal grid-modal">
        <div class="modal-head">
          <div>
            <p class="eyebrow">QUESTION NAVIGATOR</p>
            <h2>题目导航</h2>
          </div>
          <button type="button" @click="showGrid = false">关闭</button>
        </div>

        <div class="legend">
          <span><i class="dot dot-correct"></i>正确</span>
          <span><i class="dot dot-wrong"></i>错误</span>
          <span><i class="dot dot-pending"></i>未答</span>
          <span><i class="dot dot-current"></i>当前</span>
        </div>

        <div class="grid">
          <button
            v-for="(q, i) in questions"
            :key="q.id"
            type="button"
            class="grid-btn"
            :class="gridClass(q.id, i)"
            @click="jumpTo(i)"
          >{{ i + 1 }}</button>
        </div>

        <div class="grid-actions">
          <button class="ghost-button" type="button" @click="shuffleQuestions">打乱题序</button>
          <button class="primary-button" type="button" @click="showGrid = false">继续答题</button>
        </div>
      </section>
    </div>

    <!-- 我的斩题面板 -->
    <div v-if="showCutPanel" class="modal-backdrop" @click.self="closeCutPanel">
      <section class="modal cut-panel">
        <div class="modal-head">
          <div>
            <p class="eyebrow">CUT QUESTIONS</p>
            <h2>我的斩题</h2>
            <p class="cut-panel-hint">共 {{ cutPanelList.length }} 道 · 已移出常规练习</p>
          </div>
          <button type="button" @click="closeCutPanel">关闭</button>
        </div>

        <div v-if="cutPanelList.length" class="cut-panel-grid">
          <article v-for="(q, idx) in cutPanelList" :key="q.id" class="cut-panel-card">
            <header class="cut-panel-head">
              <span class="cut-panel-index">第 {{ idx + 1 }} 题</span>
              <span class="cut-panel-tag">{{ typeLabel(q) }}</span>
            </header>
            <p class="cut-panel-stem" v-html="renderMarkdown(q.stem)"></p>
            <ul v-if="q.options && q.options.length" class="cut-panel-options">
              <li v-for="(opt, i) in q.options" :key="i" :class="{ correct: isCorrectOption(q, i) }">
                <span class="opt-key">{{ letters[i] }}</span>
                <span>{{ opt }}</span>
              </li>
            </ul>
            <p v-else class="cut-panel-answer">
              <b>参考答案：</b>{{ q.correct_answer }}
            </p>
            <p v-if="q.explanation" class="cut-panel-explanation">
              <b>解析</b>{{ q.explanation }}
            </p>
            <footer class="cut-panel-actions">
              <button type="button" class="row-btn restore" :disabled="cutPanelRestoring === q.id" @click="cutPanelRestore(q.id)">
                {{ cutPanelRestoring === q.id ? '恢复中…' : '恢复' }}
              </button>
            </footer>
          </article>
        </div>

        <p v-else class="empty-cut">还没有斩过的题。</p>
      </section>
    </div>

    <!-- 笔记编辑弹窗 -->
    <div v-if="showNoteEditor" class="modal-backdrop" @click.self="closeNoteEditor">
      <section class="modal note-editor-modal">
        <div class="modal-head">
          <div>
            <p class="eyebrow">MY NOTE</p>
            <h2>本题笔记</h2>
          </div>
          <button type="button" @click="closeNoteEditor">关闭</button>
        </div>

        <p class="note-stem">{{ plainStem(currentQuestion?.stem || '') }}</p>

        <textarea
          v-model="noteDraft"
          class="note-textarea"
          rows="6"
          :disabled="savingNote"
          placeholder="记录易错点、解题方法、需要复习的内容…"
        ></textarea>

        <div class="note-actions">
          <button class="ghost-button" type="button" :disabled="savingNote" @click="closeNoteEditor">取消</button>
          <button class="primary-button" type="button" :disabled="savingNote" @click="saveNote">
            {{ savingNote ? '保存中…' : '保存笔记' }}
          </button>
        </div>
      </section>
    </div>

    <!-- 继续上次练习的询问 -->
    <div v-if="showResumePrompt" class="modal-backdrop">
      <section class="modal resume-modal">
        <div class="modal-head">
          <div>
            <p class="eyebrow">CONTINUE PRACTICE</p>
            <h2>发现上次的练习记录</h2>
          </div>
        </div>
        <p class="resume-text">
          上次练习到第 <b>{{ resumeIndex }}</b> 题，已完成 <b>{{ resumeCompleted }}</b> 道。
          是否继续？
        </p>
        <div class="resume-actions">
          <button class="primary-button" type="button" @click="showResumePrompt = false">继续上次</button>
          <button class="ghost-button" type="button" @click="restartFresh">重新开始</button>
        </div>
      </section>
    </div>

    <!-- AI 助手 -->
    <AiAssistant :question-id="currentQuestion?.id ?? 0" />
  </main>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import request from '@/api/request'
import { toast } from '@/composables/useToast'
import AiAssistant from '@/components/AiAssistant.vue'
import { renderMarkdown, plainStem } from '@/utils/renderMarkdown'


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
  correct_answer: string
  explanation: string
}

type AnswerState = {
  selected: number | number[] | string
  selectedAnswer: string
  isCorrect: boolean
  needSelfCheck?: boolean
  correctAnswer: string
  explanation: string
}

const router = useRouter()
const route = useRoute()

const letters = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H']
const bankId = Number(route.query.bank || 0)
const source = String(route.query.source || 'sequential')
const qtypeFilter = String(route.query.qtype || '')

const loading = ref(true)
const submitting = ref(false)
const mode = ref<'answer' | 'review'>('answer')

const questions = ref<Question[]>([])
const answers = ref<Record<number, AnswerState>>({})

const currentIndex = ref(0)
const selected = ref<number | number[] | string | null>(null)
const textInput = ref('')
const showGrid = ref(false)
const showCompletion = ref(false)

const uploadingAnswer = ref(false)

const showCutPanel = ref(false)
const cutPanelList = ref<CutQuestion[]>([])
const cutPanelRestoring = ref<number | null>(null)

// 笔记
const showNoteEditor = ref(false)
const noteDraft = ref('')
const savingNote = ref(false)

// 练习进度恢复
const showResumePrompt = ref(false)
const resumeIndex = ref(0)
const resumeCompleted = ref(0)

// AI 解析
const aiExplaining = ref(false)
const aiExplanation = ref('')

const currentQuestion = computed(() => questions.value[currentIndex.value])
const currentAnswer = computed(() => {
  if (!currentQuestion.value) return null
  return answers.value[currentQuestion.value.id] || null
})
const isSubmitted = computed(() => currentAnswer.value !== null)
const completedCount = computed(() => questions.value.filter(q => answers.value[q.id] !== undefined).length)
const correctCount = computed(() => questions.value.filter(q => answers.value[q.id]?.isCorrect).length)
const wrongCount = computed(() => questions.value.filter(q => answers.value[q.id] && !answers.value[q.id].isCorrect).length)
const progressPercent = computed(() => questions.value.length ? (completedCount.value / questions.value.length) * 100 : 0)

const canSubmit = computed(() => {
  const q = currentQuestion.value
  if (!q) return false

  if (q.question_type === 'multiple') {
    return Array.isArray(selected.value) && selected.value.length > 0
  }
  if (q.question_type === 'blank' || q.question_type === 'short' || q.question_type === 'calc') {
    return textInput.value.trim().length > 0
  }
  return selected.value !== null
})

// ==================== 工具 ====================

function hasImage(text: string) {
  return /!\[[^\]]*\]\([^)]+\)/.test(text || '')
}



function formatAnswer(ans: string) {
  if (!ans) return ''
  if (/^[A-H]+$/.test(ans) && ans.length > 1) {
    return [...ans].join('、')
  }
  return ans
}

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

function hasOptions(q: Question) {
  return ['single', 'multiple', 'judge'].includes(q.question_type)
}

function isCorrectOption(q: CutQuestion, index: number) {
  const ans = String(q.correct_answer || '').toUpperCase()
  return ans.includes(letters[index])
}

// ==================== 加载 ====================

async function loadQuestions() {
  loading.value = true
  try {
    // 先查后端保存的进度
    let savedProgress: any = null
    try {
      const res = await request.get('/practice/progress', {
        params: { bank_id: bankId, source },
      }) as unknown as { progress: any }
      savedProgress = res.progress
    } catch { /* 忽略 */ }

    let url = `/banks/${bankId}/questions`
    if (source === 'type' && qtypeFilter) {
      url += `?question_type=${qtypeFilter}`
    } else if (['wrong', 'favorite', 'cut'].includes(source)) {
      url += `?filter_type=${source}`
    }
    let list = await request.get(url) as unknown as Question[]

    if (source === 'image') {
      list = list.filter(q => hasImage(q.stem))
    }
    if (source === 'type') {
      list = list.filter(q => !hasImage(q.stem))
    }

    // ============ 有进度：恢复 ============
    if (savedProgress && savedProgress.question_ids && savedProgress.question_ids.length) {
      const map = new Map(list.map(q => [q.id, q]))
      const restored = savedProgress.question_ids
        .map((id: number) => map.get(id))
        .filter((q: Question | undefined): q is Question => Boolean(q))

      if (restored.length === savedProgress.question_ids.length) {
        questions.value = restored
        answers.value = savedProgress.answers || {}
        currentIndex.value = Math.min(savedProgress.current_index || 0, restored.length - 1)

        const ans = answers.value[questions.value[currentIndex.value]?.id]
        if (ans) {
          selected.value = ans.selected
          textInput.value = typeof ans.selected === 'string' ? ans.selected : ''
        }

        resumeIndex.value = currentIndex.value + 1
        resumeCompleted.value = Object.keys(answers.value).length
        showResumePrompt.value = true
        loading.value = false
        return
      }
    }

    // ============ 无进度：全新开始 ============
    let ids: number[] = []
    try {
      ids = JSON.parse(sessionStorage.getItem('practice-selection') || '[]')
    } catch {
      ids = []
    }

    questions.value = source === 'selected' && ids.length
      ? list.filter(q => ids.includes(q.id))
      : list

    if (source === 'random') shuffleQuestions()

    currentIndex.value = 0
    selected.value = null
    textInput.value = ''
    showCompletion.value = false
  } catch (e: any) {
    toast.error(e.message || '题目加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(loadQuestions)

watch(currentIndex, (idx) => {
  const q = questions.value[idx]
  if (!q) {
    selected.value = null
    textInput.value = ''
    return
  }
  const ans = answers.value[q.id]
  if (ans) {
    selected.value = ans.selected
    textInput.value = typeof ans.selected === 'string' ? ans.selected : ''
  } else {
    selected.value = null
    textInput.value = ''
  }
  // 切题时清空 AI 解析
  aiExplanation.value = ''
})

// ==================== 页面导航 ====================

function goToQuestion(idx: number) {
  if (idx < 0 || idx >= questions.value.length) return
  currentIndex.value = idx
  showGrid.value = false
  showCompletion.value = false
  scheduleSave()
}

function jumpTo(idx: number) { goToQuestion(idx) }
function openGrid() { showGrid.value = true }

function shuffleQuestions() {
  const arr = [...questions.value]
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[arr[i], arr[j]] = [arr[j], arr[i]]
  }
  questions.value = arr
  currentIndex.value = 0
  selected.value = null
  textInput.value = ''
  showCompletion.value = false
  scheduleSave()
}

// ==================== 作答 ====================

function handleOptionClick(i: number) {
  if (isSubmitted.value || submitting.value) return
  const q = currentQuestion.value
  if (!q) return

  if (q.question_type === 'multiple') {
    const cur = Array.isArray(selected.value) ? selected.value : []
    selected.value = cur.includes(i)
      ? cur.filter(x => x !== i)
      : [...cur, i]
    return
  }

  selected.value = i
  if (mode.value === 'review') submitAnswer()
}

async function onAnswerImageUpload(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return

  uploadingAnswer.value = true
  try {
    const fd = new FormData()
    fd.append('file', file)
    const res = await request.post('/upload', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }) as unknown as { url: string }

    const md = `\n\n![](${res.url})`
    textInput.value = (textInput.value || '') + md
    toast.success('图片已添加')
  } catch (e: any) {
    toast.error(e.message || '上传失败')
  } finally {
    uploadingAnswer.value = false
    input.value = ''
  }
}

async function submitAnswer() {
  if (!currentQuestion.value || submitting.value) return
  const q = currentQuestion.value

  let payload = ''
  if (q.question_type === 'blank' || q.question_type === 'short' || q.question_type === 'calc') {
    payload = textInput.value.trim()
    if (!payload) return
    selected.value = payload
  } else if (q.question_type === 'multiple') {
    if (!Array.isArray(selected.value) || selected.value.length === 0) return
    payload = (selected.value as number[])
      .slice()
      .sort((a, b) => a - b)
      .map(i => letters[i])
      .join('')
  } else {
    if (selected.value === null) return
    payload = letters[selected.value as number]
  }

  submitting.value = true
  try {
    const res = await request.post(`/questions/${q.id}/answer`, {
      selected_answer: payload,
    }) as unknown as {
      correct: boolean
      need_self_check?: boolean
      correct_answer: string
      explanation: string
    }

    answers.value[q.id] = {
      selected: selected.value as any,
      selectedAnswer: payload,
      isCorrect: res.correct,
      needSelfCheck: res.need_self_check || false,
      correctAnswer: res.correct_answer,
      explanation: res.explanation,
    }

    scheduleSave()
  } catch (e: any) {
    toast.error(e.message || '提交失败')
  } finally {
    submitting.value = false
  }
}

// ==================== 选项样式 ====================

function optionClass(i: number) {
  const cls: Record<string, boolean> = {}
  const q = currentQuestion.value
  const ans = currentAnswer.value
  if (!q) return cls

  if (!ans) {
    if (q.question_type === 'multiple') {
      const cur = Array.isArray(selected.value) ? selected.value : []
      if (cur.includes(i)) cls.selected = true
    } else if (selected.value === i) {
      cls.selected = true
    }
    return cls
  }

  const correctLetters = String(ans.correctAnswer).toUpperCase()
  const correctIdx = [...correctLetters].map(ch => letters.indexOf(ch)).filter(x => x >= 0)
  const userLetters = String(ans.selectedAnswer).toUpperCase()
  const userIdx = [...userLetters].map(ch => letters.indexOf(ch)).filter(x => x >= 0)

  if (correctIdx.includes(i)) cls.correct = true
  if (userIdx.includes(i)) cls.selected = true
  if (userIdx.includes(i) && !correctIdx.includes(i)) cls.wrong = true

  return cls
}

function showOptionState(i: number) {
  const ans = currentAnswer.value
  if (!ans) return false
  const correctLetters = String(ans.correctAnswer).toUpperCase()
  const userLetters = String(ans.selectedAnswer).toUpperCase()
  return correctLetters.includes(letters[i]) || userLetters.includes(letters[i])
}

function optionStateIcon(i: number) {
  const ans = currentAnswer.value
  if (!ans) return ''
  const correctLetters = String(ans.correctAnswer).toUpperCase()
  const userLetters = String(ans.selectedAnswer).toUpperCase()
  if (correctLetters.includes(letters[i])) return '✓'
  if (userLetters.includes(letters[i])) return '✗'
  return ''
}

function gridClass(qid: number, idx: number) {
  const cls: Record<string, boolean> = {}
  const ans = answers.value[qid]
  if (ans) cls[ans.isCorrect ? 'correct' : 'wrong'] = true
  else cls.pending = true
  if (idx === currentIndex.value && !showCompletion.value) cls.current = true
  return cls
}

// ==================== 收藏 / 斩题 ====================

async function toggleCurrentFavorite() {
  if (!currentQuestion.value) return
  try {
    const res = await request.post(`/questions/${currentQuestion.value.id}/favorite`) as unknown as { is_favorite: boolean }
    currentQuestion.value.is_favorite = res.is_favorite
    toast.success(res.is_favorite ? '已收藏' : '已取消收藏')
  } catch (e: any) {
    toast.error(e.message || '操作失败')
  }
}

async function cutCurrentQuestion() {
  if (!currentQuestion.value) return
  const q = currentQuestion.value
  if (q.is_cut) {
    toast.warning('这道题已经在斩题库里了')
    return
  }
  try {
    await request.post(`/questions/${q.id}/cut`)
    questions.value.splice(currentIndex.value, 1)
    if (questions.value.length === 0) {
      showCompletion.value = true
      return
    }
    if (currentIndex.value >= questions.value.length) {
      currentIndex.value = questions.value.length - 1
    }
    selected.value = null
    textInput.value = ''
    toast.success('已加入斩题库')
    scheduleSave()
  } catch (e: any) {
    toast.error(e.message || '操作失败')
  }
}

// ==================== 斩题面板 ====================

async function openCutPanel() {
  try {
    cutPanelList.value = await request.get(
      `/banks/${bankId}/questions?filter_type=cut`
    ) as unknown as CutQuestion[]
    showCutPanel.value = true
  } catch (e: any) {
    toast.error(e.message || '加载失败')
  }
}

async function cutPanelRestore(id: number) {
  cutPanelRestoring.value = id
  try {
    await request.post(`/questions/${id}/cut`)
    cutPanelList.value = cutPanelList.value.filter(q => q.id !== id)
    toast.success('已恢复')
  } catch (e: any) {
    toast.error(e.message || '恢复失败')
  } finally {
    cutPanelRestoring.value = null
  }
}

function closeCutPanel() { showCutPanel.value = false }

// ==================== 笔记 ====================

function openNoteEditor() {
  if (!currentQuestion.value) return
  noteDraft.value = currentQuestion.value.note || ''
  showNoteEditor.value = true
}

function closeNoteEditor() {
  if (savingNote.value) return
  showNoteEditor.value = false
  noteDraft.value = ''
}

async function saveNote() {
  if (!currentQuestion.value) return
  savingNote.value = true
  try {
    const res = await request.put(
      `/questions/${currentQuestion.value.id}/note`,
      { note: noteDraft.value }
    ) as unknown as { note: string }

    currentQuestion.value.note = res.note
    toast.success(res.note ? '笔记已保存' : '笔记已清空')
    showNoteEditor.value = false
    noteDraft.value = ''
  } catch (e: any) {
    toast.error(e.message || '保存失败')
  } finally {
    savingNote.value = false
  }
}

// ==================== 练习进度 ====================

let saveTimer: number | null = null

function scheduleSave() {
  if (!questions.value.length) return
  if (saveTimer) window.clearTimeout(saveTimer)
  saveTimer = window.setTimeout(async () => {
    try {
      await request.put('/practice/progress', {
        bank_id: bankId,
        source,
        question_ids: questions.value.map(q => q.id),
        answers: answers.value,
        current_index: currentIndex.value,
      })
    } catch { /* 忽略 */ }
  }, 600)
}

async function clearProgress() {
  try {
    await request.delete('/practice/progress', {
      params: { bank_id: bankId, source },
    })
  } catch { /* 忽略 */ }
}

async function restartFresh() {
  showResumePrompt.value = false
  await clearProgress()
  answers.value = {}
  currentIndex.value = 0
  selected.value = null
  textInput.value = ''
  showCompletion.value = false
  scheduleSave()
}

// ==================== AI 解析 ====================

async function requestAiExplain() {
  if (!currentQuestion.value || aiExplaining.value) return
  aiExplaining.value = true
  aiExplanation.value = ''

  try {
    const token = localStorage.getItem('token')
    const res = await fetch('/api/ai/explain', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
      body: JSON.stringify({
        question_id: currentQuestion.value.id,
        user_answer: currentAnswer.value?.selectedAnswer || '',
      }),
    })

    if (!res.ok) throw new Error('AI 请求失败')

    const reader = res.body?.getReader()
    if (!reader) throw new Error('无法读取流')
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n\n')
      buffer = lines.pop() || ''
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const data = line.slice(6)
          if (data === '[DONE]') continue
          try {
            const parsed = JSON.parse(data)
            if (parsed.error) throw new Error(parsed.error)
            if (parsed.content) aiExplanation.value += parsed.content
          } catch { /* 忽略 */ }
        }
      }
    }
  } catch (e) {
    aiExplanation.value = 'AI 解析加载失败，请检查 Ollama 是否正在运行。'
  } finally {
    aiExplaining.value = false
  }
}

function backToBank() {
  router.push(bankId ? `/banks/${bankId}` : '/home')
}
</script>

<style scoped>

/* KaTeX 公式在 .stem-img 之外额外留白 */
.question-stem :deep(.katex-display),
.cut-panel-stem :deep(.katex-display),
.ai-explain-content :deep(.katex-display),
.self-check-answer :deep(.katex-display),
.user-answer-body :deep(.katex-display) {
  margin: 12px 0;
  overflow-x: auto;
  overflow-y: hidden;
}
.question-stem :deep(.katex),
.cut-panel-stem :deep(.katex),
.ai-explain-content :deep(.katex),
.self-check-answer :deep(.katex),
.user-answer-body :deep(.katex) {
  font-size: 1.05em;
}

.practice-page {
  min-height: 100vh;
  color: #20332b;
  background: #f5f8f6;
  padding-bottom: 76px;
}
.practice-header {
  position: sticky;
  top: 0;
  z-index: 5;
  height: 66px;
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 0 clamp(20px, 6vw, 86px);
  border-bottom: 1px solid #e0e8e3;
  background: rgba(255, 255, 255, .94);
  backdrop-filter: blur(8px);
}
.back-button {
  display: flex;
  gap: 9px;
  align-items: center;
  border: 0;
  color: #254b3f;
  background: transparent;
  font-weight: 600;
  font-size: 15px;
  cursor: pointer;
}
.mode-switch {
  display: flex;
  gap: 3px;
  padding: 4px;
  border-radius: 10px;
  background: #f1f5f3;
  margin-left: auto;
}
.mode-switch button {
  min-width: 60px;
  height: 30px;
  border: 0;
  border-radius: 7px;
  color: #718078;
  background: transparent;
  font-size: 13px;
  cursor: pointer;
  transition: background .18s, color .18s;
}
.mode-switch button.active {
  color: #17644f;
  background: #fff;
  box-shadow: 0 2px 6px rgba(30, 64, 53, .08);
  font-weight: 600;
}
.header-actions {
  display: flex;
  gap: 8px;
}
.header-action {
  border: 1px solid #d8e3dd;
  border-radius: 8px;
  padding: 8px 12px;
  color: #2c6f5a;
  background: #fff;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: border-color .18s, background .18s;
}
.header-action:hover {
  border-color: #8ec5b0;
  background: #f6fbf8;
}
.header-action.cut-entry {
  border-color: #8b9ee0;
  color: #455993;
}
.header-action.cut-entry:hover {
  border-color: #5c7cd1;
  background: #f4f6ff;
}

.practice-body {
  max-width: 780px;
  margin: 0 auto;
  padding: 30px clamp(20px, 5vw, 40px) 40px;
}
.status-block {
  padding: 110px 24px;
  text-align: center;
  color: #77857d;
}
.status-icon {
  display: grid;
  place-items: center;
  width: 60px;
  height: 60px;
  margin: 0 auto 16px;
  border-radius: 50%;
  background: #e7f5ee;
  color: #28735f;
  font-size: 28px;
  font-weight: 700;
}
.status-icon.success {
  background: #dff5eb;
  color: #1f6956;
}
.status-block h1 {
  margin: 0 0 8px;
  color: #1f2d3d;
  font-size: 22px;
}
.status-block p {
  margin: 0 0 24px;
  font-size: 14px;
}
.status-actions {
  max-width: 320px;
  margin: 0 auto;
}
.progress-box {
  padding: 18px 20px;
  border: 1px solid #e0e8e3;
  border-radius: 14px;
  background: #fff;
  margin-bottom: 20px;
}
.progress-info {
  display: flex;
  justify-content: space-between;
  color: #718078;
  font-size: 13px;
}
.progress-info strong {
  color: #1f6956;
  font-weight: 650;
}
.progress-info i {
  color: #a0aaa5;
  font-style: normal;
  font-weight: 400;
}
.progress-track {
  height: 5px;
  overflow: hidden;
  margin-top: 10px;
  border-radius: 99px;
  background: #e8efeb;
}
.progress-track i {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: #28735f;
  transition: width .25s ease;
}
.question-card {
  padding: 26px 26px 24px;
  border: 1px solid #e0e8e3;
  border-radius: 14px;
  background: #fff;
  box-shadow: 0 6px 20px rgba(31, 45, 61, .04);
}
.question-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.question-actions {
  display: flex;
  gap: 4px;
}
.question-tag {
  padding: 5px 10px;
  border-radius: 6px;
  color: #28745f;
  background: #eaf6f0;
  font-size: 12px;
  font-weight: 600;
}
.text-button {
  border: 0;
  padding: 6px 10px;
  border-radius: 6px;
  color: #718078;
  background: transparent;
  font-size: 13px;
  cursor: pointer;
  transition: color .18s, background .18s;
}
.text-button:hover {
  color: #28745f;
  background: #f1f8f5;
}
.text-button.has-note {
  color: #c7823d;
  font-weight: 600;
}
.text-button.has-note:hover {
  background: #fff9ee;
}
.question-stem {
  margin: 20px 0 22px;
  color: #1f2d3d;
  font-size: clamp(19px, 3vw, 24px);
  font-weight: 650;
  line-height: 1.55;
  word-break: break-word;
}
.question-stem :deep(.stem-img) {
  display: block;
  max-width: 100%;
  margin: 14px 0;
  border-radius: 10px;
  border: 1px solid #e0e8e3;
}
.review-hint {
  display: flex;
  flex-direction: column;
  gap: 3px;
  margin-bottom: 16px;
  padding: 12px 14px;
  border-radius: 10px;
  color: #28745f;
  background: #f1f9f5;
  font-size: 13px;
}
.review-hint small {
  color: #7a9289;
}
.option-list {
  display: grid;
  gap: 10px;
}
.option {
  position: relative;
  display: flex;
  align-items: center;
  gap: 14px;
  width: 100%;
  min-height: 60px;
  border: 1px solid #dde7e1;
  border-radius: 12px;
  padding: 10px 16px;
  color: #2d4238;
  background: #fff;
  text-align: left;
  font-size: 15px;
  cursor: pointer;
  transition: border-color .18s, background .18s;
}
.option:hover:not(:disabled) {
  border-color: #8ec5b0;
  background: #f9fcfa;
}
.option.selected {
  border-color: #28735f;
  background: #f1f9f5;
}
.option.correct {
  border-color: #28735f;
  color: #17644f;
  background: #eaf6f0;
}
.option.wrong {
  border-color: #bf4b3f;
  color: #a13c31;
  background: #fff4f2;
}
.option:disabled {
  cursor: default;
}
.option-key {
  display: grid;
  place-items: center;
  flex: 0 0 34px;
  width: 34px;
  height: 34px;
  border: 1px solid #dbe5df;
  border-radius: 50%;
  color: #66766e;
  background: #fff;
  font-size: 13px;
  font-weight: 650;
}
.option.selected .option-key {
  border-color: #28735f;
  color: #fff;
  background: #28735f;
}
.option.correct .option-key {
  border-color: #28735f;
  color: #fff;
  background: #28735f;
}
.option.wrong .option-key {
  border-color: #bf4b3f;
  color: #fff;
  background: #bf4b3f;
}
.option-text {
  line-height: 1.5;
}
.option-state {
  margin-left: auto;
  font-size: 18px;
  font-weight: 700;
}
.option.correct .option-state {
  color: #28735f;
}
.option.wrong .option-state {
  color: #bf4b3f;
}

/* 填空 / 简答 / 计算 输入框 */
.input-area {
  margin: 8px 0 4px;
}
.answer-input {
  width: 100%;
  height: 52px;
  border: 1px solid #dde7e1;
  border-radius: 12px;
  padding: 0 16px;
  font-size: 15px;
  color: #2d4238;
  background: #fff;
  outline: none;
  box-sizing: border-box;
  transition: border-color .18s, box-shadow .18s;
}
.answer-textarea {
  width: 100%;
  border: 1px solid #dde7e1;
  border-radius: 12px;
  padding: 14px 16px;
  font-size: 15px;
  font-family: inherit;
  color: #2d4238;
  background: #fff;
  outline: none;
  resize: vertical;
  box-sizing: border-box;
  line-height: 1.6;
  transition: border-color .18s, box-shadow .18s;
}
.answer-input:focus,
.answer-textarea:focus {
  border-color: #28735f;
  box-shadow: 0 0 0 3px rgba(40, 115, 95, .12);
}
.answer-input:disabled,
.answer-textarea:disabled {
  background: #f7faf8;
  color: #6d8077;
  cursor: not-allowed;
}

/* 简答 / 计算题的上传图片按钮 */
.answer-image-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 10px;
}
.answer-image-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid #28735f;
  border-radius: 8px;
  padding: 8px 14px;
  color: #28735f;
  background: #fff;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background .18s;
}
.answer-image-btn:hover {
  background: #eaf6f0;
}
.answer-image-btn input {
  display: none;
}
.answer-image-actions small {
  color: #85928b;
  font-size: 12px;
}

.primary-button {
  width: 100%;
  height: 48px;
  margin-top: 20px;
  border: 1px solid #1f6956;
  border-radius: 8px;
  color: #fff;
  background: #1f6956;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  transition: background .18s, transform .18s;
}
.primary-button:hover:not(:disabled) {
  background: #175746;
  transform: translateY(-1px);
}
.primary-button:disabled {
  opacity: .6;
  cursor: not-allowed;
}
.ghost-button {
  width: 100%;
  height: 48px;
  margin-top: 10px;
  border: 1px solid #d8e3dd;
  border-radius: 8px;
  color: #2c6f5a;
  background: #fff;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: border-color .18s, background .18s;
}
.ghost-button:hover {
  border-color: #8ec5b0;
  background: #f6fbf8;
}

.question-nav {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 16px;
  padding: 0 4px;
}
.nav-btn {
  flex: 0 0 auto;
  min-width: 110px;
  height: 42px;
  border: 1px solid #d8e3dd;
  border-radius: 10px;
  color: #2c6f5a;
  background: #fff;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: border-color .18s, background .18s, opacity .18s;
}
.nav-btn:hover:not(:disabled) {
  border-color: #8ec5b0;
  background: #f6fbf8;
}
.nav-btn:disabled {
  opacity: .4;
  cursor: not-allowed;
}
.nav-progress {
  color: #718078;
  font-size: 13px;
}

.result-card {
  margin-top: 20px;
  padding: 16px;
  border: 1px solid #ccebdd;
  border-radius: 12px;
  background: #f1f9f5;
}
.result-card.wrong {
  border-color: #f3d6d1;
  background: #fff4f2;
}
.result-card.selfcheck {
  border-color: #c8d6f0;
  background: #f4f7fd;
}
.result-head {
  display: flex;
  align-items: center;
  gap: 12px;
}
.result-icon {
  display: grid;
  place-items: center;
  flex: 0 0 30px;
  width: 30px;
  height: 30px;
  border-radius: 50%;
  color: #fff;
  background: #28735f;
  font-size: 15px;
  font-weight: 700;
}
.wrong .result-icon {
  background: #bf4b3f;
}
.result-card.selfcheck .result-icon {
  background: #477fbd;
}
.result-head strong {
  color: #17644f;
  font-size: 14px;
}
.wrong .result-head strong {
  color: #a13c31;
}
.result-card.selfcheck .result-head strong {
  color: #2c5187;
}
.result-head p {
  margin: 4px 0 0;
  color: #6d8077;
  font-size: 13px;
}
.result-explanation {
  margin: 14px 0 0;
  padding: 12px 14px;
  border-radius: 10px;
  background: rgba(255, 255, 255, .7);
  color: #4d665b;
  font-size: 13px;
  line-height: 1.7;
}

.user-answer {
  margin-top: 12px;
  padding: 12px 14px;
  border-radius: 10px;
  background: rgba(255, 255, 255, .8);
  color: #35483f;
  font-size: 14px;
  line-height: 1.7;
}
.user-answer > b {
  display: block;
  margin-bottom: 6px;
  color: #2c5187;
  font-size: 13px;
}
.user-answer-body {
  word-break: break-word;
}
.user-answer-body :deep(.stem-img) {
  display: block;
  max-width: 100%;
  margin: 10px 0;
  border-radius: 8px;
  border: 1px solid #e0e8e3;
}

.self-check-answer {
  margin-top: 12px;
  padding: 12px 14px;
  border-radius: 10px;
  background: rgba(255, 255, 255, .8);
  color: #35483f;
  font-size: 14px;
  line-height: 1.7;
  word-break: break-word;
}
.self-check-answer :deep(.stem-img) {
  display: block;
  max-width: 100%;
  margin: 10px 0;
  border-radius: 8px;
  border: 1px solid #e0e8e3;
}

/* AI 解析 */
.ai-explain-section {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid rgba(0, 0, 0, .05);
}
.ai-explain-btn {
  width: 100%;
  height: 40px;
  border: 1px solid #28735f;
  border-radius: 8px;
  background: #fff;
  color: #28735f;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: background .18s;
}
.ai-explain-btn:hover:not(:disabled) {
  background: #eaf6f0;
}
.ai-explain-btn:disabled {
  opacity: .6;
  cursor: not-allowed;
}
.ai-explain-content {
  margin-top: 12px;
  padding: 14px 16px;
  border-radius: 10px;
  background: rgba(255, 255, 255, .85);
  color: #2d4238;
  font-size: 14px;
  line-height: 1.75;
  word-break: break-word;
}

.practice-footer {
  position: fixed;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 4;
  display: flex;
  align-items: center;
  height: 66px;
  padding: 0 clamp(20px, 6vw, 86px);
  border-top: 1px solid #e0e8e3;
  background: rgba(255, 255, 255, .96);
  backdrop-filter: blur(10px);
}
.practice-footer > button {
  display: grid;
  justify-items: center;
  gap: 2px;
  min-width: 54px;
  border: 0;
  padding: 6px 8px;
  color: #718078;
  background: transparent;
  cursor: pointer;
  border-radius: 8px;
  transition: background .18s, color .18s;
}
.practice-footer > button:hover {
  background: #f1f8f5;
  color: #28735f;
}
.practice-footer > button > span {
  height: 24px;
  color: #60766c;
  font-size: 20px;
  line-height: 22px;
}
.practice-footer > button small,
.metric span {
  font-size: 11px;
}
.practice-footer .favored {
  color: #c7823d;
}
.practice-footer .cut-icon {
  color: #5c7cd1;
}
.footer-divider {
  width: 1px;
  height: 28px;
  margin: 0 12px;
  background: #e4eae6;
}
.metric {
  display: grid;
  justify-items: center;
  min-width: 50px;
  margin-left: auto;
}
.metric + .metric {
  margin-left: 8px;
}
.metric strong {
  color: #43564d;
  font-size: 15px;
}
.metric span {
  margin-top: 2px;
  color: #8b9690;
}
.correct-metric strong {
  color: #28735f;
}
.wrong-metric strong {
  color: #bf4b3f;
}

.modal-backdrop {
  position: fixed;
  z-index: 20;
  inset: 0;
  display: grid;
  place-items: center;
  padding: 20px;
  background: rgba(20, 45, 35, .35);
}
.modal {
  width: min(100%, 480px);
  max-height: 82vh;
  overflow: auto;
  border-radius: 14px;
  padding: 24px;
  background: #fff;
  box-shadow: 0 18px 48px rgba(19, 49, 37, .18);
}
.modal-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 16px;
}
.modal-head h2 {
  margin: 0;
  font-size: 20px;
  color: #1f2d3d;
}
.modal-head button {
  border: 0;
  padding: 4px 8px;
  color: #7e8c85;
  background: transparent;
  font-size: 13px;
  cursor: pointer;
  border-radius: 6px;
}
.modal-head button:hover {
  background: #f3f7f5;
}
.eyebrow {
  margin: 0 0 6px;
  color: #6f9083;
  font-size: 11px;
  letter-spacing: 1.3px;
  font-weight: 700;
}
.legend {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  margin-bottom: 14px;
  padding-bottom: 12px;
  border-bottom: 1px solid #eef2f0;
  color: #7f8f88;
  font-size: 12px;
}
.legend span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.legend .dot {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 3px;
}
.dot-correct { background: #28735f; }
.dot-wrong { background: #bf4b3f; }
.dot-pending { background: #d5dfd9; }
.dot-current { background: #fff; border: 2px solid #28735f; }
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(42px, 1fr));
  gap: 8px;
  padding: 4px 0 8px;
}
.grid-btn {
  aspect-ratio: 1;
  border: 1px solid #dde7e1;
  border-radius: 8px;
  background: #f7faf8;
  color: #66766e;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: transform .12s, border-color .18s, background .18s;
}
.grid-btn:hover {
  transform: scale(1.05);
}
.grid-btn.correct {
  border-color: #28735f;
  background: #eaf6f0;
  color: #17644f;
}
.grid-btn.wrong {
  border-color: #bf4b3f;
  background: #fff4f2;
  color: #a13c31;
}
.grid-btn.pending {
  border-color: #dde7e1;
  background: #fbfcfb;
  color: #8d9a94;
}
.grid-btn.current {
  outline: 2px solid #28735f;
  outline-offset: 1px;
}
.grid-actions {
  margin-top: 16px;
}
.grid-actions .primary-button {
  margin-top: 0;
}
.grid-actions .ghost-button {
  margin-top: 8px;
}

/* 斩题面板 */
.cut-panel {
  width: min(100%, 620px);
  max-width: 620px;
  max-height: 84vh;
  padding: 24px 0 0;
  display: flex;
  flex-direction: column;
}
.cut-panel .modal-head {
  padding: 0 24px;
  margin-bottom: 16px;
}
.cut-panel-hint {
  margin: 6px 0 0;
  color: #85928b;
  font-size: 12px;
}
.cut-panel-grid {
  flex: 1;
  overflow-y: auto;
  padding: 0 24px 24px;
  display: grid;
  gap: 12px;
}
.cut-panel-card {
  border: 1px solid #e0e8e3;
  border-radius: 12px;
  padding: 16px 18px;
  background: #fff;
}
.cut-panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.cut-panel-index {
  color: #7a8b9b;
  font-size: 12px;
  font-weight: 600;
}
.cut-panel-tag {
  padding: 4px 8px;
  border-radius: 6px;
  color: #28775f;
  background: #e7f5ee;
  font-size: 12px;
  font-weight: 600;
}
.cut-panel-stem {
  margin: 0 0 12px;
  color: #2d4238;
  font-size: 14px;
  font-weight: 600;
  line-height: 1.6;
}
.cut-panel-stem :deep(.stem-img) {
  display: block;
  max-width: 100%;
  margin: 10px 0;
  border-radius: 8px;
}
.cut-panel-options {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 6px;
}
.cut-panel-options li {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 8px 11px;
  border: 1px solid #eef2f0;
  border-radius: 8px;
  color: #4d665b;
  background: #fafcfb;
  font-size: 13px;
}
.cut-panel-options li.correct {
  border-color: #28735f;
  color: #17644f;
  background: #eaf6f0;
  font-weight: 600;
}
.cut-panel-options .opt-key {
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
.cut-panel-options li.correct .opt-key {
  border-color: #28735f;
  color: #fff;
  background: #28735f;
}
.cut-panel-answer {
  margin: 0;
  padding: 10px 12px;
  border-radius: 8px;
  background: #eaf6f0;
  color: #17644f;
  font-size: 13px;
  line-height: 1.6;
}
.cut-panel-answer b {
  margin-right: 6px;
  color: #1f6956;
}
.cut-panel-explanation {
  margin: 12px 0 0;
  padding: 9px 12px;
  border-left: 3px solid #28735f;
  border-radius: 4px;
  background: #f1f9f5;
  color: #4d665b;
  font-size: 12.5px;
  line-height: 1.7;
}
.cut-panel-explanation b {
  margin-right: 6px;
  color: #1f6956;
}
.cut-panel-actions {
  margin-top: 12px;
}
.cut-panel-actions .row-btn {
  width: 100%;
  height: 36px;
  border: 1px solid #8b9ee0;
  border-radius: 8px;
  color: #455993;
  background: #f4f6ff;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background .18s;
}
.cut-panel-actions .row-btn:hover:not(:disabled) {
  background: #e0e7ff;
}
.cut-panel-actions .row-btn:disabled {
  opacity: .6;
  cursor: not-allowed;
}
.empty-cut {
  padding: 60px 24px;
  text-align: center;
  color: #9aa59f;
  font-size: 13px;
}

/* 笔记弹窗 */
.note-editor-modal {
  width: min(100%, 560px);
  max-width: 560px;
}
.note-stem {
  margin: 0 0 14px;
  padding: 10px 12px;
  border-left: 3px solid #28735f;
  border-radius: 4px;
  background: #f1f9f5;
  color: #35483f;
  font-size: 13px;
  line-height: 1.6;
  word-break: break-word;
}
.note-textarea {
  width: 100%;
  border: 1px solid #d8e4de;
  border-radius: 10px;
  padding: 12px 14px;
  font-family: inherit;
  font-size: 14px;
  line-height: 1.7;
  color: #2d4238;
  background: #fff;
  outline: none;
  resize: vertical;
  box-sizing: border-box;
  transition: border-color .18s, box-shadow .18s;
}
.note-textarea:focus {
  border-color: #28735f;
  box-shadow: 0 0 0 3px rgba(40, 115, 95, .12);
}
.note-textarea:disabled {
  background: #f7faf8;
  cursor: not-allowed;
}
.note-actions {
  display: flex;
  gap: 10px;
  margin-top: 14px;
}
.note-actions .ghost-button,
.note-actions .primary-button {
  flex: 1;
  margin-top: 0;
}

/* 恢复进度弹窗 */
.resume-modal {
  max-width: 420px;
}
.resume-text {
  margin: 4px 0 20px;
  color: #4a675a;
  font-size: 14px;
  line-height: 1.7;
}
.resume-text b {
  color: #1f6956;
  font-size: 16px;
}
.resume-actions {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.resume-actions .primary-button,
.resume-actions .ghost-button {
  margin-top: 0;
}

@media (max-width: 760px) {
  .practice-header {
    padding: 0 16px;
    gap: 12px;
  }
  .back-button span {
    display: none;
  }
  .header-action {
    padding: 6px 10px;
    font-size: 12px;
  }
  .practice-body {
    padding: 20px 16px 40px;
  }
  .question-card {
    padding: 20px 18px;
  }
  .practice-footer {
    padding: 0 14px;
  }
  .metric {
    min-width: 44px;
  }
  .footer-divider {
    margin: 0 6px;
  }
  .practice-footer > button {
    min-width: 48px;
  }
  .nav-btn {
    min-width: 88px;
    font-size: 13px;
  }
}
</style>