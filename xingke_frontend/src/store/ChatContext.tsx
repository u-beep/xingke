import { createContext, useContext, useState, useRef, useCallback, useEffect, type ReactNode } from 'react'
import { chatApi, toolsApi, visionApi, fileToBase64, dietApi, waterApi, type WaterSummary } from '../services/api'

// —— 类型 ——

export interface Message {
  id: string
  role: 'ai' | 'user'
  type: 'text' | 'card' | 'recipe'
  content: string
  timestamp: string
  cardData?: any
  dietData?: { foods: any[]; total_calories: number } | null
  waterData?: { amount_ml: number; drink_type: string; description: string } | null
}

interface ChatContextValue {
  // 状态
  messages: Message[]
  sessionId: string | null
  typing: boolean
  loading: boolean
  currentDate: string  // 当前查看的日期 YYYY-MM-DD
  calorieSummary: CalorieSummary  // 当日热量统计
  waterSummary: WaterSummary  // 当日饮水统计（驱动水杯水位动画）
  // 动作
  sendChatMessage: (text: string) => Promise<void>
  recognizeFoodImage: (file: File) => Promise<void>
  generateRecipe: (days: 1 | 7) => Promise<void>
  clearChat: () => Promise<void>
  loadSessionByDate: (date: string) => Promise<void>
  confirmDiet: (msgId: string, foods: any[]) => Promise<void>
  dismissDiet: (msgId: string) => void
  confirmWater: (msgId: string, amount_ml: number, drink_type?: string, notes?: string) => Promise<void>
  dismissWater: (msgId: string) => void
}

interface CalorieSummary {
  total_calories: number
  total_protein_g: number
  total_carbs_g: number
  total_fat_g: number
  record_count: number
  budget: number
  remaining: number
}

const ChatContext = createContext<ChatContextValue | null>(null)

const USER_ID = 'user_web_001'

/** 过滤掉自动问候消息及其对应的 AI 回复 */
function filterGreetingMessages(history: any[]): any[] {
  // 找到问候消息的索引集合，连同紧跟其后的 assistant 回复一起排除
  const excludeIndices = new Set<number>()
  for (let i = 0; i < history.length; i++) {
    const msg = history[i]
    if (msg.role === 'user' && msg.content === '请给我一个早间问候和今日健康简报') {
      excludeIndices.add(i)
      // 排除紧跟其后的 assistant 回复
      if (i + 1 < history.length && history[i + 1].role === 'assistant') {
        excludeIndices.add(i + 1)
      }
    }
  }
  return history.filter((_, idx) => !excludeIndices.has(idx))
}

