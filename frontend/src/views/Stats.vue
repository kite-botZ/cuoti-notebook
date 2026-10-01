<template>
  <main class="stats-page">
    <header class="stats-header">
      <button class="back-button" type="button" @click="router.push('/home')">
        ← <span>返回首页</span>
      </button>
      <h1>学习报告</h1>
      <div class="range-picker">
        <button
          v-for="opt in rangeOptions"
          :key="opt.value"
          type="button"
          :class="{ active: days === opt.value }"
          @click="changeDays(opt.value)"
        >{{ opt.label }}</button>
      </div>
    </header>

    <section v-if="loading" class="status-block">加载中…</section>

    <section v-else class="stats-body">
      <!-- ============ 概览卡片 ============ -->
      <div class="overview-grid">
        <div class="overview-card">
          <span class="overview-label">累计答题</span>
          <strong class="overview-value">{{ overview.total_attempts }}</strong>
          <small>道</small>
        </div>
        <div class="overview-card">
          <span class="overview-label">累计正确</span>
          <strong class="overview-value correct">{{ overview.correct_attempts }}</strong>
          <small>道</small>
        </div>
        <div class="overview-card">
          <span class="overview-label">正确率</span>
          <strong class="overview-value">{{ formatPercent(overview.accuracy) }}</strong>
        </div>
        <div class="overview-card">
          <span class="overview-label">学习天数</span>
          <strong class="overview-value">{{ overview.active_days }}</strong>
          <small>天</small>
        </div>
      </div>

      <!-- ============ 折线图：趋势 ============ -->
      <section class="chart-section">
        <div class="section-heading">
          <div>
            <p class="eyebrow">TREND</p>
            <h2>答题趋势（最近 {{ days }} 天）</h2>
          </div>
          <span>柱状：答题量 · 折线：正确率</span>
        </div>
        <div ref="trendChartRef" class="chart-box"></div>
      </section>

      <!-- ============ 柱状图：各题库对比 ============ -->
      <section class="chart-section">
        <div class="section-heading">
          <div>
            <p class="eyebrow">BY BANK</p>
            <h2>各题库正确率</h2>
          </div>
          <span>只有做过题的题库会显示</span>
        </div>
        <div v-if="bankStats.length" ref="bankChartRef" class="chart-box"></div>
        <p v-else class="empty-tip">还没有任何答题记录</p>
      </section>
    </section>
  </main>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import * as echarts from 'echarts'
import request from '@/api/request'
import { toast } from '@/composables/useToast'

type Overview = {
  total_attempts: number
  correct_attempts: number
  accuracy: number
  active_days: number
}

type TrendItem = {
  date: string
  total: number
  correct: number
  accuracy: number
}

type BankStat = {
  bank_id: number
  name: string
  subject: string
  total: number
  correct: number
  accuracy: number
}

const router = useRouter()

const loading = ref(true)
const days = ref(7)
const rangeOptions = [
  { label: '7 天', value: 7 },
  { label: '14 天', value: 14 },
  { label: '30 天', value: 30 },
]

const overview = ref<Overview>({
  total_attempts: 0,
  correct_attempts: 0,
  accuracy: 0,
  active_days: 0,
})

const trendData = ref<TrendItem[]>([])
const bankStats = ref<BankStat[]>([])

const trendChartRef = ref<HTMLDivElement | null>(null)
const bankChartRef = ref<HTMLDivElement | null>(null)

let trendChart: echarts.ECharts | null = null
let bankChart: echarts.ECharts | null = null

// ==================== 工具 ====================

function formatPercent(v: number) {
  return `${Math.round(v * 100)}%`
}

// 日期缩写：2026-09-19 → 09-19
function shortDate(d: string) {
  return d.slice(5)
}

// ==================== 数据加载 ====================

async function loadOverview() {
  overview.value = await request.get('/stats/overview') as unknown as Overview
}

async function loadTrend() {
  trendData.value = await request.get('/stats/trend', {
    params: { days: days.value },
  }) as unknown as TrendItem[]
}

