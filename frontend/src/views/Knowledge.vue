<template>
  <main class="knowledge-page">
    <header class="knowledge-header">
      <button class="back-button" type="button" @click="router.push('/home')">
        ← <span>返回首页</span>
      </button>
      <h1>讲义知识库</h1>
      <div class="header-actions">
        <button class="ghost-button" type="button" :disabled="loading" @click="loadAll">
          {{ loading ? '刷新中…' : '刷新' }}
        </button>
      </div>
    </header>

    <section class="knowledge-body">
      <p class="intro">
        上传讲义后会自动解析、切分、向量化入库；刷题时的 AI 讲解会引用这里的原文，
        并标出「来自哪本讲义第几页」。扫描版 PDF 解析出来是乱码或空白，入库会直接失败并给出原因。
      </p>

      <!-- ============ 概览 ============ -->
      <div class="stat-strip">
        <div class="stat-card">
          <strong>{{ stats.documents }}</strong>
          <small>文档</small>
        </div>
        <div class="stat-card">
          <strong>{{ stats.documents_ready }}</strong>
          <small>可检索</small>
        </div>
        <div class="stat-card">
          <strong>{{ stats.chunks }}</strong>
          <small>片段</small>
        </div>
        <div class="stat-card">
          <strong>{{ percent(stats.embedding_coverage) }}</strong>
          <small>向量覆盖</small>
        </div>
        <div class="stat-card" :class="{ warn: stats.documents_failed > 0 }">
          <strong>{{ stats.documents_failed }}</strong>
          <small>入库失败</small>
        </div>
      </div>

      <p class="model-line">
        当前模型服务：<b>{{ aiInfo.provider || '未知' }}</b>
        · 对话 <b>{{ aiInfo.chat_model || '-' }}</b>
        · 向量 <b>{{ aiInfo.embed_model || '-' }}</b>
        <span v-if="aiInfo.client_ready === false" class="model-error">
          （不可用：{{ aiInfo.error }}）
        </span>
      </p>

      <!-- ============ 上传 ============ -->
      <section class="panel">
        <div class="panel-head">
          <div>
            <p class="eyebrow">UPLOAD</p>
            <h2>上传讲义</h2>
          </div>
          <small class="panel-hint">支持 PDF / DOCX / Markdown / TXT，单个不超过 30MB</small>
        </div>

        <form class="upload-form" @submit.prevent="submitUpload">
          <label class="file-picker">
            <input
              type="file"
              accept=".pdf,.docx,.md,.markdown,.txt"
              :disabled="uploading"
              @change="onFileChange"
            />
            <span class="file-picker-icon">＋</span>
            <span class="file-picker-text">
              {{ file ? file.name : '选择要上传的讲义文件' }}
            </span>
          </label>

          <div class="upload-fields">
            <input v-model.trim="uploadTitle" placeholder="标题（留空则用文件名）" :disabled="uploading" />
            <input
              v-model.trim="uploadSubject"
              list="kb-subjects"
              placeholder="学科，例如：判断推理"
              :disabled="uploading"
            />
            <datalist id="kb-subjects">
              <option v-for="s in subjectOptions" :key="s" :value="s" />
            </datalist>
          </div>

          <button class="primary-button" type="submit" :disabled="uploading || !file">
            {{ uploading ? '解析入库中…' : '上传并入库' }}
          </button>
        </form>

        <p v-if="uploading" class="upload-progress">
          正在解析并按段落切分，同时调用向量模型逐批生成向量。
          几十页的讲义通常需要几十秒，请不要关闭或刷新页面。
        </p>

        <p v-if="uploadMessage" class="upload-result" :class="uploadOk ? 'ok' : 'bad'">
          {{ uploadMessage }}
        </p>
      </section>

      <!-- ============ 文档列表 ============ -->
      <section class="panel">
        <div class="panel-head">
          <div>
            <p class="eyebrow">DOCUMENTS</p>
            <h2>已入库文档</h2>
          </div>
          <small class="panel-hint">共 {{ docs.length }} 份</small>
        </div>

        <p v-if="!docs.length" class="empty-tip">
          知识库还是空的。上传一份讲义后，检索和 AI 讲解就能引用原文了。
        </p>

        <div v-else class="doc-list">
          <div v-for="doc in docs" :key="doc.id" class="doc-row">
            <div class="doc-main">
              <div class="doc-title-line">
                <strong>{{ doc.title }}</strong>
                <span class="subject-tag">{{ doc.subject }}</span>
                <span class="status-tag" :class="doc.status">{{ statusLabel(doc) }}</span>
              </div>
              <p class="doc-meta">
                {{ doc.file_type || '未知格式' }}
                · {{ doc.char_count }} 字
                · {{ doc.chunk_count }} 个片段
                · {{ doc.embed_model ? `已建向量（${doc.embed_model}）` : '仅 BM25 索引' }}
                · {{ shortDate(doc.created_at) }}
              </p>
              <p v-if="doc.status === 'failed'" class="doc-error">
                失败于「{{ stageLabel(doc.failed_stage) }}」：{{ doc.error }}
              </p>
            </div>
            <div class="doc-actions">
              <button
                class="ghost-button"
                type="button"
                :disabled="doc.chunk_count === 0"
                @click="openChunks(doc)"
              >查看片段</button>
              <button
                class="ghost-button danger"
                type="button"
                :disabled="deletingId === doc.id"
                @click="removeDoc(doc)"
              >{{ deletingId === doc.id ? '删除中…' : '删除' }}</button>
            </div>
          </div>
        </div>
      </section>

      <!-- ============ 检索测试 ============ -->
      <section class="panel">
        <div class="panel-head">
          <div>
            <p class="eyebrow">RETRIEVAL DEBUG</p>
            <h2>检索测试</h2>
          </div>
          <small class="panel-hint">看给定问题能召回哪些片段、分数怎么来的</small>
        </div>

        <form class="search-form" @submit.prevent="runSearch">
          <input
            v-model.trim="search.query"
            placeholder="输入一个问题，例如：图形推理中对称轴的方向怎么判断"
            :disabled="searching"
          />
          <button class="primary-button" type="submit" :disabled="searching || !search.query">
            {{ searching ? '检索中…' : '检索' }}
          </button>
        </form>

        <div class="search-options">
          <label>
            <span>召回条数 {{ search.top_k }}</span>
            <input v-model.number="search.top_k" type="range" min="1" max="20" step="1" />
          </label>
          <label>
            <span>向量权重 α = {{ search.alpha.toFixed(1) }}</span>
            <input v-model.number="search.alpha" type="range" min="0" max="1" step="0.1" />
          </label>
          <label>
            <span>词命中率下限 {{ search.min_coverage.toFixed(1) }}</span>
            <input v-model.number="search.min_coverage" type="range" min="0" max="1" step="0.1" />
          </label>
          <label>
            <span>学科过滤</span>
            <input v-model.trim="search.subject" list="kb-subjects" placeholder="不限" />
          </label>
        </div>

        <p class="alpha-tip">{{ alphaExplain }}</p>

        <p v-if="searchMessage" class="empty-tip">{{ searchMessage }}</p>

        <div v-if="searchResult" class="hit-list">
          <div class="hit-summary">
            检索模式 <b>{{ modeLabel(searchResult.mode) }}</b>
            · 候选片段 {{ searchResult.candidates }} 个
            · 命中 {{ searchResult.hits.length }} 条
          </div>
          <div v-for="hit in searchResult.hits" :key="hit.chunk_id" class="hit-row">
            <div class="hit-head">
              <span class="hit-source">
                {{ hit.title || '未命名文档' }}
                <template v-if="hit.chapter"> · {{ hit.chapter }}</template>
                <template v-if="hit.page"> · 第 {{ hit.page }} 页</template>
              </span>
              <span class="hit-score">综合 {{ hit.score.toFixed(4) }}</span>
            </div>
            <div class="score-bars">
              <div class="score-bar">
                <small>BM25</small>
                <i :style="{ width: barWidth(hit.bm25_score) }"></i>
                <em>{{ hit.bm25_score.toFixed(2) }}</em>
              </div>
              <div class="score-bar">
                <small>向量</small>
                <i class="vec" :style="{ width: `${Math.max(0, Math.min(1, hit.vector_score)) * 100}%` }"></i>
                <em>{{ hit.vector_score.toFixed(3) }}</em>
              </div>
              <div class="score-bar">
                <small>词命中</small>
                <i class="cov" :style="{ width: `${Math.max(0, Math.min(1, hit.coverage)) * 100}%` }"></i>
                <em>{{ hit.coverage.toFixed(3) }}</em>
              </div>
            </div>
            <p class="hit-text">{{ hit.text }}</p>
          </div>
        </div>
      </section>

      <!-- ============ 知识点 ============ -->
      <section class="panel">
        <div class="panel-head">
          <div>
            <p class="eyebrow">KNOWLEDGE POINTS</p>
            <h2>知识点与自动打标</h2>
          </div>
          <small class="panel-hint">共 {{ flatKps.length }} 个知识点</small>
        </div>

        <div class="kp-toolbar">
          <select v-model.number="tagBankId">
            <option :value="0">选择题库…</option>
            <option v-for="b in banks" :key="b.id" :value="b.id">
              {{ b.name }}（{{ b.question_count }} 题）
            </option>
          </select>
          <label class="inline-field">
            <span>本次处理</span>
            <input v-model.number="tagLimit" type="number" min="1" max="500" />
          </label>
          <button class="ghost-button" type="button" :disabled="!tagBankId || tagging" @click="loadCoverage">
            查看覆盖率
          </button>
          <button class="ghost-button" type="button" :disabled="!tagBankId || tagging" @click="previewTag">
            预览提示词
          </button>
          <button class="primary-button" type="button" :disabled="!tagBankId || tagging" @click="runTag">
            {{ tagging ? '标注中…' : '开始打标' }}
          </button>
        </div>

        <div v-if="coverage" class="coverage-box">
          <div class="coverage-bar">
            <i :style="{ width: percent(coverage.coverage) }"></i>
          </div>
          <p>
            已标注 <b>{{ coverage.questions_tagged }}</b> / {{ coverage.questions_total }} 道
            （{{ percent(coverage.coverage) }}），
            还有 <b>{{ coverage.questions_untagged }}</b> 道没有知识点，
            覆盖 {{ coverage.knowledge_points_used }} 个知识点。
          </p>
        </div>

        <p v-if="tagMessage" class="tag-message">{{ tagMessage }}</p>
        <pre v-if="tagPreview" class="tag-preview">{{ tagPreview }}</pre>

        <p v-if="!flatKps.length" class="empty-tip">
          还没有知识点。上面的「开始打标」会让大模型读题目并归纳出知识点。
        </p>

        <div v-else class="kp-list">
          <div
            v-for="kp in flatKps"
            :key="kp.id"
            class="kp-row"
            :style="{ paddingLeft: `${12 + kp.depth * 20}px` }"
          >
            <span class="kp-dot"></span>
            <strong>{{ kp.name }}</strong>
            <span class="subject-tag">{{ kp.subject }}</span>
            <small v-if="kp.description">{{ kp.description }}</small>
          </div>
        </div>
      </section>
    </section>

    <!-- ============ 片段弹窗 ============ -->
    <div v-if="chunkDialog" class="modal-backdrop" @click.self="chunkDialog = false">
      <section class="modal">
        <div class="modal-head">
          <div>
            <p class="eyebrow">CHUNKS</p>
            <h2>{{ chunkDoc?.title }} · 切分结果</h2>
          </div>
          <button type="button" @click="chunkDialog = false">关闭</button>
        </div>

        <div class="chunk-toolbar">
          <span>共 {{ chunkDoc?.chunk_count }} 个片段</span>
          <label class="inline-field">
            <span>显示前</span>
            <select v-model.number="chunkLimit" @change="reloadChunks">
              <option :value="5">5</option>
              <option :value="10">10</option>
              <option :value="20">20</option>
              <option :value="50">50</option>
            </select>
          </label>
        </div>

        <p v-if="chunksLoading" class="empty-tip">加载中…</p>

        <div v-else class="chunk-list">
          <div v-for="c in chunks" :key="c.index" class="chunk-row">
            <div class="chunk-head">
              <span>#{{ c.index }}</span>
              <span v-if="c.chapter">{{ c.chapter }}</span>
              <span v-if="c.page">第 {{ c.page }} 页</span>
              <span>{{ c.char_count }} 字</span>
              <span class="status-tag" :class="c.has_embedding ? 'ready' : 'pending'">
                {{ c.has_embedding ? '有向量' : '无向量' }}
              </span>
            </div>
            <pre class="chunk-text">{{ c.text }}</pre>
          </div>
        </div>
      </section>
    </div>
  </main>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import request from '@/api/request'
