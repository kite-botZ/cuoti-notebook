<template>
  <div class="ai-assistant">
    <!-- 悬浮按钮 -->
    <button class="ai-fab" type="button" @click="togglePanel" :class="{ active: isOpen }">
      <span v-if="!isOpen">AI</span>
      <span v-else>✕</span>
    </button>

    <!-- 抽屉面板 -->
    <transition name="slide">
      <div v-if="isOpen" class="ai-panel">
        <div class="ai-panel-header">
          <h3>AI 助手</h3>
          <button type="button" @click="closePanel">✕</button>
        </div>

        <div ref="messagesRef" class="ai-messages">
          <div v-if="!messages.length" class="ai-welcome">
            <p>你好！我是 AI 学习助手。</p>
            <p>关于这道题，有任何问题都可以问我。</p>
          </div>
          <div v-for="(msg, i) in messages" :key="i" class="ai-message" :class="msg.role">
            <div class="ai-bubble" v-html="renderMarkdown(msg.content)"></div>
          </div>
          <div v-if="streaming" class="ai-message assistant">
            <div class="ai-bubble" v-html="renderMarkdown(streamingText)"></div>
            <span class="cursor">▌</span>
          </div>
        </div>

        <div class="ai-input-area">
          <textarea
            v-model="inputText"
            class="ai-input"
            rows="2"
            placeholder="输入你的问题…"
            :disabled="streaming"
            @keydown.enter.exact.prevent="sendMessage"
          ></textarea>
          <button class="ai-send-btn" type="button" :disabled="streaming || !inputText.trim()" @click="sendMessage">
            发送
          </button>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { renderMarkdown } from '@/utils/renderMarkdown'


const props = defineProps<{
  questionId: number
}>()

const isOpen = ref(false)
const inputText = ref('')
const messages = ref<{ role: string; content: string }[]>([])
const streaming = ref(false)
const streamingText = ref('')
const messagesRef = ref<HTMLDivElement | null>(null)

function togglePanel() {
  isOpen.value = !isOpen.value
}

function closePanel() {
  isOpen.value = false
}



// 监听新消息，自动滚动到底部
watch([messages, streamingText], () => {
  nextTick(() => {
    if (messagesRef.value) {
      messagesRef.value.scrollTop = messagesRef.value.scrollHeight
    }
  })
}, { deep: true })

async function sendMessage() {
  const text = inputText.value.trim()
  if (!text || streaming.value) return

  messages.value.push({ role: 'user', content: text })
  inputText.value = ''
  streaming.value = true
  streamingText.value = ''

  try {
    const token = localStorage.getItem('token')
    const res = await fetch('/api/ai/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`,
      },
      body: JSON.stringify({
        question_id: props.questionId,
        messages: messages.value.map(m => ({ role: m.role, content: m.content })),
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

          let parsed: any
          try {
            parsed = JSON.parse(data)
          } catch {
            continue
          }

          // 后端返回错误时，把错误抛到外层 catch
          if (parsed.error) {
            throw new Error(parsed.error)
          }
          if (parsed.content) {
            streamingText.value += parsed.content
          }
        }
      }
    }

    // 流结束，把结果存入消息列表
    messages.value.push({ role: 'assistant', content: streamingText.value })
    streamingText.value = ''
    } catch (e: any) {
    const msg = e?.message || 'AI 服务暂时不可用'
    messages.value.push({
      role: 'assistant',
      content: `⚠️ ${msg}\n\n请确认 Ollama 正在运行，并已下载模型。`,
    })
    console.error(e)
  } finally {
    streaming.value = false
  }
}

// 当题目变化时，清空对话
watch(() => props.questionId, () => {
  messages.value = []
  streamingText.value = ''
})
</script>

<style scoped>

.ai-bubble :deep(.katex-display) {
  margin: 10px 0;
  overflow-x: auto;
}
.ai-bubble :deep(.katex) {
  font-size: 1em;
}

.ai-assistant {
  position: fixed;
  bottom: 100px;
  right: 30px;
  z-index: 100;
}

.ai-fab {
  width: 54px;
  height: 54px;
  border-radius: 50%;
  border: none;
  background: linear-gradient(135deg, #28735f, #3da17e);
  color: #fff;
  font-size: 16px;
  font-weight: 700;
  cursor: pointer;
  box-shadow: 0 6px 20px rgba(40, 115, 95, .3);
  transition: transform .2s, box-shadow .2s;
}
.ai-fab:hover {
  transform: scale(1.06);
  box-shadow: 0 8px 26px rgba(40, 115, 95, .4);
}
.ai-fab.active {
  background: #5a6b7c;
  box-shadow: 0 4px 14px rgba(0, 0, 0, .2);
}

.ai-panel {
  position: fixed;
  top: 0;
  right: 0;
  width: 400px;
  height: 100vh;
  background: #fff;
  box-shadow: -4px 0 30px rgba(0, 0, 0, .1);
  display: flex;
  flex-direction: column;
  z-index: 101;
}
.ai-panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid #eef2f0;
}
.ai-panel-header h3 {
  margin: 0;
  font-size: 16px;
  color: #1f2d3d;
}
.ai-panel-header button {
  border: 0;
  background: transparent;
  font-size: 16px;
  color: #7e8c85;
  cursor: pointer;
}

.ai-messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.ai-welcome {
  text-align: center;
  color: #9aa59f;
  font-size: 13px;
  padding: 40px 0;
  line-height: 1.8;
}
.ai-message {
  display: flex;
}
.ai-message.user {
  justify-content: flex-end;
}
.ai-message.assistant {
  justify-content: flex-start;
}
.ai-bubble {
  max-width: 85%;
  padding: 10px 14px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.6;
  word-break: break-word;
}
.ai-message.user .ai-bubble {
  background: #28735f;
  color: #fff;
  border-bottom-right-radius: 4px;
}
.ai-message.assistant .ai-bubble {
  background: #f1f9f5;
  color: #2d4238;
  border-bottom-left-radius: 4px;
}
.cursor {
  animation: blink .8s infinite;
  color: #28735f;
  font-weight: 700;
  align-self: flex-end;
}
@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}

.ai-input-area {
  display: flex;
  gap: 8px;
  padding: 12px 16px;
  border-top: 1px solid #eef2f0;
}
.ai-input {
  flex: 1;
  border: 1px solid #d8e4de;
  border-radius: 8px;
  padding: 8px 12px;
  font-family: inherit;
  font-size: 14px;
  resize: none;
  outline: none;
}
.ai-input:focus {
  border-color: #28735f;
}
.ai-send-btn {
  padding: 8px 16px;
  border: 0;
  border-radius: 8px;
  background: #28735f;
  color: #fff;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
}
.ai-send-btn:disabled {
  opacity: .5;
  cursor: not-allowed;
}

.slide-enter-active, .slide-leave-active {
  transition: transform .25s ease;
}
.slide-enter-from, .slide-leave-to {
  transform: translateX(100%);
}
</style>