async function loadBanks() {
  bankStats.value = await request.get('/stats/banks') as unknown as BankStat[]
}

async function loadAll() {
  loading.value = true
  try {
    await Promise.all([loadOverview(), loadTrend(), loadBanks()])
    // 数据加载完后，等 DOM 更新再画图
    setTimeout(() => {
      renderTrendChart()
      renderBankChart()
    }, 0)
  } catch (e: any) {
    toast.error(e.message || '加载失败')
  } finally {
    loading.value = false
  }
}

// ==================== 折线 + 柱状图 ====================

function renderTrendChart() {
  if (!trendChartRef.value) return

  if (!trendChart) {
    trendChart = echarts.init(trendChartRef.value)
  }

  const dates = trendData.value.map(t => shortDate(t.date))
  const totals = trendData.value.map(t => t.total)
  const accuracies = trendData.value.map(t => Math.round(t.accuracy * 100))

  trendChart.setOption({
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
    },
    legend: {
      data: ['答题量', '正确率'],
      left: 0,
      top: 0,
      itemWidth: 14,
      itemHeight: 10,
      textStyle: { color: '#718078', fontSize: 12 },
    },
    grid: { left: 52, right: 52, top: 56, bottom: 32 },
    xAxis: {
      type: 'category',
      data: dates,
      axisLine: { lineStyle: { color: '#dde7e1' } },
      axisLabel: { color: '#85928b', fontSize: 12 },
    },
    yAxis: [
      {
        type: 'value',
        name: '答题量',
        nameGap: 14,
        nameTextStyle: { color: '#85928b', fontSize: 11, align: 'right' },
        splitLine: { lineStyle: { color: '#f0f5f2' } },
        axisLabel: { color: '#85928b' },
      },
      {
        type: 'value',
        name: '正确率',
        nameGap: 14,
        nameTextStyle: { color: '#85928b', fontSize: 11, align: 'left' },
        min: 0,
        max: 100,
        splitLine: { show: false },
        axisLabel: { color: '#85928b', formatter: '{value}%' },
      },
    ],
    series: [
      {
        name: '答题量',
        type: 'bar',
        data: totals,
        barWidth: '40%',
        itemStyle: {
          color: '#28735f',
          borderRadius: [4, 4, 0, 0],
        },
      },
      {
        name: '正确率',
        type: 'line',
        yAxisIndex: 1,
        data: accuracies,
        smooth: true,
        symbolSize: 7,
        lineStyle: { color: '#c7823d', width: 2 },
        itemStyle: { color: '#c7823d' },
      },
    ],
  })
}

// ==================== 题库对比 ====================

function renderBankChart() {
  if (!bankChartRef.value) return
  if (!bankStats.value.length) return

  if (!bankChart) {
    bankChart = echarts.init(bankChartRef.value)
  }

  const names = bankStats.value.map(b => b.name)
  const totals = bankStats.value.map(b => b.total)
  const corrects = bankStats.value.map(b => b.correct)
  const accuracies = bankStats.value.map(b => Math.round(b.accuracy * 100))

  bankChart.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: {
      data: ['答题数', '正确数', '正确率'],
      left: 0,
      top: 0,
      itemWidth: 14,
      itemHeight: 10,
      textStyle: { color: '#718078', fontSize: 12 },
    },
    grid: { left: 52, right: 52, top: 56, bottom: 32 },
    xAxis: {
      type: 'category',
      data: names,
      axisLine: { lineStyle: { color: '#dde7e1' } },
      axisLabel: { color: '#85928b', fontSize: 12, interval: 0, rotate: 0 },
    },
    yAxis: [
      {
        type: 'value',
        name: '题数',
        nameGap: 14,
        nameTextStyle: { color: '#85928b', fontSize: 11, align: 'right' },
        splitLine: { lineStyle: { color: '#f0f5f2' } },
        axisLabel: { color: '#85928b' },
      },
      {
        type: 'value',
        name: '正确率',
        nameGap: 14,
        nameTextStyle: { color: '#85928b', fontSize: 11, align: 'left' },
        min: 0,
        max: 100,
        splitLine: { show: false },
        axisLabel: { color: '#85928b', formatter: '{value}%' },
      },
    ],
    series: [
      {
        name: '答题数',
        type: 'bar',
        data: totals,
        barWidth: '22%',
        itemStyle: { color: '#8ec5b0', borderRadius: [4, 4, 0, 0] },
      },
      {
        name: '正确数',
        type: 'bar',
        data: corrects,
        barWidth: '22%',
        itemStyle: { color: '#28735f', borderRadius: [4, 4, 0, 0] },
      },
      {
        name: '正确率',
        type: 'line',
        yAxisIndex: 1,
        data: accuracies,
        smooth: true,
        symbolSize: 7,
        lineStyle: { color: '#c7823d', width: 2 },
        itemStyle: { color: '#c7823d' },
      },
    ],
  })
}