import { toast } from '@/composables/useToast'

type Doc = {
  id: number
  title: string
  subject: string
  filename: string
  file_type: string
  char_count: number
  chunk_count: number
  status: string
  failed_stage: string
  error: string
  embed_model: string
  created_at: string
}

// 上传接口比列表接口多回一句人话（成功切了多少片段 / 失败在哪一步）
type UploadResult = Doc & { message?: string }

type Chunk = {
  index: number
  chapter: string
  page: number | null
  char_count: number
  has_embedding: boolean
  text: string
}

type Hit = {
  chunk_id: number
  doc_id: number
  title: string
  text: string
  chapter: string
  page: number | null
  subject: string
  score: number
  bm25_score: number
  vector_score: number
  coverage: number
}

type SearchResult = {
  query: string
  mode: string
  candidates: number
  hits: Hit[]
  message?: string
}

type KpNode = {
  id: number
  name: string
  subject: string
  parent_id: number | null
  description: string
  children: KpNode[]
}

type BankLite = { id: number; name: string; subject: string; question_count: number }

type Coverage = {
  bank_id: number
  subject: string
  questions_total: number
  questions_tagged: number
  questions_untagged: number
  coverage: number
  knowledge_points_used: number
}

const router = useRouter()

const DEFAULT_SUBJECTS = ['数学', '英语', '物理', '化学', '综合']