function nowTime() {
  return new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

let msgIdCounter = 0
function nextId() {
  msgIdCounter += 1
  return `${Date.now()}_${msgIdCounter}`
}

export function ChatProvider({ children }: { children: ReactNode }) {
  const [messages, setMessages] = useState<Message[]>([])
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [typing, setTyping] = useState(false)
  const [loading, setLoading] = useState(false)
  const [currentDate, setCurrentDate] = useState<string>(() => {
    const d = new Date()
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  })
  const [calorieSummary, setCalorieSummary] = useState<CalorieSummary>({
    total_calories: 0,
    total_protein_g: 0,
    total_carbs_g: 0,
    total_fat_g: 0,
    record_count: 0,
    budget: 1600,
    remaining: 1600,
  })
  const [waterSummary, setWaterSummary] = useState<WaterSummary>({
    total_ml: 0,
    record_count: 0,
    goal_ml: 2000,
    remaining_ml: 2000,
    percentage: 0,
    type_breakdown: {},
  })
  // 防止重复发送问候
  const greetedRef = useRef(false)
  // 防止重复加载当天会话
  const loadedTodayRef = useRef(false)
  // 当天会话加载 Promise
  const loadTodayPromiseRef = useRef<Promise<boolean> | null>(null)

  /** 初始化：拉取当天会话历史，返回是否有历史消息 */
  const loadTodaySession = useCallback((): Promise<boolean> => {
    if (loadTodayPromiseRef.current) return loadTodayPromiseRef.current

    loadTodayPromiseRef.current = (async () => {
      if (loadedTodayRef.current) return false
      loadedTodayRef.current = true

      try {
        const result = await chatApi.getTodaySession(USER_ID)
        if (result.session_id) {
          setSessionId(result.session_id)
        }
        // 将服务端历史消息转换为前端 Message 格式
        if (result.history && result.history.length > 0) {
          const restoredMessages: Message[] = filterGreetingMessages(result.history)
            .filter((msg: any) => msg.role === 'user' || msg.role === 'assistant')
            .map((msg: any) => ({
              id: `restored_${Date.now()}_${Math.random().toString(36).slice(2)}`,
              role: msg.role === 'assistant' ? 'ai' : 'user',
              type: 'text' as const,
              content: msg.content || '',
              timestamp: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
            }))
          if (restoredMessages.length > 0) {
            setMessages(restoredMessages)
            // 已有历史记录，标记已问候，不再发送问候
            greetedRef.current = true
            return true
          }
        }
        return false
      } catch {
        // 拉取失败，静默处理
        loadedTodayRef.current = false
        loadTodayPromiseRef.current = null
        return false
      }
    })()

    return loadTodayPromiseRef.current
  }, [])

  /** 加载指定日期的热量统计 */
  const loadCalorieSummary = useCallback(async (date: string) => {
    try {
      const result = await dietApi.summary(USER_ID, date)
      const intake = result.total_calories || 0
      const budget = 1600
      setCalorieSummary({
        total_calories: intake,
        total_protein_g: result.total_protein_g || 0,
        total_carbs_g: result.total_carbs_g || 0,
        total_fat_g: result.total_fat_g || 0,
        record_count: result.record_count || 0,
        budget,
        remaining: Math.max(0, budget - intake),
      })
    } catch {
      // 静默失败
    }
  }, [])

  /** 加载指定日期的饮水统计（驱动水杯水位动画） */
  const loadWaterSummary = useCallback(async (date: string) => {
    try {
      const result = await waterApi.summary(USER_ID, date)
      setWaterSummary({
        total_ml: result.total_ml || 0,
        record_count: result.record_count || 0,
        goal_ml: result.goal_ml || 2000,
        remaining_ml: result.remaining_ml ?? (result.goal_ml || 2000) - (result.total_ml || 0),
        percentage: result.percentage || 0,
        type_breakdown: result.type_breakdown || {},
      })
    } catch {
      // 静默失败
    }
  }, [])

  // 组件挂载时拉取当天会话、热量统计、饮水统计
  useEffect(() => {
    loadTodaySession()
    const d = new Date()
    const todayStr = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
    loadCalorieSummary(todayStr)
    loadWaterSummary(todayStr)
  }, [loadTodaySession, loadCalorieSummary, loadWaterSummary])

  /** 发送当日问候 — 已禁用，不再自动发问候 */
  const sendGreeting = useCallback(async () => {
    // 不做任何事，保留函数签名兼容
  }, [])

  /** 核心：先入库用户消息，再调用流式对话API */
  const sendChatMessage = useCallback(async (text: string) => {
    // 如果正在处理中，禁止发送新消息
    if (typing || loading) return

    const userMsg: Message = {
      id: nextId(),
      role: 'user',
      type: 'text',
      content: text,
      timestamp: nowTime(),
    }
    setMessages((prev) => [...prev, userMsg])
    setTyping(true)
    setLoading(true)

    // 创建 AI 消息占位（content='' 时 MessageBubble 会显示 typing 三点动画）
    const aiId = nextId()
    setMessages((prev) => [...prev, {
      id: aiId,
      role: 'ai',
      type: 'text',
      content: '',
      timestamp: nowTime(),
    }])

    // 轮询模式：POST /chat/start 立即返回 task_id（后端后台跑 AgentLoop），
    // 然后定时 GET /chat/poll 取结果，避免 SSE 长连接在后端慢响应时被超时 abort。
    let accumulated = ''
    let currentSessionId = sessionId
    const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))
    try {
      // ① 发起异步对话（后端立即入库用户消息 + 启动后台线程跑 AgentLoop）
      const startResp = await chatApi.start({
        message: text,
        session_id: currentSessionId,
        user_id: USER_ID,
      })
      const taskId = startResp.task_id
      if (startResp.session_id) {
        currentSessionId = startResp.session_id
        setSessionId(currentSessionId)
      }

      // ② 轮询结果（间隔 1.5s，最多 120 次 = 180s，覆盖后端模型降级慢响应场景）
      const POLL_INTERVAL_MS = 1500
      const MAX_POLL_COUNT = 120
      let result = ''
      let pollError: string | null = null
      for (let i = 0; i < MAX_POLL_COUNT; i++) {
        await sleep(POLL_INTERVAL_MS)
        const pollResp = await chatApi.poll(taskId)
        if (pollResp.session_id) setSessionId(pollResp.session_id)
        if (pollResp.status === 'done') {
          result = pollResp.result || ''
          break
        }
        if (pollResp.status === 'error' || pollResp.status === 'unknown') {
          pollError = pollResp.error || 'AI 服务异常，请稍后重试'
          break
        }
        // status === 'running'：继续轮询，UI 已显示 typing 动画
      }
      if (!result && !pollError) {
        pollError = 'AI 响应超时，请稍后重试'
      }

      if (pollError) {
        accumulated = pollError
        setMessages((prev) => prev.map((m) => (m.id === aiId ? { ...m, content: accumulated } : m)))
      } else {
        // ③ 拿到完整 result 后，逐字动画显示（模拟流式打字机效果，UX 更自然）
        const chunkSize = 3
        for (let i = 0; i < result.length; i += chunkSize) {
          accumulated += result.slice(i, i + chunkSize)
          setMessages((prev) => prev.map((m) => (m.id === aiId ? { ...m, content: accumulated } : m)))
          // 短暂延迟，让用户看到逐字显示；末尾段稍快避免拖沓
          await sleep(i < result.length - chunkSize * 5 ? 25 : 12)
        }
        accumulated = result
      }
    } catch (err) {
      console.error('[sendChatMessage] 轮询对话失败:', err)
      accumulated = '抱歉，暂时无法连接到AI服务，请稍后再试。'
      setMessages((prev) => prev.map((m) => (m.id === aiId ? { ...m, content: accumulated } : m)))
    }

    // 解析 [DIET_DATA] 标记，提取食物数据供前端展示确认按钮
    let dietData: Message['dietData'] = null
    const dietMatch = accumulated.match(/\[DIET_DATA\](.+?)\[\/DIET_DATA\]/s)
    if (dietMatch) {
      try {
        dietData = JSON.parse(dietMatch[1])
        // 从回复中移除标记
        accumulated = accumulated.replace(/\[DIET_DATA\].+?\[\/DIET_DATA\]/s, '').trim()
        setMessages((prev) => {
          const updated = [...prev]
          const target = updated.find((m) => m.id === aiId)
          if (target) {
            target.content = accumulated
            target.dietData = dietData
          }
          return [...updated]
        })
      } catch {
        // JSON 解析失败，忽略
      }
    }

    // 解析 [WATER_DATA] 标记，提取饮水量数据供前端展示确认按钮
    let waterData: Message['waterData'] = null
    const waterMatch = accumulated.match(/\[WATER_DATA\](.+?)\[\/WATER_DATA\]/s)
    if (waterMatch) {
      try {
        const parsed = JSON.parse(waterMatch[1])
        if (parsed && typeof parsed.amount_ml === 'number' && parsed.amount_ml > 0) {
          waterData = {
            amount_ml: parsed.amount_ml,
            drink_type: parsed.drink_type || 'water',
            description: parsed.description || `${parsed.amount_ml}ml`,
          }
          // 从回复中移除标记
          accumulated = accumulated.replace(/\[WATER_DATA\].+?\[\/WATER_DATA\]/s, '').trim()
          setMessages((prev) => {
            const updated = [...prev]
            const target = updated.find((m) => m.id === aiId)
            if (target) {
              target.content = accumulated
              target.waterData = waterData
            }
            return [...updated]
          })
        }
      } catch {
        // JSON 解析失败，忽略
      }
    }

    setTyping(false)
    setLoading(false)
    // 对话完成后刷新热量统计与饮水统计（后端可能自动提取了饮食/饮水记录）
    const d = new Date()
    const todayStr = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
    loadCalorieSummary(todayStr)
    loadWaterSummary(todayStr)
  }, [sessionId, loadCalorieSummary, loadWaterSummary])

  /** 食物图片识别 */
  const recognizeFoodImage = useCallback(async (file: File) => {
    const userMsg: Message = {
      id: nextId(),
      role: 'user',
      type: 'text',
      content: '（已上传食物图片，正在识别...）',
      timestamp: nowTime(),
    }
    setMessages((prev) => [...prev, userMsg])
    setTyping(true)
    setLoading(true)

    const aiId = nextId()
    setMessages((prev) => [...prev, {
      id: aiId,
      role: 'ai',
      type: 'text',
      content: '',
      timestamp: nowTime(),
    }])

    try {
      const base64 = await fileToBase64(file)
      const result = await visionApi.recognizeFood({
        image_base64: base64,
        user_id: USER_ID,
      })
      const text = typeof result === 'string'
        ? result
        : (result.content || result.response || JSON.stringify(result, null, 2))
      setMessages((prev) => {
        const updated = [...prev]
        const target = updated.find((m) => m.id === aiId)
        if (target) target.content = text
        return [...updated]
      })
    } catch {
      setMessages((prev) => {
        const updated = [...prev]
        const target = updated.find((m) => m.id === aiId)
        if (target) target.content = '抱歉，图片识别服务暂时不可用，请稍后再试或使用文字描述食物。'
        return [...updated]
      })
    } finally {
      setTyping(false)
      setLoading(false)
    }
  }, [])

  /** 生成食谱 */
  const generateRecipe = useCallback(async (days: 1 | 7) => {
    setTyping(true)
    setLoading(true)

    const aiId = nextId()
    setMessages((prev) => [...prev, {
      id: aiId,
      role: 'ai',
      type: 'text',
      content: '正在为你生成个性化食谱，请稍候...',
      timestamp: nowTime(),
    }])

    try {
      const result = await toolsApi.generateDietPlan({
        gender: 'male',
        age: 28,
        weight: 71.5,
        height: 175,
        activity_level: 'moderate',
        target_deficit: 500,
        meals_per_day: 3,
        days: days,
        user_id: USER_ID,
      })
      const text = typeof result === 'string'
        ? result
        : (result.content || result.response || JSON.stringify(result, null, 2))
      setMessages((prev) => {
        const updated = [...prev]
        const target = updated.find((m) => m.id === aiId)
        if (target) {
          target.content = text
          target.type = 'recipe'
        }
        return [...updated]
      })
    } catch {
      setMessages((prev) => {
        const updated = [...prev]
        const target = updated.find((m) => m.id === aiId)
        if (target) target.content = '食谱生成服务暂时不可用，请稍后再试。'
        return [...updated]
      })
    } finally {
      setTyping(false)
      setLoading(false)
    }
  }, [])

  /** 清空对话 */
  const clearChat = useCallback(async () => {
    if (sessionId) {
      try {
        await chatApi.clearSession(sessionId)
      } catch {
        // 静默失败
      }
    }
    setSessionId(null)
    setMessages([])
    greetedRef.current = false
    loadedTodayRef.current = false
    loadTodayPromiseRef.current = null
    // 重新拉取当天会话（已清空历史，会创建新会话）
    await loadTodaySession()
    // 不自动发问候，保持空对话
  }, [sessionId, sendGreeting, loadTodaySession])

  /** 按日期加载会话历史 */
  const loadSessionByDate = useCallback(async (date: string) => {
    // 如果切换到今天，强制重新加载
    const d = new Date()
    const today = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
    if (date === today) {
      // 重置状态，强制重新加载今天（不依赖 loadedTodayRef 缓存）
      greetedRef.current = false
      loadedTodayRef.current = false
      loadTodayPromiseRef.current = null
      setMessages([])
      setCurrentDate(date)
      // 同步加载当天热量统计
      loadCalorieSummary(date)
      // 直接调用 API 加载今天会话，不走 loadTodaySession 的缓存逻辑
      try {
        const result = await chatApi.getTodaySession(USER_ID)
        if (result.session_id) {
          setSessionId(result.session_id)
        }
        if (result.history && result.history.length > 0) {
          const restoredMessages: Message[] = filterGreetingMessages(result.history)
            .filter((msg: any) => msg.role === 'user' || msg.role === 'assistant')
            .map((msg: any) => ({
              id: `restored_${Date.now()}_${Math.random().toString(36).slice(2)}`,
              role: msg.role === 'assistant' ? 'ai' : 'user',
              type: 'text' as const,
              content: msg.content || '',
              timestamp: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
            }))
          setMessages(restoredMessages)
          greetedRef.current = true
          return
        }
      } catch {
        // 静默失败，继续发问候
      }
      // 今天没有历史记录，保持空对话（不发问候）
      return
    }

    // 加载指定日期的历史会话（接口已返回合并后的完整历史）
    setTyping(true)
    setLoading(true)
    setMessages([])
    setCurrentDate(date)
    greetedRef.current = true  // 历史日期不发问候
    // 同步加载该日期的热量统计
    loadCalorieSummary(date)

    try {
      const result = await chatApi.listSessionsByDate(USER_ID, date)
      if (result.history && result.history.length > 0) {
        const restoredMessages: Message[] = filterGreetingMessages(result.history)
          .filter((msg: any) => msg.role === 'user' || msg.role === 'assistant')
          .map((msg: any) => ({
            id: `hist_${Date.now()}_${Math.random().toString(36).slice(2)}`,
            role: msg.role === 'assistant' ? 'ai' : 'user',
            type: 'text' as const,
            content: msg.content || '',
            timestamp: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
          }))
        setMessages(restoredMessages)
        setSessionId(result.session_id || null)
      } else {
        setMessages([{
          id: nextId(),
          role: 'ai',
          type: 'text',
          content: `${date} 当天没有对话记录。`,
          timestamp: nowTime(),
        }])
        setSessionId(null)
      }
    } catch {
      setMessages([{
        id: nextId(),
        role: 'ai',
        type: 'text',
        content: `加载 ${date} 的对话记录失败，请稍后再试。`,
        timestamp: nowTime(),
      }])
    } finally {
      setTyping(false)
      setLoading(false)
    }
  }, [loadTodaySession, sendGreeting])

  /** 确认计入热量统计 */
  const confirmDiet = useCallback(async (msgId: string, foods: any[]) => {
    try {
      await dietApi.confirm(USER_ID, foods)
      // 刷新热量统计
      const d = new Date()
      loadCalorieSummary(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`)
      // 清除该消息的 dietData（已确认）— 不可变更新，避免 mutation 触发渲染异常
      setMessages((prev) => prev.map((m) => (m.id === msgId ? { ...m, dietData: null } : m)))
    } catch (err) {
      // 保存失败时提示用户，避免静默丢失
      console.error('[confirmDiet] 保存饮食记录失败:', err)
      alert('保存到今日热量失败，请稍后重试')
    }
  }, [loadCalorieSummary])

  /** 忽略饮食确认 */
  const dismissDiet = useCallback((msgId: string) => {
    setMessages((prev) => prev.map((m) => (m.id === msgId ? { ...m, dietData: null } : m)))
  }, [])

  /** 确认计入今日饮水总量（用户在前端确认 AI 提取的饮水量） */
  const confirmWater = useCallback(async (msgId: string, amount_ml: number, drink_type: string = 'water', notes?: string) => {
    try {
      await waterApi.confirm(USER_ID, amount_ml, drink_type, notes)
      // 刷新今日饮水统计（驱动水杯水位上涨动画）
      const d = new Date()
      loadWaterSummary(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`)
      // 清除该消息的 waterData（已确认）— 不可变更新，避免 mutation 触发渲染异常
      setMessages((prev) => prev.map((m) => (m.id === msgId ? { ...m, waterData: null } : m)))
    } catch (err) {
      // 保存失败时提示用户，避免静默丢失
      console.error('[confirmWater] 保存饮水记录失败:', err)
      alert('保存到今日饮水失败，请稍后重试')
    }
  }, [loadWaterSummary])

  /** 忽略饮水确认 */
  const dismissWater = useCallback((msgId: string) => {
    setMessages((prev) => prev.map((m) => (m.id === msgId ? { ...m, waterData: null } : m)))
  }, [])

  return (
    <ChatContext.Provider value={{
      messages,
      sessionId,
      typing,
      loading,
      currentDate,
      calorieSummary,
      waterSummary,
      sendChatMessage,
      recognizeFoodImage,
      generateRecipe,
        clearChat,
        loadSessionByDate,
        confirmDiet,
        dismissDiet,
        confirmWater,
        dismissWater,
      }}>
      {children}
    </ChatContext.Provider>
  )
}

/** 获取 ChatContext */
export function useChat() {
  const ctx = useContext(ChatContext)
  if (!ctx) {
    throw new Error('useChat 必须在 ChatProvider 内部使用')
  }
  return ctx
}
