import katex from 'katex'
import 'katex/dist/katex.min.css'

/**
 * 统一的 Markdown + LaTeX 渲染：
 * - ![](url) → <img>
 * - $...$ → 行内公式
 * - $$...$$ → 块级公式
 * - \n → <br>
 * 同时做 HTML 转义，防止 XSS。
 */
export function renderMarkdown(text: string): string {
  if (!text) return ''

  const formulas: string[] = []

  // 1. 先提取公式，用占位符替换。公式不能参与后续的 HTML 转义。
  let safe = text

  // 块级公式 $$...$$
  safe = safe.replace(/\$\$([\s\S]+?)\$\$/g, (_, formula) => {
    try {
      const html = katex.renderToString(String(formula).trim(), {
        displayMode: true,
        throwOnError: false,
      })
      formulas.push(html)
      return `\u0000F${formulas.length - 1}\u0000`
    } catch {
      return _
    }
  })

  // 行内公式 $...$（不匹配跨行、不匹配 $$）
  safe = safe.replace(/\$([^\$\n]+?)\$/g, (_, formula) => {
    try {
      const html = katex.renderToString(String(formula).trim(), {
        displayMode: false,
        throwOnError: false,
      })
      formulas.push(html)
      return `\u0000F${formulas.length - 1}\u0000`
    } catch {
      return _
    }
  })

  // 2. 转义 HTML（此时公式已被替换成占位符，不会被误伤）
  safe = safe
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')

  // 3. 渲染图片
  safe = safe.replace(
    /!\[([^\]]*)\]\(([^)]+)\)/g,
    '<img src="$2" alt="$1" class="stem-img" />'
  )

  // 4. 换行
  safe = safe.replace(/\n/g, '<br />')

  // 5. 把占位符换回 KaTeX 生成的 HTML
  safe = safe.replace(/\u0000F(\d+)\u0000/g, (_, idx) => formulas[Number(idx)] || '')

  return safe
}

/**
 * 把题干里的公式和图片转成纯文本，用于列表展示。
 */
export function plainStem(text: string): string {
  if (!text) return ''
  return text
    .replace(/!\[[^\]]*\]\([^)]+\)/g, '［图片］')
    .replace(/\$\$[\s\S]+?\$\$/g, '［公式］')
    .replace(/\$[^\$\n]+?\$/g, '［公式］')
    .replace(/\n/g, ' ')
    .trim()
}