const loading = ref(false)
const docs = ref<Doc[]>([])
const banks = ref<BankLite[]>([])
const kpTree = ref<KpNode[]>([])
const deletingId = ref<number | null>(null)

const stats = reactive({
  documents: 0,
  documents_ready: 0,
  documents_failed: 0,
  chunks: 0,
  chunks_with_embedding: 0,
  embedding_coverage: 0,
  kp_coverage: 0,
  subjects: [] as string[],
})

const aiInfo = reactive({
  provider: '',
  chat_model: '',
  embed_model: '',
  client_ready: true as boolean | undefined,
  error: '',
})

// ==================== 上传 ====================

const file = ref<File | null>(null)
const uploadTitle = ref('')
const uploadSubject = ref('综合')
const uploading = ref(false)
const uploadMessage = ref('')
const uploadOk = ref(false)

function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement
  const picked = input.files?.[0] || null
  file.value = picked
  uploadMessage.value = ''
  // 标题不做预填：留空时后端直接用文件名，用户手填反而容易和文件名对不上
}

async function submitUpload() {
  if (!file.value) {
    toast.warning('请先选择文件')
    return
  }

  const fd = new FormData()
  fd.append('file', file.value)
  fd.append('title', uploadTitle.value)
  fd.append('subject', uploadSubject.value || '综合')

  uploading.value = true
  uploadMessage.value = ''
  try {
    // 入库要解析全文并逐批跑向量模型，几十页讲义远超默认 10 秒，这里单独放宽
    const res = (await request.post('/knowledge-docs', fd, {
      timeout: 10 * 60 * 1000,
    })) as unknown as UploadResult

    uploadOk.value = res.status !== 'failed'
    uploadMessage.value = res.message || (uploadOk.value ? '入库成功' : '入库失败')
    if (uploadOk.value) {
      file.value = null
      uploadTitle.value = ''
      toast.success(uploadMessage.value)
      await loadAll()
    } else {
      toast.error(uploadMessage.value)
    }
  } catch (e: any) {
    uploadOk.value = false
    uploadMessage.value = e.message || '上传失败'
    toast.error(uploadMessage.value)
  } finally {
    uploading.value = false
  }
}

