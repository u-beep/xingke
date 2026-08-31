// ============================================
// 型刻 API 服务层
// 封装所有后端接口调用，统一错误处理
// 后端地址: http://localhost:8900
// ============================================

import type {
  ChatRequest,
  ChatResponse,
  SessionListResponse,
  ToolCallRequest,
  ToolCallResponse,
  BMRCalculatorParams,
  TDEECalculatorParams,
  BMICalculatorParams,
  DietPlanParams,
  ExercisePlanParams,
  AnalyzeBodyParams,
  AnalyzeBodyBody,
  FoodRecognitionRequest,
  KnowledgeSearchRequest,
  KnowledgeAddRequest,
} from './types'
import { getToken, clearAuth, redirectToLogin } from './authStore'

// —— 基础配置 ——

const API_BASE = '/api/v1'

/** 通用请求头：自动附带登录 Token */
function buildHeaders(extra?: HeadersInit): HeadersInit {
  const token = getToken()
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...extra,
  }
}

/** 401 统一处理：清除本地登录态并跳转登录页 */
function handleUnauthorized(): void {
  clearAuth()
  redirectToLogin()
}

/** 通用 JSON 请求（导出供 auth 模块复用） */
export async function request<T>(
  url: string,
  options: RequestInit = {}
): Promise<T> {
  const resp = await fetch(url, {
    headers: buildHeaders(options.headers),
    ...options,
  })

  if (!resp.ok) {
    if (resp.status === 401) {
      handleUnauthorized()
    }
    const error = await resp.json().catch(() => ({ detail: resp.statusText }))
    throw new Error(error.detail?.[0]?.msg || error.detail || `请求失败: ${resp.status}`)
  }

  // 部分接口可能返回空 body
  const text = await resp.text()
  return text ? JSON.parse(text) : ({} as T)
}

/** 构建 query string */
function buildQuery(params: Record<string, any>): string {
  const entries = Object.entries(params).filter(
    ([, v]) => v !== undefined && v !== null && v !== ''
  )
  if (entries.length === 0) return ''
  return '?' + entries
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
    .join('&')
}

// ============================================
//  对话模块 API
// ============================================

