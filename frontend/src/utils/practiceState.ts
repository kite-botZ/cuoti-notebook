export type QuestionActivity = {
  wrongCount: number
  favorite: boolean
  cut: boolean
  note: string
  updatedAt: string
}

export type ActivityMap = Record<string, Partial<QuestionActivity>>

const STORAGE_KEY = 'mistake-notebook-question-activity'

export function readActivity(): ActivityMap {
  try {
    const value = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}')
    return value && typeof value === 'object' ? value as ActivityMap : {}
  } catch {
    return {}
  }
}

export function writeActivity(activity: ActivityMap) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(activity))
}

export function activityFor(activity: ActivityMap, questionId: number) {
  return activity[String(questionId)] || {}
}