// ==================== 文档 ====================

async function loadDocs() {
  try {
    docs.value = (await request.get('/knowledge-docs')) as unknown as Doc[]
  } catch (e: any) {
    toast.error(e.message || '文档列表加载失败')
  }
}

async function loadStats() {
  try {
    const data = (await request.get('/rag/stats')) as unknown as typeof stats
    Object.assign(stats, data)
  } catch (e: any) {
    toast.error(e.message || '统计加载失败')
  }
}

async function loadAiInfo() {
  try {
    const data = (await request.get('/ai/info')) as unknown as typeof aiInfo
    Object.assign(aiInfo, data)
  } catch {
    // 模型信息只是辅助展示，失败不打扰用户
  }
}

async function loadBanks() {
  try {
    banks.value = (await request.get('/banks')) as unknown as BankLite[]
  } catch {
    /* 打标面板才需要题库，失败静默 */
  }
}

async function loadKps() {
  try {
    kpTree.value = (await request.get('/knowledge-points?tree=true')) as unknown as KpNode[]
  } catch {
    /* 同上 */
  }
}

async function loadAll() {
  loading.value = true
  await Promise.all([loadDocs(), loadStats(), loadAiInfo(), loadBanks(), loadKps()])
  loading.value = false
}

onMounted(loadAll)

async function removeDoc(doc: Doc) {
  const ok = window.confirm(
    `确定删除「${doc.title}」吗？\n\n它切出的 ${doc.chunk_count} 个片段会一起删除，AI 讲解也不再引用这份讲义。`
  )
  if (!ok) return

  deletingId.value = doc.id
  try {
    await request.delete(`/knowledge-docs/${doc.id}`)
    docs.value = docs.value.filter(d => d.id !== doc.id)
    toast.success('已删除')
    await loadStats()
  } catch (e: any) {
    toast.error(e.message || '删除失败')
  } finally {
    deletingId.value = null
  }
}