export const chatApi = {
  /** 发起对话（非流式） */
  async ask(data: ChatRequest): Promise<ChatResponse> {
    return request<ChatResponse>(`${API_BASE}/chat/ask`, {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },

  /**
   * 发起对话（流式 SSE）
   * 返回一个 async generator，逐 token 产出
   * @param signal 可选的 AbortSignal，用于超时中断
   */
  async *stream(data: ChatRequest, signal?: AbortSignal): AsyncGenerator<{ token?: string; done?: boolean; session_id?: string }> {
    const resp = await fetch(`${API_BASE}/chat/stream`, {
      method: 'POST',
      headers: buildHeaders(),
      body: JSON.stringify(data),
      signal,
    })

    if (!resp.ok) {
      if (resp.status === 401) {
        handleUnauthorized()
      }
      throw new Error(`流式对话请求失败: ${resp.status}`)
    }

    const reader = resp.body!.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed || !trimmed.startsWith('data:')) continue
          const jsonStr = trimmed.slice(5).trim()
          try {
            const payload = JSON.parse(jsonStr)
            yield payload
          } catch {
            // 忽略解析失败的行
          }
        }
      }
    } finally {
      // 中断或正常结束时释放 reader
      reader.releaseLock()
    }
  },

  /**
   * 异步发起对话（轮询模式）— 立即返回 task_id，后端后台跑 AgentLoop。
   * 配合 poll() 轮询结果，避免 SSE 长连接在后端慢响应时被超时 abort。
   */
  async start(data: ChatRequest): Promise<{ task_id: string; session_id: string; status: string }> {
    return request<any>(`${API_BASE}/chat/start`, {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },

  /**
   * 轮询对话任务结果。
   * - status="running"：AgentLoop 仍在执行
   * - status="done"：完成，result 为完整回复
   * - status="error"：失败，error 为错误信息
   * - status="cancelled"：已被用户终止
   */
  async poll(taskId: string, signal?: AbortSignal): Promise<{
    task_id: string
    status: 'running' | 'done' | 'error' | 'cancelled' | 'unknown'
    result: string
    error: string | null
    session_id: string
    done: boolean
    /** 后台提取状态：pending=提取中 / ready=已就绪 / none=无提取 */
    extract_status?: 'pending' | 'ready' | 'none'
  }> {
    return request<any>(`${API_BASE}/chat/poll?task_id=${encodeURIComponent(taskId)}`, { signal })
  },

  /**
   * 拉取后台提取结果（饮食/饮水）。
   * 主回复返回后提取仍在后台跑，前端在用户阅读期间轮询本接口。
   * - status="ready"：提取完成（diet_data/water_data 可能为 null 表示无记录）
   * - status="pending"：提取仍在进行，稍后再来
   * - status="none"：终结态（任务不存在/未完成/无提取），停止轮询
   */
  async extract(taskId: string, signal?: AbortSignal): Promise<{
    status: 'ready' | 'pending' | 'none'
    diet_data: { foods: any[]; total_calories: number } | null
    water_data: { amount_ml: number; drink_type: string; description: string } | null
  }> {
    return request<any>(`${API_BASE}/chat/extract?task_id=${encodeURIComponent(taskId)}`, { signal })
  },

  /** 终止正在生成的对话任务（用户点击"停止生成"） */
  async cancel(taskId: string): Promise<{ success: boolean; message: string }> {
    return request<any>(`${API_BASE}/chat/cancel?task_id=${encodeURIComponent(taskId)}`, { method: 'POST' })
  },

  /** 查询会话列表 */
  async listSessions(userId?: string): Promise<SessionListResponse> {
    const query = buildQuery({ user_id: userId })
    return request<SessionListResponse>(`${API_BASE}/chat/sessions${query}`)
  },

  /** 查询会话历史 */
  async getSession(sessionId: string): Promise<any> {
    return request<any>(`${API_BASE}/chat/sessions/${sessionId}`)
  },

  /** 清空会话历史 */
  async clearSession(sessionId: string): Promise<any> {
    return request<any>(`${API_BASE}/chat/sessions/${sessionId}`, { method: 'DELETE' })
  },

  /** 删除会话 */
  async deleteSession(sessionId: string): Promise<any> {
    return request<any>(`${API_BASE}/chat/sessions/${sessionId}/delete`, { method: 'DELETE' })
  },

  /** 提交用户消息（立即入库，刷新不丢失） */
  async sendMessage(data: ChatRequest): Promise<{
    session_id: string
    user_message: string
    message_count: number
  }> {
    return request<any>(`${API_BASE}/chat/send`, {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },

  /** 获取或创建当天会话（刷新页面时调用，恢复当天对话） */
  async getTodaySession(userId: string): Promise<{
    session_id: string
    created_at: string
    history: Array<{ role: string; content: string; name?: string; args?: any }>
    message_count: number
  }> {
    const query = buildQuery({ user_id: userId })
    return request<any>(`${API_BASE}/chat/today${query}`)
  },

  /** 按日期查询会话历史（返回合并后的完整消息列表） */
  async listSessionsByDate(userId: string, date?: string): Promise<{
    session_id: string
    created_at: string
    history: Array<{ role: string; content: string; name?: string; args?: any }>
    message_count: number
  }> {
    const query = buildQuery({ user_id: userId, date })
    return request<any>(`${API_BASE}/chat/sessions/by-date${query}`)
  },
}

// ============================================
//  工具模块 API
// ============================================

export const toolsApi = {
  /** 列出所有可用工具 */
  async list(): Promise<any> {
    return request<any>(`${API_BASE}/tools/list`)
  },

  /** 直接调用工具 */
  async call(data: ToolCallRequest): Promise<ToolCallResponse> {
    return request<ToolCallResponse>(`${API_BASE}/tools/call`, {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },

  /** 计算基础代谢率 (BMR) */
  async calculateBMR(params: BMRCalculatorParams = {}): Promise<any> {
    const query = buildQuery(params)
    return request<any>(`${API_BASE}/tools/calculate/bmr${query}`, { method: 'POST' })
  },

  /** 计算每日总能量消耗 (TDEE) */
  async calculateTDEE(params: TDEECalculatorParams): Promise<any> {
    const query = buildQuery(params)
    return request<any>(`${API_BASE}/tools/calculate/tdee${query}`, { method: 'POST' })
  },

  /** 计算身体质量指数 (BMI) */
  async calculateBMI(params: BMICalculatorParams): Promise<any> {
    const query = buildQuery(params)
    return request<any>(`${API_BASE}/tools/calculate/bmi${query}`, { method: 'POST' })
  },

  /** 生成个性化饮食方案 */
  async generateDietPlan(params: DietPlanParams = {}, signal?: AbortSignal): Promise<any> {
    const query = buildQuery(params)
    return request<any>(`${API_BASE}/tools/diet-plan${query}`, { method: 'POST', signal })
  },

  /** 生成运动训练计划 */
  async generateExercisePlan(params: ExercisePlanParams = {}): Promise<any> {
    const query = buildQuery(params)
    return request<any>(`${API_BASE}/tools/exercise-plan${query}`, { method: 'POST' })
  },

  /** 分析身材数据 */
  async analyzeBody(
    body: AnalyzeBodyBody,
    params: AnalyzeBodyParams = {}
  ): Promise<any> {
    const query = buildQuery(params)
    return request<any>(`${API_BASE}/tools/analyze-body${query}`, {
      method: 'POST',
      body: JSON.stringify(body),
    })
  },
}

// ============================================
//  图像识别模块 API
// ============================================

export const visionApi = {
  /** 食物识别 */
  async recognizeFood(data: FoodRecognitionRequest, signal?: AbortSignal): Promise<any> {
    return request<any>(`${API_BASE}/vision/food-recognition`, {
      method: 'POST',
      body: JSON.stringify(data),
      signal,
    })
  },

  /** 获取食物营养数据库 */
  async getFoodDatabase(): Promise<any> {
    return request<any>(`${API_BASE}/vision/food-database`)
  },

  /** 获取低置信度识别记录 */
  async getLowConfidenceLog(limit: number = 50): Promise<any> {
    const query = buildQuery({ limit })
    return request<any>(`${API_BASE}/vision/low-confidence-log${query}`)
  },
}

// ============================================
//  知识库模块 API
// ============================================

export const knowledgeApi = {
  /** 知识库统计 */
  async stats(): Promise<any> {
    return request<any>(`${API_BASE}/knowledge/stats`)
  },

  /** 知识分类列表 */
  async categories(): Promise<any> {
    return request<any>(`${API_BASE}/knowledge/categories`)
  },

  /** 知识检索 */
  async search(data: KnowledgeSearchRequest): Promise<any> {
    return request<any>(`${API_BASE}/knowledge/search`, {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },

  /** 添加知识文档 */
  async add(data: KnowledgeAddRequest): Promise<any> {
    return request<any>(`${API_BASE}/knowledge/add`, {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },

  /** 批量添加知识文档 */
  async addBatch(documents: Record<string, any>[]): Promise<any> {
    return request<any>(`${API_BASE}/knowledge/add-batch`, {
      method: 'POST',
      body: JSON.stringify(documents),
    })
  },

  /** 清空知识库 */
  async clear(): Promise<any> {
    return request<any>(`${API_BASE}/knowledge/clear`, { method: 'DELETE' })
  },
}

// ============================================
//  系统模块 API
// ============================================

export const systemApi = {
  /** 健康检查 */
  async health(): Promise<any> {
    return request<any>('/health')
  },

  /** 模型网关状态 */
  async gatewayStats(): Promise<any> {
    return request<any>(`${API_BASE}/gateway/stats`)
  },

  /** 安全拦截统计 */
  async safetyStats(): Promise<any> {
    return request<any>(`${API_BASE}/safety/stats`)
  },

  /** 安全拦截日志 */
  async safetyLog(limit: number = 50): Promise<any> {
    const query = buildQuery({ limit })
    return request<any>(`${API_BASE}/safety/log${query}`)
  },
}

// ============================================
//  体重记录模块 API
// ============================================

export const weightApi = {
  /** 记录体重 */
  async record(data: { weight_kg: number; body_fat_pct?: number; waist_cm?: number; hip_cm?: number; notes?: string }): Promise<any> {
    return request<any>(`${API_BASE}/weight/record`, {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },

  /** 查询体重历史 */
  async history(days: number = 30, limit: number = 100): Promise<any> {
    const query = buildQuery({ days, limit })
    return request<any>(`${API_BASE}/weight/history${query}`)
  },

  /** 获取最新体重 */
  async latest(): Promise<any> {
    return request<any>(`${API_BASE}/weight/latest`)
  },

  /** 获取体重统计 */
  async stats(days: number = 7): Promise<any> {
    const query = buildQuery({ days })
    return request<any>(`${API_BASE}/weight/stats${query}`)
  },
}

// ============================================
//  饮食记录模块 API
// ============================================

export const dietApi = {
  /** 记录饮食 */
  async record(data: { meal_type: string; food_name: string; amount_g?: number; calories?: number; protein_g?: number; carbs_g?: number; fat_g?: number; image_url?: string }): Promise<any> {
    return request<any>(`${API_BASE}/diet/record`, {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },

  /** 获取今日饮食 */
  async today(): Promise<any> {
    return request<any>(`${API_BASE}/diet/today`)
  },

  /** 查询饮食历史 */
  async history(days: number = 30): Promise<any> {
    const query = buildQuery({ days })
    return request<any>(`${API_BASE}/diet/history${query}`)
  },

  /** 按日期获取饮食统计 */
  async summary(userId: string, date?: string): Promise<{
    total_calories: number
    total_protein_g: number
    total_carbs_g: number
    total_fat_g: number
    record_count: number
    meal_breakdown: Record<string, number>
  }> {
    const query = buildQuery({ user_id: userId, date })
    return request<any>(`${API_BASE}/diet/summary${query}`)
  },

  /** 确认计入今日热量统计 */
  async confirm(userId: string, foods: any[]): Promise<{ success: boolean; saved_count: number; total_calories: number }> {
    return request<any>(`${API_BASE}/diet/confirm`, {
      method: 'POST',
      body: JSON.stringify({ user_id: userId, foods }),
    })
  },

  /** Agent 智能饮食推荐（结合剩余热量 + 营养知识库 + 外卖菜品） */
  async recommendation(userId: string): Promise<{
    user_id: string
    remaining_calories: number
    consumed_calories: number
    budget: number
    recommendation: string
    dishes_count: number
    budget_source: string
  }> {
    const query = buildQuery({ user_id: userId })
    return request<any>(`${API_BASE}/diet/recommendation${query}`)
  },

  /** 按日期查询饮食记录(外卖+手动+冰箱菜谱,纯记录展示) */
  async daily(date?: string): Promise<DailyDietResult> {
    const query = date ? `?date=${date}` : ''
    return request<any>(`${API_BASE}/diet/daily${query}`)
  },
}

/** 每日饮食聚合记录项(统一格式,三来源合并) */
export interface DailyDietRecord {
  record_key: string
  id: number
  meal_type: string
  food_name: string
  amount_g: number | null
  calories: number | null
  protein_g: number | null
  carbs_g: number | null
  fat_g: number | null
  recorded_at: string | null
  image_url: string | null
  source: 'order' | 'chat' | 'fridge'
  source_label: string // 外卖 / 手动记录 / 冰箱菜谱
  include_in_stats: boolean
  ingredients_summary?: string | null
}

export interface DailyDietResult {
  date: string
  records: DailyDietRecord[]
  count: number
  summary: {
    total_calories: number
    total_protein_g: number
    total_carbs_g: number
    total_fat_g: number
    record_count: number
    meal_breakdown: Record<string, number>
    source_breakdown: Record<string, { calories: number; protein_g: number }>
    fridge_calories: number
    budget?: number
    remaining?: number
    budget_source?: string
  }
}

// ============================================
//  用户资料 / 每日热量预算 API
// ============================================

export const profileApi = {
  /** 获取当前用户完整资料（身体数据/偏好/目标） */
  async me(): Promise<{
    user_id: string
    profile: {
      user_id: string
      height_cm: number | null
      weight_kg: number | null
      age: number | null
      gender: string | null
      target_weight_kg: number | null
      exercise_frequency: string | null
      health_goal: string | null
      target_date: string | null
      sleep_hours: number | null
      water_intake_ml: number | null
      daily_calorie_budget: number | null
    }
    is_complete: boolean
  }> {
    return request<any>(`${API_BASE}/profile/me`)
  },

  /** 获取每日热量目标预算（含 TDEE 建议值） */
  async getCalorieBudget(userId: string): Promise<{
    user_id: string
    daily_calorie_budget: number | null
    suggested_budget: number | null
    has_custom: boolean
  }> {
    const query = buildQuery({ user_id: userId })
    return request<any>(`${API_BASE}/profile/calorie-budget${query}`)
  },

  /** 设置每日热量目标预算 */
  async setCalorieBudget(userId: string, budget: number): Promise<{
    success: boolean
    user_id: string
    daily_calorie_budget: number
    message: string
  }> {
    return request<any>(`${API_BASE}/profile/calorie-budget`, {
      method: 'PUT',
      body: JSON.stringify({ user_id: userId, daily_calorie_budget: budget }),
    })
  },
}

// ============================================
//  饮水记录模块 API
// ============================================

export interface WaterSummary {
  total_ml: number
  record_count: number
  goal_ml: number
  remaining_ml: number
  percentage: number
  type_breakdown: Record<string, number>
}

export const waterApi = {
  /** 记录饮水 */
  async record(data: { amount_ml: number; drink_type?: string; notes?: string }): Promise<any> {
    return request<any>(`${API_BASE}/hydration/record`, {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },

  /** 获取今日饮水记录及统计 */
  async today(): Promise<{ records: any[]; summary: WaterSummary }> {
    return request<any>(`${API_BASE}/hydration/today`)
  },

  /** 按日期获取饮水统计 */
  async summary(userId: string, date?: string): Promise<WaterSummary> {
    const query = buildQuery({ user_id: userId, date })
    return request<any>(`${API_BASE}/hydration/summary${query}`)
  },

  /** 确认计入今日饮水总量（用户在前端确认 AI 提取的饮水量） */
  async confirm(
    userId: string,
    amount_ml: number,
    drink_type: string = 'water',
    notes?: string,
  ): Promise<{ success: boolean; record_id: number; saved_ml: number; total_ml: number; percentage: number; goal_ml: number }> {
    return request<any>(`${API_BASE}/hydration/confirm`, {
      method: 'POST',
      body: JSON.stringify({ user_id: userId, amount_ml, drink_type, notes }),
    })
  },

  /** 查询饮水历史 */
  async history(days: number = 30): Promise<any> {
    const query = buildQuery({ days })
    return request<any>(`${API_BASE}/hydration/history${query}`)
  },
}

// ============================================
//  运动记录模块 API
// ============================================

export const exerciseApi = {
  /** 记录运动 */
  async record(data: { exercise_name: string; exercise_type?: string; duration_min?: number; calories_burned?: number; completed?: boolean; scheduled_date?: string; notes?: string }): Promise<any> {
    return request<any>(`${API_BASE}/exercise/record`, {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },

  /** 获取今日运动 */
  async today(): Promise<any> {
    return request<any>(`${API_BASE}/exercise/today`)
  },

  /** 获取本周运动 */
  async week(): Promise<any> {
    return request<any>(`${API_BASE}/exercise/week`)
  },

  /** 查询运动历史 */
  async history(days: number = 30): Promise<any> {
    const query = buildQuery({ days })
    return request<any>(`${API_BASE}/exercise/history${query}`)
  },

  /** 查询指定日期区间的运动记录（日历切换历史用） */
  async range(startDate: string, endDate: string): Promise<any> {
    const query = buildQuery({ start_date: startDate, end_date: endDate })
    return request<any>(`${API_BASE}/exercise/history${query}`)
  },

  /** 按日聚合运动统计（次数/时长/消耗热量，用于周/月/年图表） */
  async stats(startDate: string, endDate: string): Promise<{ stats: DailyStat[] }> {
    const query = buildQuery({ start_date: startDate, end_date: endDate })
    return request<any>(`${API_BASE}/exercise/stats${query}`)
  },

  /** 删除运动记录 */
  async deleteRecord(recordId: number): Promise<{ success: boolean }> {
    return request<any>(`${API_BASE}/exercise/record/${recordId}`, { method: 'DELETE' })
  },
}

// ============================================
//  运动计划模块 API
// ============================================

export interface ExerciseOption {
  name: string
  met: number
}

export interface ExerciseGroup {
  cardio: ExerciseOption[]
  strength: ExerciseOption[]
  anaerobic: ExerciseOption[]
}

export interface PlanItem {
  id: number
  exercise_type: string
  exercise_name: string
  duration_min: number
  calories_burned: number
  completed: boolean
}

export interface PlanSummary {
  /** 已完成项目的实际运动消耗，仅该值参与热量缺口计算。 */
  total_calories: number
  total_duration: number
  completed_count: number
  /** 所有待办与已完成项目的预计值，仅用于计划展示。 */
  planned_calories: number
  planned_duration: number
  item_count: number
  items: PlanItem[]
}

export interface ExerciseRecordInfo {
  id: number
  exercise_name: string
  exercise_type: string | null
  duration_min: number | null
  calories_burned: number | null
  completed: boolean
  scheduled_date: string | null
  recorded_at: string | null
  notes: string | null
}

/** 按日聚合的运动统计点 */
export interface DailyStat {
  date: string
  count: number
  duration_min: number
  calories: number
}

export const exercisePlanApi = {
  /** 获取运动列表 */
  async exercises(): Promise<ExerciseGroup> {
    return request<any>(`${API_BASE}/exercise-plan/exercises`)
  },

  /** 添加运动计划项 */
  async add(data: {
    exercise_type: string
    exercise_name: string
    duration_min: number
    plan_date?: string
  }): Promise<{ success: boolean; item_id: number; calories_burned: number }> {
    return request<any>(`${API_BASE}/exercise-plan/add`, {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },

  /** 获取今日运动计划 */
  async today(userId: string): Promise<PlanSummary> {
    const query = buildQuery({ user_id: userId })
    return request<any>(`${API_BASE}/exercise-plan/today${query}`)
  },

  /** 按日期获取运动计划 */
  async byDate(userId: string, date: string): Promise<PlanSummary> {
    const query = buildQuery({ user_id: userId, date })
    return request<any>(`${API_BASE}/exercise-plan/by-date${query}`)
  },

  /** 确认完成计划项，并将实际消耗写入运动记录。 */
  async completeItem(itemId: number): Promise<{
    success: boolean
    record_id?: number
    calories_burned?: number
    already_completed?: boolean
    message?: string
  }> {
    return request<any>(`${API_BASE}/exercise-plan/item/${itemId}/complete`, { method: 'POST' })
  },

  /** 删除运动计划项 */
  async deleteItem(itemId: number): Promise<{ success: boolean }> {
    return request<any>(`${API_BASE}/exercise-plan/item/${itemId}`, { method: 'DELETE' })
  },

  /** 清空今日运动计划 */
  async clearToday(userId: string): Promise<{ success: boolean }> {
    const query = buildQuery({ user_id: userId })
    return request<any>(`${API_BASE}/exercise-plan/clear-today${query}`, { method: 'DELETE' })
  },
}

// ============================================
//  运动方案模板模块 API
// ============================================

export interface ExerciseCalorieInfo {
  id: number
  exercise_name: string
  exercise_type: string
  met_value: number
  category: string
  intensity: string
  description: string
}

export interface ExerciseCalorieGroup {
  cardio: ExerciseCalorieInfo[]
  strength: ExerciseCalorieInfo[]
  anaerobic: ExerciseCalorieInfo[]
}

export interface TemplateItem {
  exercise_name: string
  exercise_type: string
  duration_min: number
}

export interface WorkoutTemplateInfo {
  id: number
  template_name: string
  description: string
  items: TemplateItem[]
  total_duration: number
  estimated_calories: number
  created_at: string
}

export const workoutApi = {
  /** 获取运动热量规则列表（按类型分组） */
  async exercises(): Promise<ExerciseCalorieGroup> {
    return request<any>(`${API_BASE}/workout/exercises`)
  },

  /** 搜索运动 */
  async searchExercises(keyword: string): Promise<ExerciseCalorieInfo[]> {
    const query = buildQuery({ keyword })
    return request<any>(`${API_BASE}/workout/exercises/search${query}`)
  },

  /** 创建运动方案模板 */
  async createTemplate(data: {
    template_name: string
    description?: string
    items: TemplateItem[]
  }): Promise<{ success: boolean; template_id: number }> {
    return request<any>(`${API_BASE}/workout/templates`, {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },

  /** 获取模板列表 */
  async listTemplates(userId: string): Promise<{ templates: WorkoutTemplateInfo[]; count: number }> {
    const query = buildQuery({ user_id: userId })
    return request<any>(`${API_BASE}/workout/templates${query}`)
  },

  /** 获取模板详情 */
  async getTemplate(templateId: number): Promise<WorkoutTemplateInfo> {
    return request<any>(`${API_BASE}/workout/templates/${templateId}`)
  },

  /** 删除模板 */
  async deleteTemplate(templateId: number): Promise<{ success: boolean }> {
    return request<any>(`${API_BASE}/workout/templates/${templateId}`, { method: 'DELETE' })
  },

  /** 应用模板到当天计划 */
  async applyTemplate(templateId: number, planDate?: string): Promise<{
    success: boolean
    added_count: number
    total_calories: number
    template_name: string
  }> {
    return request<any>(`${API_BASE}/workout/templates/apply`, {
      method: 'POST',
      body: JSON.stringify({ template_id: templateId, plan_date: planDate }),
    })
  },
}

// ============================================
//  仪表盘模块 API
// ============================================

export const dashboardApi = {
  /** 获取核心指标聚合 */
  async metrics(): Promise<any> {
    return request<any>(`${API_BASE}/dashboard/metrics`)
  },

  /** 获取周报数据 */
  async weeklySummary(): Promise<any> {
    return request<any>(`${API_BASE}/dashboard/weekly-summary`)
  },
}

// ============================================
//  目标管理模块 API
// ============================================

export const goalsApi = {
  /** 创建目标 */
  async create(data: { goal_type: string; target_value: number; current_value?: number; unit?: string; start_value?: number; deadline?: string }): Promise<any> {
    return request<any>(`${API_BASE}/goals`, {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },

  /** 获取目标进度 */
  async progress(): Promise<any> {
    return request<any>(`${API_BASE}/goals/progress`)
  },

  /** 获取目标列表 */
  async list(status?: string): Promise<any> {
    const query = buildQuery({ status })
    return request<any>(`${API_BASE}/goals${query}`)
  },

  /** 更新目标 */
  async update(goalId: number, data: Record<string, any>): Promise<any> {
    return request<any>(`${API_BASE}/goals/${goalId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    })
  },
}

// ============================================
//  反馈模块 API
// ============================================

export const feedbackApi = {
  /** 提交消息反馈 */
  async submit(data: { session_id?: string; message_id?: string; feedback_type: string; reason?: string }): Promise<any> {
    return request<any>(`${API_BASE}/feedback/message`, {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },
}

// ============================================
//  导出模块 API
// ============================================

export const exportApi = {
  /** 导出体重历史 */
  async weightHistory(days: number = 30, format: string = 'csv'): Promise<Blob> {
    const query = buildQuery({ days, format })
    const resp = await fetch(`${API_BASE}/export/weight-history${query}`, {
      headers: buildHeaders(),
    })
    if (!resp.ok) throw new Error(`导出失败: ${resp.status}`)
    return resp.blob()
  },
}

// ============================================
//  外卖选购模块 API
// ============================================

export interface TakeoutShopInfo {
  id: number
  shop_name: string
  category: string
  monthly_sales: number
  delivery_minutes: number
  min_order_price: number
  delivery_fee: number
  rating: number
  logo_url: string | null
  created_at: string | null
}

export interface TakeoutMenuGroup {
  category: string
  dishes: TakeoutDishInfo[]
}

export interface TakeoutShopDetail extends TakeoutShopInfo {
  menu_groups: TakeoutMenuGroup[]
}

export interface TakeoutDishInfo {
  id: number
  dish_name: string
  shop_name: string
  category: string
  description: string
  amount_g: number | null
  calories: number | null
  protein_g: number | null
  carbs_g: number | null
  fat_g: number | null
  price: number
  image_url: string | null
  available: boolean
  created_at: string | null
}

export interface TakeoutOrderInfo {
  id: number
  user_id: string
  dish_id: number
  dish_name: string
  shop_name: string
  quantity: number
  meal_type: string
  include_in_stats: boolean
  order_status: string
total_calories: number
total_protein_g: number
total_carbs_g?: number
total_fat_g?: number
notes: string | null
  created_at: string | null
  // 关联字段（join takeout_dishes）
  image_url: string | null
  category: string | null
  price: number | null
}

export interface TakeoutSummary {
order_count: number
total_calories: number
total_protein_g: number
total_carbs_g?: number
total_fat_g?: number
stats_calories: number
stats_protein_g: number
stats_carbs_g?: number
stats_fat_g?: number
}

export interface PlaceOrderResult {
  success: boolean
  order_id: number
  include_in_stats: boolean
  message: string
  today_summary: TakeoutSummary
}

export const takeoutApi = {
  /** 获取店家列表（仿美团店列，可按品类过滤） */
  async shops(category?: string): Promise<{ shops: TakeoutShopInfo[]; count: number }> {
    const query = buildQuery({ category })
    return request<any>(`${API_BASE}/takeout/shops${query}`)
  },

  /** 获取店家品类列表 */
  async shopCategories(): Promise<{ categories: string[] }> {
    return request<any>(`${API_BASE}/takeout/shop-categories`)
  },

  /** 获取店家详情 + 按店内分类分组的菜单 */
  async shopDetail(shopName: string): Promise<TakeoutShopDetail> {
    return request<any>(`${API_BASE}/takeout/shops/${encodeURIComponent(shopName)}`)
  },

  /** 获取外卖菜品菜单（可按店家/分类过滤） */
  async dishes(category?: string, shopName?: string): Promise<{ dishes: TakeoutDishInfo[]; count: number }> {
    const query = buildQuery({ category, shop_name: shopName })
    return request<any>(`${API_BASE}/takeout/dishes${query}`)
  },

  /** 获取菜品分类 */
  async categories(): Promise<{ categories: string[] }> {
    return request<any>(`${API_BASE}/takeout/categories`)
  },

  /** 获取菜品详情 */
  async getDish(dishId: number): Promise<TakeoutDishInfo | { success: false; message: string }> {
    return request<any>(`${API_BASE}/takeout/dishes/${dishId}`)
  },

  /** 下单（确认外卖订单）
   * include_in_stats=false 时该份外卖仍写入饮食记录但不计入当日热量与蛋白质统计
   */
  async placeOrder(data: {
    dish_id: number
    quantity?: number
    meal_type?: string
    include_in_stats: boolean
    notes?: string
  }): Promise<PlaceOrderResult> {
    return request<any>(`${API_BASE}/takeout/orders`, {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },

  /** 获取今日外卖订单 */
  async todayOrders(): Promise<{
    orders: TakeoutOrderInfo[]
    count: number
    summary: TakeoutSummary
  }> {
    return request<any>(`${API_BASE}/takeout/orders/today`)
  },

  /** 查询外卖订单历史 */
  async historyOrders(days: number = 30): Promise<{
    orders: TakeoutOrderInfo[]
    count: number
    days: number
  }> {
    const query = buildQuery({ days })
    return request<any>(`${API_BASE}/takeout/orders/history${query}`)
  },

  /** 今日外卖汇总 */
  async summary(): Promise<TakeoutSummary> {
    return request<any>(`${API_BASE}/takeout/orders/summary`)
  },

  /** 取消外卖订单（同步删除关联饮食记录） */
  async cancelOrder(orderId: number): Promise<{
    success: boolean
    message: string
    today_summary: TakeoutSummary | null
  }> {
    return request<any>(`${API_BASE}/takeout/orders/${orderId}`, { method: 'DELETE' })
  },
}

// ============================================
//  我的冰箱模块 API
// ============================================

export interface FridgeItemInfo {
  id: number
  user_id: string
  name: string
  category: string
  quantity_g: number
  unit: string
  calories: number | null
  protein_g: number | null
  carbs_g: number | null
  fat_g: number | null
  image_object_key: string | null
  image_url: string | null // /api/v1/fridge/items/{id}/image
  recognized_at: string | null
  notes: string | null
  shelf_life_days: number | null // 保质期天数(支持小数)
  stored_at: string | null // 放入冰箱时间(ISO 到分钟)
  expires_at: string | null // 预计过期时间(ISO 到分钟)
  created_at: string | null
  updated_at: string | null
}

export interface FridgeRecipeIngredient {
  name: string
  amount_g: number
  unit: string
}

export interface FridgeRecipe {
name: string
description: string
steps: string[]
ingredients: FridgeRecipeIngredient[]
/** 菜谱整餐营养，后端按用料和营养库计算。 */
total_calories?: number
total_protein_g?: number
total_carbs_g?: number
total_fat_g?: number
}

export interface FridgeDeduction {
  name: string
  requested: number
  available: number
  deducted: number
  unit: string
  status: 'ok' | 'insufficient' | 'missing'
  match?: string
  item_id?: number
}

export interface FridgeRecognizedItem {
  name: string
  category?: string
  quantity_g?: number
  unit?: string
  confidence?: number
  calories?: number
  protein?: number
  carbs?: number
  fat?: number
}

export const fridgeApi = {
  /** 获取冰箱食材列表 */
  async list(category?: string): Promise<{
    items: FridgeItemInfo[]
    count: number
    categories: string[]
  }> {
    const query = buildQuery({ category })
    return request<any>(`${API_BASE}/fridge/items${query}`)
  },

  /** 新增食材 */
  async add(data: {
    name: string
    category?: string
    quantity_g: number
    unit?: string
    calories?: number
    protein_g?: number
    carbs_g?: number
    fat_g?: number
    notes?: string
    shelf_life_days?: number | null
  }): Promise<{ success: boolean; item_id: number; item: FridgeItemInfo }> {
    return request<any>(`${API_BASE}/fridge/items`, {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },

  /** 更新食材 */
  async update(
    itemId: number,
    data: {
      name: string
      category?: string
      quantity_g: number
      unit?: string
      calories?: number
      protein_g?: number
      carbs_g?: number
      fat_g?: number
      notes?: string
      shelf_life_days?: number | null
    },
  ): Promise<{ success: boolean; item: FridgeItemInfo }> {
    return request<any>(`${API_BASE}/fridge/items/${itemId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    })
  },

  /** 删除食材 */
  async remove(itemId: number): Promise<{ success: boolean; message: string }> {
    return request<any>(`${API_BASE}/fridge/items/${itemId}`, { method: 'DELETE' })
  },

  /** 拍照识别食材并入库（视觉模型 + MinIO 持久化 + 合并库存） */
  async photoRecognize(
    imageBase64: string,
  ): Promise<{
    success: boolean
    recognized: FridgeRecognizedItem[]
    image_object_key: string
    items: FridgeItemInfo[]
    message?: string
  }> {
    return request<any>(`${API_BASE}/fridge/photo-recognize`, {
      method: 'POST',
      body: JSON.stringify({ image_base64: imageBase64 }),
    })
  },

  /** 基于冰箱现有食材推荐菜谱 */
  async recommendRecipes(preferences?: string): Promise<{
    recipes: FridgeRecipe[]
    fridge_snapshot: FridgeItemInfo[]
    raw?: string
    message?: string
  }> {
    return request<any>(`${API_BASE}/fridge/recipes/recommend`, {
      method: 'POST',
      body: JSON.stringify({ preferences: preferences || '' }),
    })
  },

  /** 确认使用菜谱并扣减库存 */
  async confirmRecipe(recipe: FridgeRecipe): Promise<{
success: boolean
recipe_name: string
deducted: FridgeDeduction[]
insufficient: FridgeDeduction[]
missing: FridgeDeduction[]
total_calories: number
total_protein_g: number
total_carbs_g: number
total_fat_g: number
meal_id?: number
items: FridgeItemInfo[]
message: string
  }> {
    return request<any>(`${API_BASE}/fridge/recipes/confirm`, {
      method: 'POST',
      body: JSON.stringify({ recipe }),
    })
  },
}

// ============================================
//  活动模块 API
// ============================================

/** 活动（含实时加入人数） */
export interface ActivityInfo {
  id: number
  title: string
  sport_type: string
  city: string
  district: string
  location: string
  start_time: string | null
  max_participants: number
  description: string
  creator_id: string
  status: 'open' | 'full' | 'closed' | 'finished'
  group_id: number | null
  created_at: string | null
}

export interface ActivityListItem {
  activity: ActivityInfo
  member_count: number
}

export interface ActivityMyItem extends ActivityListItem {
  role: 'owner' | 'member'
}

export interface ActivityDetail {
  activity: ActivityInfo
  member_count: number
  my_role: 'owner' | 'member' | null
  is_creator: boolean
}

export interface ActivityMemberInfo {
  id: number
  activity_id: number
  user_id: string
  role: 'owner' | 'member'
  nickname: string
  joined_at: string | null
}

export interface ActivityGroupInfo {
  id: number
  activity_id: number
  group_name: string
  announcement: string
  created_at: string | null
}

export interface ActivityMessageInfo {
  id: number
  group_id: number
  sender_id: string
  sender_nickname: string
  content: string
  created_at: string | null
}

export interface CreateActivityData {
  title: string
  sport_type: string
  city: string
  district?: string
  location?: string
  start_time: string
  max_participants: number
  description?: string
}

export const activityApi = {
  /** 创建活动（自动建群） */
  async create(data: CreateActivityData): Promise<{ success: boolean; activity: ActivityInfo; group_id: number; message: string }> {
    return request<any>(`${API_BASE}/activities`, {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },

  /** 活动列表（城市/行政区/运动类型/关键词筛选） */
  async list(params: {
    city?: string
    district?: string
    sport_type?: string
    keyword?: string
    status?: string
    only_mine?: boolean
    limit?: number
    offset?: number
  } = {}): Promise<{ activities: ActivityInfo[]; member_counts: number[]; count: number }> {
    const query = buildQuery(params)
    return request<any>(`${API_BASE}/activities${query}`)
  },

  /** 我加入/发起的活动 */
  async mine(): Promise<{ activities: ActivityInfo[]; roles: string[]; member_counts: number[]; count: number }> {
    return request<any>(`${API_BASE}/activities/mine`)
  },

  /** 运动类型枚举 */
  async sportTypes(): Promise<{ sport_types: string[] }> {
    return request<any>(`${API_BASE}/activities/sport-types`)
  },

  /** 有活动的城市列表 */
  async cities(): Promise<{ cities: string[] }> {
    return request<any>(`${API_BASE}/activities/cities`)
  },

  /** 行政区列表（按城市） */
  async districts(city?: string): Promise<{ districts: string[] }> {
    const query = buildQuery({ city })
    return request<any>(`${API_BASE}/activities/districts${query}`)
  },

  /** 活动详情 */
  async detail(activityId: number): Promise<ActivityDetail> {
    return request<any>(`${API_BASE}/activities/${activityId}`)
  },

  /** 修改活动（仅发起者） */
  async update(activityId: number, data: Partial<CreateActivityData> & { status?: string }): Promise<{ success: boolean; activity: ActivityInfo }> {
    return request<any>(`${API_BASE}/activities/${activityId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    })
  },

  /** 解散活动（仅发起者） */
  async remove(activityId: number): Promise<{ success: boolean; message: string }> {
    return request<any>(`${API_BASE}/activities/${activityId}`, { method: 'DELETE' })
  },

  /** 加入活动（自动加入群聊） */
  async join(activityId: number): Promise<{ success: boolean; group_id: number; member_count: number; message: string }> {
    return request<any>(`${API_BASE}/activities/${activityId}/join`, { method: 'POST' })
  },

  /** 退出活动 */
  async leave(activityId: number): Promise<{ success: boolean; message: string }> {
    return request<any>(`${API_BASE}/activities/${activityId}/leave`, { method: 'POST' })
  },

  /** 成员列表 */
  async members(activityId: number): Promise<{ members: ActivityMemberInfo[]; count: number; my_role: string }> {
    return request<any>(`${API_BASE}/activities/${activityId}/members`)
  },

  /** 移除成员（仅发起者） */
  async removeMember(activityId: number, userId: string): Promise<{ success: boolean; message: string }> {
    return request<any>(`${API_BASE}/activities/${activityId}/members/${encodeURIComponent(userId)}`, { method: 'DELETE' })
  },

  /** 群聊信息 */
  async group(activityId: number): Promise<{ group: ActivityGroupInfo; my_role: string; member_count: number }> {
    return request<any>(`${API_BASE}/activities/${activityId}/group`)
  },

  /** 修改群信息（仅发起者） */
  async updateGroup(activityId: number, data: { group_name?: string; announcement?: string }): Promise<{ success: boolean; group: ActivityGroupInfo }> {
    return request<any>(`${API_BASE}/activities/${activityId}/group`, {
      method: 'PUT',
      body: JSON.stringify(data),
    })
  },

  /** 拉取群聊消息（before_id 向前翻页） */
  async messages(activityId: number, beforeId?: number, limit: number = 50): Promise<{ group_id: number; messages: ActivityMessageInfo[]; count: number }> {
    const query = buildQuery({ before_id: beforeId, limit })
    return request<any>(`${API_BASE}/activities/${activityId}/messages${query}`)
  },

  /** 发送群聊消息（仅成员） */
  async sendMessage(activityId: number, content: string): Promise<{ success: boolean; message: ActivityMessageInfo }> {
    return request<any>(`${API_BASE}/activities/${activityId}/messages`, {
      method: 'POST',
      body: JSON.stringify({ content }),
    })
  },
}

// —— 工具函数 ——

/** 将 File 转为 Base64 */
export function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const result = reader.result as string
      // 去掉 data:image/xxx;base64, 前缀
      resolve(result.split(',')[1])
    }
    reader.onerror = reject
    reader.readAsDataURL(file)
  })
}