// ==================== 交互 ====================

async function changeDays(d: number) {
  days.value = d
  try {
    await loadTrend()
    renderTrendChart()
  } catch (e: any) {
    toast.error(e.message || '加载失败')
  }
}

function handleResize() {
  trendChart?.resize()
  bankChart?.resize()
}

onMounted(() => {
  loadAll()
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  trendChart?.dispose()
  bankChart?.dispose()
})
</script>

<style scoped>
.stats-page {
  min-height: 100vh;
  color: #20332b;
  background: #f5f8f6;
}

.stats-header {
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
}
.stats-header h1 {
  margin: 0;
  font-size: 20px;
  font-weight: 650;
}
.range-picker {
  display: flex;
  gap: 3px;
  padding: 4px;
  border-radius: 10px;
  background: #f1f5f3;
  margin-left: auto;
}
.range-picker button {
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
.range-picker button.active {
  color: #17644f;
  background: #fff;
  box-shadow: 0 2px 6px rgba(30, 64, 53, .08);
  font-weight: 600;
}

.status-block {
  padding: 140px 24px;
  text-align: center;
  color: #77857d;
}

.stats-body {
  max-width: 1080px;
  margin: 0 auto;
  padding: 40px 28px 80px;
}

/* ============ 概览卡片 ============ */
.overview-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
}
.overview-card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  padding: 22px 24px;
  border: 1px solid #e0e8e3;
  border-radius: 14px;
  background: #fff;
  box-shadow: 0 6px 20px rgba(31, 45, 61, .04);
}
.overview-label {
  color: #7a8b9b;
  font-size: 12px;
  font-weight: 600;
}
.overview-value {
  margin-top: 12px;
  color: #1f6956;
  font-size: 32px;
  font-weight: 700;
  line-height: 1;
}
.overview-value.correct {
  color: #28735f;
}
.overview-card small {
  margin-top: 6px;
  color: #85928b;
  font-size: 12px;
}

/* ============ 图表区 ============ */
.chart-section {
  margin-top: 40px;
  padding: 24px 24px 16px;
  border: 1px solid #e0e8e3;
  border-radius: 14px;
  background: #fff;
  box-shadow: 0 6px 20px rgba(31, 45, 61, .04);
}
.section-heading {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}
.eyebrow {
  margin: 0 0 8px;
  color: #6f9083;
  font-size: 11px;
  letter-spacing: 1.3px;
  font-weight: 700;
}
.section-heading h2 {
  margin: 0;
  font-size: 18px;
}
.section-heading > span {
  color: #85928b;
  font-size: 12px;
}
.chart-box {
  width: 100%;
  height: 320px;
}
.empty-tip {
  padding: 60px 0;
  text-align: center;
  color: #9aa59f;
  font-size: 14px;
}

/* ============ 响应式 ============ */
@media (max-width: 900px) {
  .overview-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}
@media (max-width: 700px) {
  .stats-header {
    padding: 0 20px;
  }
  .back-button span {
    display: none;
  }
  .stats-body {
    padding: 24px 16px 60px;
  }
  .overview-value {
    font-size: 26px;
  }
  .chart-box {
    height: 280px;
  }
  .section-heading {
    align-items: flex-start;
    flex-direction: column;
    gap: 4px;
  }
}
</style>