// ==================== 片段 ====================

const chunkDialog = ref(false)
const chunkDoc = ref<Doc | null>(null)
const chunks = ref<Chunk[]>([])
const chunkLimit = ref(10)
const chunksLoading = ref(false)

async function openChunks(doc: Doc) {
  chunkDoc.value = doc
  chunkDialog.value = true
  await reloadChunks()
}

async function reloadChunks() {
  if (!chunkDoc.value) return
  chunksLoading.value = true
  try {
    const res = (await request.get(
      `/knowledge-docs/${chunkDoc.value.id}/chunks?limit=${chunkLimit.value}`
    )) as unknown as { chunks: Chunk[] }
    chunks.value = res.chunks || []
  } catch (e: any) {
    toast.error(e.message || '片段加载失败')
    chunks.value = []
  } finally {
    chunksLoading.value = false
  }
}

// ==================== 检索 ====================

const search = reactive({
  query: '',
  top_k: 5,
  alpha: 0.5,
  min_coverage: 0.2,
  subject: '',
})

const searching = ref(false)
const searchResult = ref<SearchResult | null>(null)
const searchMessage = ref('')

const alphaExplain = computed(() => {
  if (!searchResult.value) {
    return 'α = 0 只用 BM25 关键词打分，α = 1 只用向量语义打分，中间是两者加权混合。'
  }
  const mode = searchResult.value.mode
  if (mode === 'bm25') return '本次只用 BM25 打分（向量模型不可用，或 α = 0）。'
  if (mode === 'vector') return '本次只用向量语义打分（α = 1）。'
  return `本次是混合检索：向量权重 α = ${search.alpha.toFixed(1)}，BM25 权重 ${(1 - search.alpha).toFixed(1)}。`
})

async function runSearch() {
  if (!search.query) return
  searching.value = true
  searchMessage.value = ''
  try {
    const body: Record<string, unknown> = {
      query: search.query,
      top_k: search.top_k,
      alpha: search.alpha,
      min_coverage: search.min_coverage,
    }
    if (search.subject) body.subject = search.subject

    const res = (await request.post('/rag/search', body)) as unknown as SearchResult
    searchResult.value = res
    if (res.message) searchMessage.value = res.message
    else if (!res.hits.length) {
      searchMessage.value = '这一批候选里没有片段满足分数与命中率要求，可以调低「词命中率下限」再试。'
    }
  } catch (e: any) {
    toast.error(e.message || '检索失败')
    searchResult.value = null
  } finally {
    searching.value = false
  }
}

function modeLabel(mode: string) {
  const map: Record<string, string> = { bm25: 'BM25 关键词', vector: '向量语义', hybrid: '混合', none: '未执行' }
  return map[mode] || mode
}

function barWidth(bm25: number) {
  // BM25 原始分没有上界，用平方根压缩一下，否则长文档会把短文档压成一条线
  return `${Math.min(100, Math.sqrt(Math.max(0, bm25)) * 12)}%`
}

// ==================== 知识点打标 ====================

const tagBankId = ref(0)
const tagLimit = ref(20)
const tagging = ref(false)
const tagMessage = ref('')
const tagPreview = ref('')
const coverage = ref<Coverage | null>(null)

async function loadCoverage() {
  if (!tagBankId.value) return
  try {
    coverage.value = (await request.get(
      `/banks/${tagBankId.value}/knowledge-coverage`
    )) as unknown as Coverage
  } catch (e: any) {
    toast.error(e.message || '覆盖率加载失败')
  }
}

async function previewTag() {
  if (!tagBankId.value) return
  tagging.value = true
  tagMessage.value = ''
  tagPreview.value = ''
  try {
    const res = (await request.post(
      `/banks/${tagBankId.value}/questions/auto-tag?limit=${tagLimit.value}&dry_run=true`
    )) as unknown as { message: string; prompt_preview: string }
    tagMessage.value = res.message
    tagPreview.value = res.prompt_preview || ''
  } catch (e: any) {
    toast.error(e.message || '预览失败')
  } finally {
    tagging.value = false
  }
}

async function runTag() {
  if (!tagBankId.value) return
  const ok = window.confirm(
    `将对题库中最多 ${tagLimit.value} 道还没有知识点的题目调用大模型标注。\n\n` +
      '每道题都要跑一次推理，本地模型会比较慢，请耐心等待。是否继续？'
  )
  if (!ok) return

  tagging.value = true
  tagMessage.value = ''
  tagPreview.value = ''
  try {
    const res = (await request.post(
      `/banks/${tagBankId.value}/questions/auto-tag?limit=${tagLimit.value}`,
      null,
      { timeout: 30 * 60 * 1000 }
    )) as unknown as {
      message: string
      tagged: number
      links: number
      failed_batches: number
      errors: string[]
    }
    tagMessage.value = res.message
    if (res.errors && res.errors.length) {
      tagPreview.value = res.errors.join('\n')
    }
    toast.success(res.message)
    await Promise.all([loadCoverage(), loadKps()])
  } catch (e: any) {
    toast.error(e.message || '打标失败')
  } finally {
    tagging.value = false
  }
}

// ==================== 展示辅助 ====================

const flatKps = computed(() => {
  const out: Array<KpNode & { depth: number }> = []
  const walk = (nodes: KpNode[], depth: number) => {
    for (const node of nodes) {
      out.push({ ...node, depth })
      if (node.children && node.children.length) walk(node.children, depth + 1)
    }
  }
  walk(kpTree.value, 0)
  return out
})

const subjectOptions = computed(() => {
  const set = new Set<string>([...DEFAULT_SUBJECTS, ...(stats.subjects || [])])
  for (const b of banks.value) if (b.subject) set.add(b.subject)
  return [...set].filter(Boolean)
})

function percent(v: number) {
  return `${Math.round((v || 0) * 100)}%`
}

function shortDate(s: string) {
  return s ? s.slice(0, 10) : '—'
}

function statusLabel(doc: Doc) {
  if (doc.status === 'ready') return '已入库'
  if (doc.status === 'failed') return '入库失败'
  if (doc.status === 'pending') return '处理中'
  return doc.status
}

function stageLabel(stage: string) {
  const map: Record<string, string> = {
    load: '解析原文',
    chunk: '切分片段',
    embed: '生成向量',
  }
  return map[stage] || stage || '未知步骤'
}
</script>

<style scoped>
.knowledge-page {
  min-height: 100vh;
  color: #20332b;
  background: #f5f8f6;
}

.knowledge-header {
  height: 66px;
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 0 clamp(20px, 6vw, 86px);
  border-bottom: 1px solid #e0e8e3;
  background: rgba(255, 255, 255, .94);
  backdrop-filter: blur(8px);
  position: sticky;
  top: 0;
  z-index: 5;
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
  padding: 0;
}
.back-button:hover span {
  text-decoration: underline;
}
.knowledge-header h1 {
  margin: 0;
  font-size: 18px;
  font-weight: 650;
}
.header-actions {
  margin-left: auto;
}

.knowledge-body {
  max-width: 1040px;
  margin: 0 auto;
  padding: 34px 28px 80px;
}

.intro {
  margin: 0 0 24px;
  color: #6f7f77;
  font-size: 14px;
  line-height: 1.75;
}

/* ============ 概览 ============ */
.stat-strip {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 12px;
  margin-bottom: 14px;
}
.stat-card {
  border: 1px solid #e2ebe5;
  border-radius: 12px;
  padding: 16px 14px;
  background: #fff;
}
.stat-card strong {
  display: block;
  color: #1f4c3e;
  font-size: 24px;
  font-weight: 680;
  line-height: 1.2;
}
.stat-card small {
  color: #8b988f;
  font-size: 12px;
}
.stat-card.warn strong {
  color: #bf4b3f;
}

.model-line {
  margin: 0 0 26px;
  color: #7c8a82;
  font-size: 13px;
}
.model-line b {
  color: #35604f;
  font-weight: 600;
}
.model-error {
  color: #bf4b3f;
}

/* ============ 面板 ============ */
.panel {
  border: 1px solid #e2ebe5;
  border-radius: 14px;
  padding: 24px;
  margin-bottom: 20px;
  background: #fff;
}
.panel-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}
.eyebrow {
  margin: 0 0 7px;
  color: #6e8f82;
  font-size: 11px;
  letter-spacing: 1.35px;
  font-weight: 700;
}
.panel-head h2 {
  margin: 0;
  font-size: 19px;
  font-weight: 650;
}
.panel-hint {
  color: #93a09a;
  font-size: 12px;
}

/* ============ 上传 ============ */
.upload-form {
  display: grid;
  grid-template-columns: 1fr 1fr auto;
  gap: 12px;
  align-items: stretch;
}
.file-picker {
  grid-column: 1 / -1;
  display: flex;
  align-items: center;
  gap: 12px;
  border: 1px dashed #cbdcd3;
  border-radius: 10px;
  padding: 16px;
  color: #5c6f66;
  background: #fafcfb;
  cursor: pointer;
  transition: border-color .18s, background .18s;
}
.file-picker:hover {
  border-color: #7fb7a2;
  background: #f4faf7;
}
.file-picker input {
  display: none;
}
.file-picker-icon {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: 50%;
  color: #2a8066;
  background: #e4f4ed;
  font-size: 17px;
}
.file-picker-text {
  font-size: 14px;
}
.upload-fields {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

input[type="text"],
input:not([type]),
.upload-fields input,
.search-form input,
.kp-toolbar input,
.kp-toolbar select,
.chunk-toolbar select,
.modal input {
  height: 42px;
  border: 1px solid #d7e2dc;
  border-radius: 8px;
  padding: 0 12px;
  color: #34473d;
  background: #fff;
  outline: none;
  box-sizing: border-box;
  font-size: 14px;
}
input:focus,
select:focus {
  border-color: #28735f;
  box-shadow: 0 0 0 3px rgba(40, 115, 95, .12);
}

.primary-button {
  border: 1px solid #1f795f;
  border-radius: 8px;
  padding: 0 20px;
  height: 42px;
  color: #fff;
  background: #1f795f;
  font-size: 14px;
  font-weight: 600;
  white-space: nowrap;
  cursor: pointer;
  transition: background .18s;
}
.primary-button:hover:not(:disabled) {
  background: #175746;
}
.primary-button:disabled,
.ghost-button:disabled {
  opacity: .5;
  cursor: not-allowed;
}
.ghost-button {
  border: 1px solid #d7e2dc;
  border-radius: 8px;
  padding: 0 14px;
  height: 36px;
  color: #35604f;
  background: #fff;
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
  cursor: pointer;
  transition: border-color .18s, background .18s, color .18s;
}
.ghost-button:hover:not(:disabled) {
  border-color: #7fb7a2;
  background: #f4faf7;
}
.ghost-button.danger {
  color: #bf4b3f;
  border-color: #f0d6d2;
}
.ghost-button.danger:hover:not(:disabled) {
  background: #fff4f2;
  border-color: #e0b3ac;
}

.upload-progress,
.upload-result {
  margin: 14px 0 0;
  font-size: 13px;
  line-height: 1.7;
}
.upload-progress {
  color: #8a6d3b;
}
.upload-result.ok {
  color: #2a7a5c;
}
.upload-result.bad {
  color: #bf4b3f;
}

/* ============ 文档列表 ============ */
.doc-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.doc-row {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  border: 1px solid #eaf1ec;
  border-radius: 10px;
  padding: 14px 16px;
  background: #fcfdfc;
}
.doc-main {
  flex: 1;
  min-width: 0;
}
.doc-title-line {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.doc-title-line strong {
  font-size: 15px;
  font-weight: 640;
}
.subject-tag {
  border-radius: 6px;
  padding: 3px 8px;
  color: #28755e;
  background: #e6f4ed;
  font-size: 12px;
}
.status-tag {
  border-radius: 6px;
  padding: 3px 8px;
  font-size: 12px;
  background: #eef2f0;
  color: #6d7b74;
}
.status-tag.ready {
  color: #28755e;
  background: #e6f4ed;
}
.status-tag.failed {
  color: #bf4b3f;
  background: #fdeeec;
}
.status-tag.pending {
  color: #8a6d3b;
  background: #fdf4e4;
}
.doc-meta {
  margin: 8px 0 0;
  color: #8b988f;
  font-size: 12px;
}
.doc-error {
  margin: 8px 0 0;
  color: #bf4b3f;
  font-size: 12px;
  line-height: 1.6;
}
.doc-actions {
  display: flex;
  gap: 8px;
  flex: 0 0 auto;
}
.empty-tip {
  margin: 0;
  color: #8b988f;
  font-size: 13px;
  line-height: 1.7;
}

/* ============ 检索 ============ */
.search-form {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 12px;
}
.search-options {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-top: 16px;
}
.search-options label {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.search-options span {
  color: #5d6f66;
  font-size: 12px;
  font-weight: 600;
}
input[type="range"] {
  width: 100%;
  accent-color: #28735f;
}
.alpha-tip {
  margin: 14px 0 0;
  color: #8b988f;
  font-size: 12px;
}
.hit-list {
  margin-top: 18px;
}
.hit-summary {
  margin-bottom: 12px;
  color: #5d6f66;
  font-size: 13px;
}
.hit-row {
  border: 1px solid #eaf1ec;
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 10px;
  background: #fcfdfc;
}
.hit-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.hit-source {
  color: #35604f;
  font-size: 13px;
  font-weight: 600;
}
.hit-score {
  color: #1f4c3e;
  font-size: 13px;
  font-weight: 650;
}
.score-bars {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
  margin: 12px 0;
}
.score-bar {
  display: grid;
  grid-template-columns: 46px 1fr 44px;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  color: #8b988f;
}
.score-bar i {
  display: block;
  height: 6px;
  border-radius: 3px;
  background: #4a9c7d;
}
.score-bar i.vec {
  background: #4a86c5;
}
.score-bar i.cov {
  background: #c7853d;
}
.score-bar em {
  font-style: normal;
  text-align: right;
  color: #6d7b74;
}
.hit-text {
  margin: 0;
  color: #4b5d54;
  font-size: 13px;
  line-height: 1.75;
  white-space: pre-wrap;
  word-break: break-word;
}

/* ============ 知识点 ============ */
.kp-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}
.kp-toolbar select {
  min-width: 200px;
}
.inline-field {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #5d6f66;
  font-size: 13px;
}
.inline-field input[type="number"] {
  width: 84px;
  height: 36px;
  border: 1px solid #d7e2dc;
  border-radius: 8px;
  padding: 0 10px;
  font-size: 13px;
  outline: none;
}
.coverage-box {
  margin-top: 16px;
}
.coverage-bar {
  height: 8px;
  border-radius: 4px;
  background: #eef2f0;
  overflow: hidden;
}
.coverage-bar i {
  display: block;
  height: 100%;
  border-radius: 4px;
  background: linear-gradient(90deg, #4a9c7d, #28735f);
  transition: width .25s;
}
.coverage-box p {
  margin: 10px 0 0;
  color: #6d7b74;
  font-size: 13px;
}
.tag-message {
  margin: 14px 0 0;
  color: #35604f;
  font-size: 13px;
}
.tag-preview {
  margin: 12px 0 0;
  max-height: 260px;
  overflow: auto;
  border: 1px solid #eaf1ec;
  border-radius: 10px;
  padding: 14px;
  color: #4b5d54;
  background: #fbfcfb;
  font-size: 12px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}
.kp-list {
  margin-top: 16px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.kp-row {
  display: flex;
  align-items: center;
  gap: 10px;
  border-radius: 8px;
  padding: 9px 12px;
  background: #fafcfb;
  font-size: 13px;
}
.kp-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #7fb7a2;
  flex: 0 0 auto;
}
.kp-row strong {
  font-weight: 600;
}
.kp-row small {
  color: #93a09a;
  font-size: 12px;
}

/* ============ 弹窗 ============ */
.modal-backdrop {
  position: fixed;
  z-index: 10;
  inset: 0;
  display: grid;
  place-items: center;
  padding: 24px;
  background: rgba(20, 45, 35, .35);
}
.modal {
  width: min(100%, 820px);
  max-height: 86vh;
  overflow: auto;
  border-radius: 15px;
  padding: 24px;
  background: #fff;
  box-shadow: 0 18px 48px rgba(19, 49, 37, .2);
}
.modal-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 18px;
}
.modal-head h2 {
  margin: 0;
  font-size: 18px;
  font-weight: 650;
}
.modal-head button {
  border: 0;
  color: #7b8982;
  background: transparent;
  font-size: 13px;
  cursor: pointer;
}
.chunk-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
  color: #6d7b74;
  font-size: 13px;
}
.chunk-toolbar select {
  height: 34px;
  border: 1px solid #d7e2dc;
  border-radius: 8px;
  padding: 0 8px;
  font-size: 13px;
}
.chunk-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.chunk-row {
  border: 1px solid #eaf1ec;
  border-radius: 10px;
  padding: 12px 14px;
  background: #fcfdfc;
}
.chunk-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
  color: #8b988f;
  font-size: 12px;
}
.chunk-text {
  margin: 0;
  max-height: 220px;
  overflow: auto;
  color: #4b5d54;
  font-size: 12.5px;
  line-height: 1.75;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

@media (max-width: 860px) {
  .stat-strip {
    grid-template-columns: repeat(2, 1fr);
  }
  .upload-form,
  .upload-fields,
  .search-form,
  .score-bars {
    grid-template-columns: 1fr;
  }
  .search-options {
    grid-template-columns: repeat(2, 1fr);
  }
  .doc-row {
    flex-direction: column;
  }
  .knowledge-body {
    padding: 24px 18px 60px;
  }
}
</style>