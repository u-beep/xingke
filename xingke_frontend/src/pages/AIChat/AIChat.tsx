import { useState, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { getCurrentUserId } from '../../services/authStore'
import {
Flag,
Trash2,
Send,
Plus,
Camera,
Scale,
Copy,
  ThumbsUp,
  ThumbsDown,
  ChevronLeft,
  PanelRightClose,
  PanelRightOpen,
  Flame,
  Check,
  TrendingDown,
  X,
  Loader2,
  Square,
  Calendar,
  Dumbbell,
  Plus as PlusIcon,
  Trash,
  Droplets,
  Pencil,
} from 'lucide-react'
import { mockGoalProgress } from '../../data/mockData'
import { useChat } from '../../store/ChatContext'
import { exerciseApi, exercisePlanApi, workoutApi, profileApi, waterApi, dietApi, weightApi, type ExerciseCalorieGroup, type WorkoutTemplateInfo, type ExerciseRecordInfo, type PlanSummary } from '../../services/api'
import CalendarPanel from '../../components/CalendarPanel/CalendarPanel'
import './AIChat.css'

// ============================================
//  右侧信息栏卡片注册表（用户可自定义增删）
// ============================================
const PANEL_CARDS = [
  { id: 'calorie', label: '今日热量' },
  { id: 'water', label: '今日饮水' },
  { id: 'plan', label: '运动计划' },
  { id: 'burn', label: '运动热量消耗' },
  { id: 'gap', label: '热量缺口' },
  { id: 'goal', label: '目标进度' },
]
const ALL_CARD_IDS = PANEL_CARDS.map((c) => c.id)

// 饮品类型英文 -> 中文
const DRINK_TYPE_LABEL: Record<string, string> = {
water: '水',
tea: '茶',
coffee: '咖啡',
milk: '牛奶',
juice: '果汁',
soda: '碳酸饮料',
soup: '汤',
other: '其他',
}

/** Date → 本地时区 YYYY-MM-DD */
function isoOf(d: Date): string {
return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/** 体重建议：把输入值视作当天新记录，与最近一次记录和本周趋势对比，实时生成反馈文案 */
function buildWeightAdvice(
input: string,
info: { current: number | null; target: number | null; weekPoints: Array<{ iso: string; weight: number }> },
): string {
const n = parseFloat(input)
if (isNaN(n) || n <= 0) return '输入体重后，这里将结合本周变化实时给出建议'
const tips: string[] = []
const last = info.weekPoints.length ? info.weekPoints[info.weekPoints.length - 1].weight : info.current
if (last != null) {
const diff = +(n - last).toFixed(1)
if (Math.abs(diff) < 0.1) tips.push('与最近一次记录基本持平')
else if (diff < 0) tips.push(`较最近一次记录下降 ${Math.abs(diff)}kg`)
else tips.push(`较最近一次记录上升 ${diff}kg`)
}
const wp = info.weekPoints
if (wp.length >= 2) {
const weekDiff = +(n - wp[0].weight).toFixed(1)
if (weekDiff <= -0.2) tips.push(`本周累计下降 ${Math.abs(weekDiff)}kg，趋势良好，保持当前节奏`)
else if (weekDiff >= 0.2) tips.push(`本周累计上升 ${weekDiff}kg，建议留意饮食与运动平衡`)
else tips.push('本周体重整体稳定')
} else if (last != null) {
tips.push('坚持每天记录，就能看到完整趋势')
}
if (info.target != null) {
const toTarget = +(n - info.target).toFixed(1)
if (Math.abs(toTarget) <= 0.2) tips.push('已达成目标体重，可转入维持期')
else if (toTarget > 0) tips.push(`距目标体重还差 ${toTarget}kg，继续加油`)
else tips.push(`已低于目标 ${Math.abs(toTarget)}kg，注意别减过头`)
}
return tips.join('；')
}

/** 按用户隔离持久化卡片展示配置 */
function panelCardsStorageKey(): string {
  return `xingke_panel_cards_${getCurrentUserId()}`
}

function loadVisibleCards(): string[] {
  try {
    const raw = localStorage.getItem(panelCardsStorageKey())
    if (raw) {
      const saved = JSON.parse(raw) as string[]
      const valid = ALL_CARD_IDS.filter((id) => saved.includes(id))
      if (valid.length > 0) return valid
    }
  } catch {
    // 解析失败忽略，回退全量展示
  }
  return [...ALL_CARD_IDS]
}

interface Message {
  id: string
  role: 'ai' | 'user'
  type: 'text' | 'card' | 'recipe'
  content: string
  timestamp: string
  cardData?: any
  dietData?: { foods: any[]; total_calories: number } | null
  waterData?: { amount_ml: number; drink_type: string; description: string } | null
  /** 图片消息预览（dataURL，仅前端展示） */
  imageUrl?: string
}

export default function AIChat() {
  const navigate = useNavigate()
  // 从全局 Context 获取持久化状态（切换 tab 不会丢失）
  const {
    messages,
    sessionId,
    typing,
    loading,
    currentDate,
    calorieSummary,
    waterSummary,
    sendChatMessage,
    recognizeFoodImage,
    clearChat,
    loadSessionByDate,
    confirmDiet,
    dismissDiet,
    confirmWater,
    dismissWater,
    stopGeneration,
    refreshSummaries,
  } = useChat()

  // 仅本页的 UI 局部状态
  const [input, setInput] = useState('')
const [showWeightModal, setShowWeightModal] = useState(false)
const [showConfirmClear, setShowConfirmClear] = useState(false)
  const [rightPanelVisible, setRightPanelVisible] = useState(true)
const [visibleCards, setVisibleCards] = useState<string[]>(loadVisibleCards)
const [showCardPicker, setShowCardPicker] = useState(false)
  const [calendarVisible, setCalendarVisible] = useState(false)
  const [weightInput, setWeightInput] = useState('')
const [savingWeight, setSavingWeight] = useState(false)
// 体重信息（当前/起始/目标/近 7 天记录点），驱动目标进度卡与弹窗实时建议
const [bodyInfo, setBodyInfo] = useState<{
current: number | null
target: number | null
start: number | null
weekPoints: Array<{ iso: string; weight: number }>
}>({ current: null, target: null, start: null, weekPoints: [] })
    // 运动计划状态
  const [exerciseGroup, setExerciseGroup] = useState<ExerciseCalorieGroup | null>(null)
  const [planSummary, setPlanSummary] = useState<PlanSummary>({
    total_calories: 0,
    total_duration: 0,
    completed_count: 0,
    planned_calories: 0,
    planned_duration: 0,
    item_count: 0,
    items: [],
  })
  const [exerciseRecords, setExerciseRecords] = useState<ExerciseRecordInfo[]>([])
  const [exercisePanelTab, setExercisePanelTab] = useState<'plan' | 'history'>('plan')
  const [confirmingPlanItem, setConfirmingPlanItem] = useState<PlanSummary['items'][number] | null>(null)
  const [completingPlanItemId, setCompletingPlanItemId] = useState<number | null>(null)
  const [selectedType, setSelectedType] = useState<string>('cardio')
  const [selectedExercise, setSelectedExercise] = useState<string>('')
  const [duration, setDuration] = useState<number>(30)
const [templates, setTemplates] = useState<WorkoutTemplateInfo[]>([])
const [showSaveTemplate, setShowSaveTemplate] = useState(false)
const [templateName, setTemplateName] = useState('')
// 目标行内编辑：'protein'/'carbs'/'fat' = 三大营养素目标，'water' = 饮水目标，'waterIntake' = 饮水已摄入
const [editingGoal, setEditingGoal] = useState<'protein' | 'carbs' | 'fat' | 'water' | 'waterIntake' | null>(null)
const [goalInput, setGoalInput] = useState('')
const [savingGoal, setSavingGoal] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const now = new Date()
  const todayStr = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
  const isViewingHistory = currentDate !== todayStr

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

// 每次进入页面时刷新热量/饮水统计（Context 数据可能因其他页面的增删改而过期）
useEffect(() => {
refreshSummaries()
fetchBodyInfo()
// eslint-disable-next-line react-hooks/exhaustive-deps
}, [])

  // 加载运动列表和今日计划
  useEffect(() => {
    const loadExerciseData = async () => {
      try {
        const groups = await workoutApi.exercises()
        setExerciseGroup(groups)
        if (groups.cardio.length > 0) {
          setSelectedExercise(groups.cardio[0].exercise_name)
        }
      } catch {
        // 静默失败
      }
    }
    loadExerciseData()
    // 加载模板列表
    workoutApi.listTemplates(getCurrentUserId()).then(res => setTemplates(res.templates || [])).catch(() => {})
  }, [])

/** 切换右侧信息栏卡片展示状态（持久化到 localStorage） */
const togglePanelCard = (id: string) => {
  setVisibleCards((prev) => {
    const next = prev.includes(id)
      ? prev.filter((c) => c !== id)
      : ALL_CARD_IDS.filter((c) => prev.includes(c) || c === id)
    try {
      localStorage.setItem(panelCardsStorageKey(), JSON.stringify(next))
    } catch {
      // 存储不可用忽略
    }
    return next
  })
}

// 加载今日运动计划
const loadExercisePlan = async (date?: string) => {
    try {
      const summary = date
        ? await exercisePlanApi.byDate(getCurrentUserId(), date)
        : await exercisePlanApi.today(getCurrentUserId())
      setPlanSummary({
        ...summary,
        total_calories: summary.total_calories || 0,
        total_duration: summary.total_duration || 0,
        completed_count: summary.completed_count || 0,
        planned_calories: summary.planned_calories || 0,
        planned_duration: summary.planned_duration || 0,
        item_count: summary.item_count || 0,
        items: summary.items || [],
      })
    } catch {
      // 静默失败
    }
  }

  const loadExerciseRecords = async () => {
    try {
      const result = await exerciseApi.history()
      setExerciseRecords(result.records || [])
    } catch {
      // 静默失败
    }
  }

  useEffect(() => {
    loadExercisePlan(isViewingHistory ? currentDate : undefined)
    loadExerciseRecords()
  }, [currentDate])

  // 运动类型中文映射
  const typeLabels: Record<string, string> = { cardio: '有氧运动', strength: '力量训练', anaerobic: '无氧运动' }
  const typeColors: Record<string, string> = { cardio: '#5b9bd5', strength: '#e8746b', anaerobic: '#f0a732' }

// 计算热量缺口 = 摄入热量 - (BMR + 运动消耗)
const bmr = 1674 // 基础代谢率（根据用户数据计算）
const exerciseCalories = planSummary.total_calories
const intakeCalories = calorieSummary.total_calories
const totalBurn = bmr + exerciseCalories
const calorieGap = Math.round(totalBurn - intakeCalories)

// —— 目标进度卡（真实数据，无数据时回退 mock）——
const goalPct = (() => {
const { current, target, start } = bodyInfo
if (!current || !target) return mockGoalProgress.percentage
if (start == null || start === target) return 0
const pct = Math.round(((start - current) / (start - target)) * 100)
return Math.max(0, Math.min(100, pct))
})()
const goalWeeklyChange = bodyInfo.weekPoints.length >= 2
? +(bodyInfo.weekPoints[bodyInfo.weekPoints.length - 1].weight - bodyInfo.weekPoints[0].weight).toFixed(1)
: null

// 弹窗内实时建议：把输入值视作当天新记录，与最近一次记录和本周趋势对比
const weightAdvice = buildWeightAdvice(weightInput, bodyInfo)

  // 运动消耗完成度：已完成消耗相对计划预计的比例。
  const exerciseBurnPercent = planSummary.planned_calories > 0
    ? Math.min(100, Math.round((exerciseCalories / planSummary.planned_calories) * 100))
    : exerciseCalories > 0
      ? 100
      : 0

  const handleAddExercise = async () => {
    if (!selectedExercise) return
    try {
      await exercisePlanApi.add({
        exercise_type: selectedType,
        exercise_name: selectedExercise,
        duration_min: duration,
      })
      await loadExercisePlan(isViewingHistory ? currentDate : undefined)
    } catch {
      // 静默失败
    }
  }

  const handleApplyTemplate = async (templateId: number) => {
    try {
      await workoutApi.applyTemplate(templateId)
      await loadExercisePlan(isViewingHistory ? currentDate : undefined)
    } catch {
      // 静默失败
    }
  }

  const handleDeleteTemplate = async (templateId: number) => {
    try {
      await workoutApi.deleteTemplate(templateId)
      const res = await workoutApi.listTemplates(getCurrentUserId())
      setTemplates(res.templates || [])
    } catch {
      // 静默失败
    }
  }

  const handleSaveTemplate = async () => {
    if (!templateName.trim() || planSummary.items.length === 0) return
    try {
      const items = planSummary.items.map(i => ({
        exercise_name: i.exercise_name,
        exercise_type: i.exercise_type,
        duration_min: i.duration_min,
      }))
      await workoutApi.createTemplate({
        template_name: templateName.trim(),
        items,
      })
      setTemplateName('')
      setShowSaveTemplate(false)
      const res = await workoutApi.listTemplates(getCurrentUserId())
      setTemplates(res.templates || [])
    } catch {
      // 静默失败
    }
  }

  const handleDeleteExercise = async (itemId: number) => {
    try {
      await exercisePlanApi.deleteItem(itemId)
      await loadExercisePlan(isViewingHistory ? currentDate : undefined)
    } catch {
      // 静默失败
    }
  }

  const handleConfirmExerciseComplete = async () => {
    if (!confirmingPlanItem) return
    setCompletingPlanItemId(confirmingPlanItem.id)
    try {
      const result = await exercisePlanApi.completeItem(confirmingPlanItem.id)
      if (!result.success) return
      setConfirmingPlanItem(null)
      await Promise.all([
        loadExercisePlan(isViewingHistory ? currentDate : undefined),
        loadExerciseRecords(),
      ])
    } catch {
      // 请求失败时保留确认弹窗，便于用户重试或取消。
    } finally {
      setCompletingPlanItemId(null)
    }
  }

  /** 发送消息（流式） */
  const handleSend = async () => {
    if (!input.trim() || loading) return
    const userText = input.trim()
    setInput('')
    await sendChatMessage(userText)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.ctrlKey) {
      e.preventDefault()
      handleSend()
    }
  }

/** 快捷功能 */
const handleQuickAction = (action: string) => {
switch (action) {
case 'diet':
fileInputRef.current?.click()
break
case 'weight':
setShowWeightModal(true)
fetchBodyInfo()
break
}
}

  /** 图片文件选择 → 食物识别 */
  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    e.target.value = ''
    recognizeFoodImage(file)
  }

  /** 拖拽图片 → 食物识别 */
  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault()
    const files = e.dataTransfer.files
    if (files.length > 0 && files[0].type.startsWith('image/')) {
      recognizeFoodImage(files[0])
    }
  }

/** 拉取体重信息（当前/起始/目标/近 7 天记录点，每天取最后一条） */
const fetchBodyInfo = async () => {
try {
const [profileRes, histRes] = await Promise.all([
profileApi.me().catch(() => null),
weightApi.history(30, 200).catch(() => null),
])
const records: any[] = (histRes?.records || []).slice().reverse() // 接口倒序 → 时间升序
const byDay = new Map<string, number>()
let first: number | null = null
let last: number | null = null
for (const r of records) {
if (r.weight_kg == null) continue
const w = Number(r.weight_kg)
const iso = isoOf(new Date(r.recorded_at))
if (first == null) first = w
byDay.set(iso, w)
last = w
}
const weekPoints = [...byDay.entries()]
.sort((a, b) => (a[0] < b[0] ? -1 : 1))
.slice(-7)
.map(([iso, weight]) => ({ iso, weight }))
setBodyInfo({
current: last,
target: Number(profileRes?.profile?.target_weight_kg) || null,
start: first,
weekPoints,
})
} catch {
// 静默失败
}
}

/** 体重录入 */
const handleWeightSubmit = async () => {
const weight = parseFloat(weightInput)
if (isNaN(weight) || weight <= 0 || savingWeight) return
setSavingWeight(true)
try {
// 先落库，当前体重/目标进度卡实时更新
await weightApi.record({ weight_kg: weight })
await fetchBodyInfo()
} catch {
// 落库失败不阻断，AI 对话中仍会尝试记录
} finally {
setSavingWeight(false)
}
setShowWeightModal(false)
setWeightInput('')
await sendChatMessage(`我刚记录了今日体重：${weight}kg，请结合我这一周的体重变化给出趋势反馈和建议`)
}

/** 清空对话 */
  const handleClearChat = async () => {
    setShowConfirmClear(false)
    await clearChat()
  }

  const caloriePercent = calorieSummary.budget > 0
  ? Math.round((calorieSummary.total_calories / calorieSummary.budget) * 100)
  : 0
// 摄入超过预算时剩余为负数，显示为“超出”

// ─── 目标行内编辑 ───
const startEditGoal = (kind: 'protein' | 'carbs' | 'fat' | 'water' | 'waterIntake') => {
setEditingGoal(kind)
if (kind === 'protein') setGoalInput(String(calorieSummary.protein_target_g))
else if (kind === 'carbs') setGoalInput(String(calorieSummary.carbs_target_g))
else if (kind === 'fat') setGoalInput(String(calorieSummary.fat_target_g))
else if (kind === 'water') setGoalInput(String(waterSummary.goal_ml))
else setGoalInput(String(Math.round(waterSummary.total_ml)))
}

const cancelEditGoal = () => {
  setEditingGoal(null)
  setGoalInput('')
}

const saveGoal = async () => {
const n = Math.round(Number(goalInput))
// 饮水已摄入允许设为 0（清空），其他目标必须大于 0
const invalid = Number.isNaN(n) || n < 0 || (editingGoal !== 'waterIntake' && n <= 0)
if (invalid || savingGoal) {
cancelEditGoal()
return
}
const kind = editingGoal
setSavingGoal(true)
try {
if (kind === 'protein' || kind === 'carbs' || kind === 'fat') {
// 保存营养素目标，后端自动重算热量预算
const p = kind === 'protein' ? n : calorieSummary.protein_target_g
const c = kind === 'carbs' ? n : calorieSummary.carbs_target_g
const f = kind === 'fat' ? n : calorieSummary.fat_target_g
await dietApi.setMacroTargets(getCurrentUserId(), p, c, f)
await refreshSummaries()
} else if (kind === 'water') {
await profileApi.update({ water_intake_ml: n })
await refreshSummaries()
} else if (kind === 'waterIntake') {
await waterApi.setManualTotal(n)
await refreshSummaries()
}
cancelEditGoal()
} catch {
alert('保存失败，请稍后再试')
} finally {
setSavingGoal(false)
}
}

  return (
    <div className="ai-chat">
      {/* 日历面板 */}
      <CalendarPanel visible={calendarVisible} />

      {/* 日历收起把手（仅日历展开时显示，重新展开用顶栏的日历按钮） */}
      {calendarVisible && (
        <button
          className="calendar-toggle-btn calendar-toggle-btn--open"
          onClick={() => setCalendarVisible(false)}
          title="收起日历"
        >
          <ChevronLeft size={14} />
        </button>
      )}

      {/* 文件上传隐藏input */}
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        hidden
        onChange={handleFileSelect}
      />

      {/* 对话区 */}
      <div className={`chat-area ${!rightPanelVisible ? 'chat-area--full' : ''}`}>
        {/* 对话标题栏 */}
        <div className="chat-header">
          <div className="chat-header__left">
            <button
              className={`chat-header__cal-btn ${calendarVisible ? 'active' : ''}`}
              onClick={() => setCalendarVisible(!calendarVisible)}
              title={calendarVisible ? '隐藏日历' : '显示日历'}
            >
              <Calendar size={18} />
            </button>
{isViewingHistory && (
  <div>
    <h2 className="chat-header__title">{`${currentDate} 历史对话`}</h2>
    <span className="chat-header__subtitle">查看历史记录 · 切回今天可继续对话</span>
  </div>
)}
          </div>
          <div className="chat-header__actions">
            {isViewingHistory && (
              <button
                className="btn btn-ghost chat-header__btn"
                style={{ color: 'var(--mint-600)', fontWeight: 600 }}
                onClick={() => loadSessionByDate(todayStr)}
              >
                回到今天
              </button>
            )}
<button
  className="btn btn-ghost chat-header__btn"
  onClick={() => setShowConfirmClear(true)}
  disabled={isViewingHistory}
>
  <Trash2 size={14} /> 清空对话
</button>
            <button
              className="chat-header__panel-toggle"
              onClick={() => setRightPanelVisible(!rightPanelVisible)}
              title={rightPanelVisible ? '收起信息栏' : '展开信息栏'}
            >
              {rightPanelVisible ? <PanelRightClose size={18} /> : <PanelRightOpen size={18} />}
            </button>
          </div>
        </div>

        {/* 对话流 */}
        <div className="chat-stream" id="chat-stream">
          {messages.map((msg) => (
            <MessageBubble
              key={msg.id}
              message={msg}
              confirmDiet={confirmDiet}
              dismissDiet={dismissDiet}
              confirmWater={confirmWater}
              dismissWater={dismissWater}
            />
          ))}
          {typing && messages.length > 0 && messages[messages.length - 1]?.role === 'user' && <TypingIndicator />}
          <div ref={messagesEndRef} />
        </div>

        {/* 快捷功能栏 + 输入区 */}
        <div className="chat-input-zone">
          <div className="quick-actions">
<button className="quick-btn" onClick={() => handleQuickAction('diet')}>
<Camera size={16} /> 记饮食
</button>
{/* 记体重入口暂时隐藏，功能保留（handleQuickAction('weight') 可随时恢复） */}
{/* <button className="quick-btn" onClick={() => handleQuickAction('weight')}>
<Scale size={16} /> 记体重
</button> */}
</div>

          <div
            className="chat-input-wrapper"
            onDragOver={(e) => e.preventDefault()}
            onDrop={handleDrop}
          >
            <button className="chat-input__plus" title="更多功能">
              <Plus size={20} />
            </button>
            <textarea
              className="chat-input"
              placeholder="输入你想问的，或拖拽食物图片到这里识别..."
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              rows={1}
            />
            {loading ? (
              <button
                className="chat-input__send chat-input__send--stop active"
                onClick={stopGeneration}
                title="停止生成"
                aria-label="停止生成"
              >
                <Square size={13} fill="currentColor" />
              </button>
            ) : (
              <button
                className={`chat-input__send ${input.trim() ? 'active' : ''}`}
                onClick={handleSend}
                disabled={!input.trim()}
                title="发送 (Enter)"
              >
                <Send size={18} />
              </button>
            )}
</div>
</div>
</div>

      {/* 右侧常驻快捷信息栏 */}
      {rightPanelVisible && (
        <div className="info-panel">
          {/* 今日热量卡片 */}
          {visibleCards.includes('calorie') && (
          <div className="info-card card">
            <div className="info-card__header">
              <span className="info-card__title">
                <Flame size={16} /> {currentDate.slice(5)} 热量
              </span>
<button type="button" className="info-card__link" onClick={() => navigate('/diet')} title="查看饮食记录详情">详情 →</button>
</div>
            <div className="calorie-ring">
              <svg viewBox="0 0 120 120" className="calorie-ring__svg">
                <circle cx="60" cy="60" r="50" fill="none" stroke="#fff3c4" strokeWidth="10" />
                <circle
                  cx="60"
                  cy="60"
                  r="50"
                  fill="none"
                  stroke="#ffc300"
                  strokeWidth="10"
                  strokeLinecap="round"
                  strokeDasharray={`${Math.min(100, caloriePercent) * 3.14} 314`}
                  transform="rotate(-90 60 60)"
                />
              </svg>
              <div className="calorie-ring__center">
                <span className="calorie-ring__percent">{caloriePercent}%</span>
                <span className="calorie-ring__label">已摄入</span>
              </div>
            </div>
            <div className="calorie-stats">
              <div className="calorie-stat">
                <span className="calorie-stat__label">摄入</span>
                <span className="calorie-stat__value">{Math.round(calorieSummary.total_calories)}</span>
              </div>
              <div className="calorie-stat">
                <span className="calorie-stat__label">预算</span>
                <span
                  className="calorie-stat__value"
                  title="由三大营养素目标自动计算，调整目标即可更新"
                >
                  {calorieSummary.budget}
                </span>
              </div>
              <div className="calorie-stat">
                <span className="calorie-stat__label">{calorieSummary.remaining >= 0 ? '剩余' : '超出'}</span>
                <span className="calorie-stat__value calorie-stat__value--accent">
                  {Math.abs(calorieSummary.remaining)}
                </span>
              </div>
            </div>

            {/* 宏量营养素 */}
            <div className="macro-list">
              <div className="macro-item">
                <div className="macro-item__header">
                  <span className="macro-item__name">蛋白质</span>
                  <span className="macro-item__value">{Math.round(calorieSummary.total_protein_g)}g</span>
                </div>
                <div className="macro-item__bar">
                  <div
                    className="macro-item__fill macro-item__fill--protein"
                    style={{ width: `${Math.min(100, (calorieSummary.total_protein_g / calorieSummary.protein_target_g) * 100)}%` }}
                  />
                </div>
                {editingGoal === 'protein' ? (
                  <span className="goal-edit">
                    <input
                      className="goal-edit__input"
                      type="number"
                      min={1}
                      autoFocus
                      value={goalInput}
                      disabled={savingGoal}
                      onChange={(e) => setGoalInput(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') saveGoal()
                        if (e.key === 'Escape') cancelEditGoal()
                      }}
                    />
                    <button className="goal-edit__btn goal-edit__btn--ok" onClick={saveGoal} title="保存" disabled={savingGoal}>
                      {savingGoal ? <Loader2 size={12} className="spin" /> : <Check size={12} />}
                    </button>
                    <button className="goal-edit__btn" onClick={cancelEditGoal} title="取消">
                      <X size={12} />
                    </button>
                  </span>
                ) : (
                  <button
                    className="macro-item__target goal-editable"
                    onClick={() => startEditGoal('protein')}
                    title="点击调整蛋白质目标，预算热量自动更新"
                  >
                    目标 {calorieSummary.protein_target_g}g
                    <Pencil size={11} className="goal-editable__icon" />
                  </button>
                )}
              </div>
              <div className="macro-item">
                <div className="macro-item__header">
                  <span className="macro-item__name">碳水化合物</span>
                  <span className="macro-item__value">{Math.round(calorieSummary.total_carbs_g)}g</span>
                </div>
                <div className="macro-item__bar">
                  <div
                    className="macro-item__fill macro-item__fill--carbs"
                    style={{ width: `${Math.min(100, (calorieSummary.total_carbs_g / calorieSummary.carbs_target_g) * 100)}%` }}
                  />
                </div>
                {editingGoal === 'carbs' ? (
                  <span className="goal-edit">
                    <input
                      className="goal-edit__input"
                      type="number"
                      min={1}
                      autoFocus
                      value={goalInput}
                      disabled={savingGoal}
                      onChange={(e) => setGoalInput(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') saveGoal()
                        if (e.key === 'Escape') cancelEditGoal()
                      }}
                    />
                    <button className="goal-edit__btn goal-edit__btn--ok" onClick={saveGoal} title="保存" disabled={savingGoal}>
                      {savingGoal ? <Loader2 size={12} className="spin" /> : <Check size={12} />}
                    </button>
                    <button className="goal-edit__btn" onClick={cancelEditGoal} title="取消">
                      <X size={12} />
                    </button>
                  </span>
                ) : (
                  <button
                    className="macro-item__target goal-editable"
                    onClick={() => startEditGoal('carbs')}
                    title="点击调整碳水目标，预算热量自动更新"
                  >
                    目标 {calorieSummary.carbs_target_g}g
                    <Pencil size={11} className="goal-editable__icon" />
                  </button>
                )}
              </div>
              <div className="macro-item">
                <div className="macro-item__header">
                  <span className="macro-item__name">脂肪</span>
                  <span className="macro-item__value">{Math.round(calorieSummary.total_fat_g)}g</span>
                </div>
                <div className="macro-item__bar">
                  <div
                    className="macro-item__fill macro-item__fill--fat"
                    style={{ width: `${Math.min(100, (calorieSummary.total_fat_g / calorieSummary.fat_target_g) * 100)}%` }}
                  />
                </div>
                {editingGoal === 'fat' ? (
                  <span className="goal-edit">
                    <input
                      className="goal-edit__input"
                      type="number"
                      min={1}
                      autoFocus
                      value={goalInput}
                      disabled={savingGoal}
                      onChange={(e) => setGoalInput(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') saveGoal()
                        if (e.key === 'Escape') cancelEditGoal()
                      }}
                    />
                    <button className="goal-edit__btn goal-edit__btn--ok" onClick={saveGoal} title="保存" disabled={savingGoal}>
                      {savingGoal ? <Loader2 size={12} className="spin" /> : <Check size={12} />}
                    </button>
                    <button className="goal-edit__btn" onClick={cancelEditGoal} title="取消">
                      <X size={12} />
                    </button>
                  </span>
                ) : (
                  <button
                    className="macro-item__target goal-editable"
                    onClick={() => startEditGoal('fat')}
                    title="点击调整脂肪目标，预算热量自动更新"
                  >
                    目标 {calorieSummary.fat_target_g}g
                    <Pencil size={11} className="goal-editable__icon" />
                  </button>
                )}
              </div>
            </div>
          </div>
          )}

          {/* 今日喝水量可视化卡片（动态水杯动画） */}
          {visibleCards.includes('water') && (
          <div className="info-card card water-card">
            <div className="info-card__header">
              <span className="info-card__title">
                <Droplets size={16} /> {currentDate.slice(5)} 饮水
              </span>
              <span className="info-card__link">
                {waterSummary.record_count > 0 ? `${waterSummary.record_count} 次` : '今日未记录'}
</span>
</div>
              <div className="water-cup">
              <div className="water-cup__glass">
                <div
                  className="water-cup__water"
                  style={{ height: `${Math.min(100, waterSummary.percentage)}%` }}
                >
                  <div className="water-cup__wave" />
                  <div className="water-cup__wave water-cup__wave--alt" />
                </div>
                <div className="water-cup__bubbles">
                  <span className="water-cup__bubble" />
                  <span className="water-cup__bubble water-cup__bubble--s" />
                  <span className="water-cup__bubble water-cup__bubble--xs" />
                </div>
                <div className="water-cup__scale">
                  <span className="water-cup__scale-tick" style={{ bottom: '100%' }} />
                  <span className="water-cup__scale-tick" style={{ bottom: '75%' }} />
                  <span className="water-cup__scale-tick" style={{ bottom: '50%' }} />
                  <span className="water-cup__scale-tick" style={{ bottom: '25%' }} />
                  <span className="water-cup__scale-tick" style={{ bottom: '0%' }} />
                </div>
                <div className="water-cup__center">
                  <span className="water-cup__percent">{Math.round(waterSummary.percentage)}%</span>
                  <span className="water-cup__ratio">
                    {Math.round(waterSummary.total_ml)} / {waterSummary.goal_ml}ml
                  </span>
                </div>
              </div>
            </div>
            <div className="water-stats">
              <div className="water-stat">
                <span className="water-stat__label">已摄入</span>
                {editingGoal === 'waterIntake' ? (
                  <span className="goal-edit">
                    <input
                      className="goal-edit__input goal-edit__input--water"
                      type="number"
                      min={0}
                      autoFocus
                      value={goalInput}
                      disabled={savingGoal}
                      onChange={(e) => setGoalInput(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') saveGoal()
                        if (e.key === 'Escape') cancelEditGoal()
                      }}
                    />
                    <span className="goal-edit__unit">ml</span>
                    <button className="goal-edit__btn goal-edit__btn--ok" onClick={saveGoal} title="保存" disabled={savingGoal}>
                      {savingGoal ? <Loader2 size={12} className="spin" /> : <Check size={12} />}
                    </button>
                    <button className="goal-edit__btn" onClick={cancelEditGoal} title="取消">
                      <X size={12} />
                    </button>
                  </span>
                ) : (
                  <button
                    className="water-stat__value goal-editable"
                    onClick={() => startEditGoal('waterIntake')}
                    title="点击手动修正今日已摄入水量"
                  >
                    {Math.round(waterSummary.total_ml)} ml
                    <Pencil size={11} className="goal-editable__icon" />
                  </button>
                )}
              </div>
              <div className="water-stat">
                <span className="water-stat__label">目标</span>
                {editingGoal === 'water' ? (
                  <span className="goal-edit">
                    <input
                      className="goal-edit__input goal-edit__input--water"
                      type="number"
                      min={1}
                      autoFocus
                      value={goalInput}
                      disabled={savingGoal}
                      onChange={(e) => setGoalInput(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') saveGoal()
                        if (e.key === 'Escape') cancelEditGoal()
                      }}
                    />
                    <span className="goal-edit__unit">ml</span>
                    <button className="goal-edit__btn goal-edit__btn--ok" onClick={saveGoal} title="保存" disabled={savingGoal}>
                      {savingGoal ? <Loader2 size={12} className="spin" /> : <Check size={12} />}
                    </button>
                    <button className="goal-edit__btn" onClick={cancelEditGoal} title="取消">
                      <X size={12} />
                    </button>
                  </span>
                ) : (
                  <button
                    className="water-stat__value goal-editable"
                    onClick={() => startEditGoal('water')}
                    title="点击调整每日饮水目标"
                  >
                    {waterSummary.goal_ml} ml
                    <Pencil size={11} className="goal-editable__icon" />
                  </button>
                )}
              </div>
              <div className="water-stat">
                <span className="water-stat__label">还需</span>
                <span className="water-stat__value water-stat__value--accent">
                  {Math.round(waterSummary.remaining_ml)} ml
                </span>
              </div>
            </div>
            {Object.entries(waterSummary.type_breakdown || {})
              .filter(([type]) => type !== 'manual')
              .length > 0 && (
              <div className="water-types">
                {Object.entries(waterSummary.type_breakdown)
                  .filter(([type]) => type !== 'manual')
                  .map(([type, ml]) => (
                    <span key={type} className="water-types__chip">
                      {type} {Math.round(ml as number)}ml
                    </span>
                  ))}
              </div>
            )}
            <div className="water-card__hint">
              {waterSummary.percentage >= 100
                ? '已达成今日饮水目标，保持节奏！'
                : '在对话中输入"刚喝了 300ml 水"，AI 将自动识别并计入今日饮水。'}
            </div>
          </div>
          )}

          {/* 今日运动计划卡片 */}
          {visibleCards.includes('plan') && (
          <div className="info-card card">
            <div className="info-card__header">
              <span className="info-card__title">
                <Dumbbell size={16} /> {currentDate.slice(5)} 运动计划
              </span>
              {exercisePanelTab === 'plan' && planSummary.items.length > 0 && !isViewingHistory && (
                <button
                  type="button"
                  className="info-card__link"
                  onClick={() => exercisePlanApi.clearToday(getCurrentUserId()).then(() => loadExercisePlan())}
                >
                  清空
                </button>
)}
</div>

            <div className="exercise-panel-tabs" role="tablist" aria-label="运动内容">
              <button
                type="button"
                role="tab"
                aria-selected={exercisePanelTab === 'plan'}
                className={`exercise-panel-tab ${exercisePanelTab === 'plan' ? 'exercise-panel-tab--active' : ''}`}
                onClick={() => setExercisePanelTab('plan')}
              >
                运动计划
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={exercisePanelTab === 'history'}
                className={`exercise-panel-tab ${exercisePanelTab === 'history' ? 'exercise-panel-tab--active' : ''}`}
                onClick={() => setExercisePanelTab('history')}
              >
                消耗记录
              </button>
            </div>

            {exercisePanelTab === 'plan' ? <>
            {/* 运动方案模板选择区 */}
            {templates.length > 0 && (
              <div className="template-section">
                <div className="template-section__label">快速选择模板</div>
                <div className="template-list">
                  {templates.map(tpl => (
                    <div key={tpl.id} className="template-card">
                      <div className="template-card__info" onClick={() => handleApplyTemplate(tpl.id)}>
                        <span className="template-card__name">{tpl.template_name}</span>
                        <span className="template-card__meta">{tpl.total_duration}min · {Math.round(tpl.estimated_calories)}kcal</span>
                      </div>
                      <button
                        className="template-card__delete"
                        onClick={(e) => { e.stopPropagation(); handleDeleteTemplate(tpl.id) }}
                      >
                        <Trash size={11} />
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* 保存为模板按钮 */}
            {planSummary.items.length > 0 && !showSaveTemplate && (
              <button
                className="btn btn-ghost template-save-btn"
                onClick={() => setShowSaveTemplate(true)}
              >
                <PlusIcon size={12} /> 保存为模板
              </button>
            )}
            {showSaveTemplate && (
              <div className="template-save-form">
                <input
                  type="text"
                  className="template-save-input"
                  placeholder="模板名称，如：减脂有氧日"
                  value={templateName}
                  onChange={e => setTemplateName(e.target.value)}
                />
                <div className="template-save-actions">
                  <button className="btn btn-primary btn-sm" onClick={handleSaveTemplate} disabled={!templateName.trim()}>
                    保存
                  </button>
                  <button className="btn btn-ghost btn-sm" onClick={() => { setShowSaveTemplate(false); setTemplateName('') }}>
                    取消
                  </button>
                </div>
              </div>
            )}

            {/* 运动类型选择 */}
            <div className="exercise-types">
              {Object.entries(typeLabels).map(([key, label]) => (
                <button
                  key={key}
                  className={`exercise-type-btn ${selectedType === key ? 'active' : ''}`}
                  style={selectedType === key ? { background: typeColors[key], borderColor: typeColors[key] } : {}}
                  onClick={() => {
                    setSelectedType(key)
                    const group = exerciseGroup?.[key as keyof ExerciseCalorieGroup]
                    if (group && group.length > 0) {
                      setSelectedExercise(group[0].exercise_name)
                    }
                  }}
                >
                  {label}
                </button>
              ))}
            </div>

            {/* 运动选择下拉 */}
            <select
              className="exercise-select"
              value={selectedExercise}
              onChange={(e) => setSelectedExercise(e.target.value)}
            >
              {exerciseGroup?.[selectedType as keyof ExerciseCalorieGroup]?.map((opt) => (
                <option key={opt.exercise_name} value={opt.exercise_name}>{opt.exercise_name} (MET {opt.met_value})</option>
              )) || <option>加载中...</option>}
            </select>

            {/* 时长滑块 */}
            <div className="duration-slider">
              <div className="duration-slider__header">
                <span className="duration-slider__label">时长</span>
                <span className="duration-slider__value">{duration} 分钟</span>
              </div>
              <input
                type="range"
                min="5"
                max="120"
                step="5"
                value={duration}
                onChange={(e) => setDuration(Number(e.target.value))}
                className="duration-slider__input"
              />
              <div className="duration-slider__marks">
                <span>5min</span>
                <span>60min</span>
                <span>120min</span>
              </div>
            </div>

            {/* 添加按钮 */}
            <button
              className="btn btn-primary exercise-add-btn"
              onClick={handleAddExercise}
              disabled={!selectedExercise}
            >
              <PlusIcon size={14} /> 添加到计划
            </button>

            {/* 已添加的运动计划列表 */}
            {planSummary.items.length > 0 && (
              <div className="plan-list">
                {planSummary.items.map((item) => (
                  <div key={item.id} className="plan-item">
                    <div className="plan-item__info">
                      <span className="plan-item__type-dot" style={{ background: typeColors[item.exercise_type] || '#5b9bd5' }} />
                      <span className="plan-item__name">{item.exercise_name}</span>
                      <span className="plan-item__duration">{item.duration_min}min</span>
                    </div>
                    <div className="plan-item__right">
                      <span className="plan-item__calories">{Math.round(item.calories_burned)}kcal</span>
                      {item.completed ? (
                        <span className="plan-item__completed"><Check size={12} /> 已完成</span>
                      ) : (
                        <button
                          type="button"
                          className="plan-item__complete"
                          onClick={() => setConfirmingPlanItem(item)}
                        >
                          完成
                        </button>
                      )}
                      {!item.completed && (
                        <button
                          type="button"
                          className="plan-item__delete"
                          onClick={() => handleDeleteExercise(item.id)}
                          aria-label={`删除${item.exercise_name}`}
                        >
                          <Trash size={12} />
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* 已完成运动才计入热量消耗，统计统一在下方运动热量消耗卡片展示 */}
            </> : (
              <div className="exercise-history-list" role="tabpanel">
                {exerciseRecords.length > 0 ? exerciseRecords.map((record) => (
                  <div key={record.id} className="exercise-history-item">
                    <div className="exercise-history-item__main">
                      <span
                        className="plan-item__type-dot"
                        style={{ background: typeColors[record.exercise_type || ''] || '#5b9bd5' }}
                      />
                      <div>
                        <div className="exercise-history-item__name">{record.exercise_name}</div>
                        <div className="exercise-history-item__meta">
                          {record.scheduled_date || '今日'} · {record.duration_min || 0} min
                        </div>
                      </div>
                    </div>
                    <strong className="exercise-history-item__calories">+{Math.round(record.calories_burned || 0)} kcal</strong>
                  </div>
                )) : (
                  <div className="exercise-history-empty">完成运动后，消耗热量会记录在这里。</div>
                )}
              </div>
            )}
          </div>
          )}

          {/* 运动热量消耗卡片 */}
          {visibleCards.includes('burn') && (
          <div className="info-card card">
            <div className="info-card__header">
              <span className="info-card__title">
<Dumbbell size={16} /> {currentDate.slice(5)} 运动热量消耗
              </span>
            </div>
            <div className="calorie-gap exercise-burn">
              <div className="calorie-gap__value positive">
                {Math.round(exerciseCalories)}
                <span className="calorie-gap__unit">kcal</span>
              </div>
              <div className="calorie-gap__bar">
                <div
                  className="calorie-gap__fill positive"
                  style={{ width: `${exerciseBurnPercent}%` }}
                />
              </div>
              <div className="calorie-gap__detail">
                <div className="calorie-gap__row">
                  <span>已完成项目</span>
                  <span>{planSummary.completed_count}/{planSummary.item_count} 项</span>
                </div>
                <div className="calorie-gap__row">
                  <span>完成时长</span>
                  <span>{planSummary.total_duration} min</span>
                </div>
                <div className="calorie-gap__row calorie-gap__row--total">
                  <span>计划预计消耗</span>
                  <span>{Math.round(planSummary.planned_calories)} kcal</span>
                </div>
              </div>
              <div className="exercise-burn__hint">确认完成的运动才会计入热量消耗</div>
            </div>
          </div>
          )}

          {/* 今日热量缺口卡片 */}
          {visibleCards.includes('gap') && (
          <div className="info-card card">
            <div className="info-card__header">
              <span className="info-card__title">
<Flame size={16} /> 今日热量缺口
                </span>
              </div>
            <div className="calorie-gap">
              <div className={`calorie-gap__value ${calorieGap >= 0 ? 'positive' : 'negative'}`}>
                {calorieGap >= 0 ? '+' : ''}{calorieGap}
                <span className="calorie-gap__unit">kcal</span>
              </div>
              <div className="calorie-gap__bar">
                <div
                  className={`calorie-gap__fill ${calorieGap >= 0 ? 'positive' : 'negative'}`}
                  style={{ width: `${Math.min(100, Math.abs(calorieGap) / 25)}%` }}
                />
              </div>
              <div className="calorie-gap__detail">
                <div className="calorie-gap__row">
                  <span>摄入</span>
                  <span>{Math.round(intakeCalories)} kcal</span>
                </div>
                <div className="calorie-gap__row">
                  <span>基础代谢 (BMR)</span>
                  <span>{bmr} kcal</span>
                </div>
                <div className="calorie-gap__row">
                  <span>运动消耗</span>
                  <span>+{Math.round(exerciseCalories)} kcal</span>
                </div>
                <div className="calorie-gap__row calorie-gap__row--total">
                  <span>总消耗</span>
                  <span>{Math.round(totalBurn)} kcal</span>
                </div>
              </div>
            </div>
          </div>
          )}

          {/* 目标进度卡片 */}
          {visibleCards.includes('goal') && (
          <div className="info-card card">
            <div className="info-card__header">
              <span className="info-card__title">
<TrendingDown size={16} /> 目标进度
                </span>
              </div>
<div className="goal-progress">
<div className="goal-progress__bar">
<div
className="goal-progress__fill"
style={{ width: `${goalPct}%` }}
/>
</div>
<span className="goal-progress__percent">{goalPct}%</span>
</div>
<div className="goal-stats">
<div className="goal-stat">
<span className="goal-stat__label">当前</span>
<span className="goal-stat__value">{bodyInfo.current != null ? `${bodyInfo.current}kg` : `${mockGoalProgress.currentWeight}kg`}</span>
</div>
<div className="goal-stat">
<span className="goal-stat__label">目标</span>
<span className="goal-stat__value">{bodyInfo.target != null ? `${bodyInfo.target}kg` : `${mockGoalProgress.targetWeight}kg`}</span>
</div>
<div className="goal-stat">
<span className="goal-stat__label">本周</span>
<span className="goal-stat__value goal-stat__value--down">
{goalWeeklyChange != null ? `${goalWeeklyChange > 0 ? '+' : ''}${goalWeeklyChange}kg` : '—'}
</span>
</div>
</div>
          </div>
          )}

          {/* 添加卡片入口 */}
          <button className="info-card-add" onClick={() => setShowCardPicker(true)}>
            <Plus size={14} /> 添加卡片
          </button>
        </div>
      )}

      {/* 体重录入弹窗 */}
      {showWeightModal && (
        <Modal title="记录体重" onClose={() => setShowWeightModal(false)}>
          <div className="weight-modal">
            <div className="weight-modal__input-group">
              <input
                type="number"
                step="0.1"
                placeholder="请输入体重"
                value={weightInput}
                onChange={(e) => setWeightInput(e.target.value)}
                autoFocus
                onKeyDown={(e) => e.key === 'Enter' && handleWeightSubmit()}
              />
              <span className="weight-modal__unit">kg</span>
            </div>
<div className={`weight-modal__hint ${weightInput ? 'weight-modal__hint--advice' : ''}`}>
{weightAdvice}
</div>
<button className="btn btn-primary weight-modal__submit" onClick={handleWeightSubmit} disabled={savingWeight}>
{savingWeight ? '保存中...' : '确认记录'}
</button>
          </div>
        </Modal>
      )}

      {/* 运动完成确认弹窗 */}
      {confirmingPlanItem && (
        <Modal title="确认完成运动" onClose={() => !completingPlanItemId && setConfirmingPlanItem(null)}>
          <div className="confirm-modal exercise-complete-modal">
            <Dumbbell size={32} className="exercise-complete-modal__icon" />
            <p className="confirm-modal__text">确认已完成「{confirmingPlanItem.exercise_name}」？</p>
            <p className="confirm-modal__subtext">
              本次将计入 {confirmingPlanItem.duration_min} 分钟、{Math.round(confirmingPlanItem.calories_burned)} kcal 运动消耗。
            </p>
            <div className="confirm-modal__actions">
              <button
                type="button"
                className="btn btn-ghost"
                disabled={completingPlanItemId === confirmingPlanItem.id}
                onClick={() => setConfirmingPlanItem(null)}
              >
                取消
              </button>
              <button
                type="button"
                className="btn btn-primary"
                disabled={completingPlanItemId === confirmingPlanItem.id}
                onClick={handleConfirmExerciseComplete}
              >
                {completingPlanItemId === confirmingPlanItem.id ? <><Loader2 size={14} className="spin" /> 保存中</> : <><Check size={14} /> 确认完成</>}
              </button>
            </div>
          </div>
        </Modal>
      )}

      {/* 自定义卡片弹窗 */}
      {showCardPicker && (
        <Modal title="自定义卡片" onClose={() => setShowCardPicker(false)}>
          <div className="card-picker">
            <p className="card-picker__desc">勾选需要在右侧信息栏展示的卡片：</p>
            <div className="card-picker__list">
              {PANEL_CARDS.map((card) => (
                <label key={card.id} className="card-picker__item">
                  <input
                    type="checkbox"
                    checked={visibleCards.includes(card.id)}
                    onChange={() => togglePanelCard(card.id)}
                  />
                  <span className="card-picker__name">{card.label}</span>
                  <em className={visibleCards.includes(card.id) ? 'card-picker__state card-picker__state--on' : 'card-picker__state'}>
                    {visibleCards.includes(card.id) ? '展示中' : '未展示'}
                  </em>
                </label>
              ))}
            </div>
            <button className="btn btn-primary card-picker__done" onClick={() => setShowCardPicker(false)}>
              完成
            </button>
          </div>
        </Modal>
      )}

      {/* 清空确认弹窗 */}
      {showConfirmClear && (
        <Modal title="清空对话" onClose={() => setShowConfirmClear(false)}>
          <div className="confirm-modal">
            <Trash2 size={32} className="confirm-modal__icon" />
            <p className="confirm-modal__text">确定要清空当前会话记录吗？</p>
            <p className="confirm-modal__subtext">此操作不可恢复，将清除服务端会话历史。</p>
            <div className="confirm-modal__actions">
              <button className="btn btn-ghost" onClick={() => setShowConfirmClear(false)}>
                取消
              </button>
              <button
                className="btn btn-primary"
                style={{ background: 'var(--color-danger)' }}
                onClick={handleClearChat}
              >
                确认清空
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  )
}

/* —— 消息气泡组件 —— */
function MessageBubble({
  message,
  confirmDiet,
  dismissDiet,
  confirmWater,
  dismissWater,
}: {
  message: Message
  confirmDiet: (msgId: string, foods: any[]) => Promise<void>
  dismissDiet: (msgId: string) => void
  confirmWater: (msgId: string, amount_ml: number, drink_type?: string, notes?: string) => Promise<void>
  dismissWater: (msgId: string) => void
}) {
  const [hovered, setHovered] = useState(false)
  const isAI = message.role === 'ai'

  return (
    <div
      className={`msg ${isAI ? 'msg--ai' : 'msg--user'} fade-in`}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      {isAI && (
        <div className="msg__avatar">
          <img src="/meituan-logo.png" alt="美团 Logo" width="32" height="32" />
        </div>
      )}
      <div className="msg__body">
        {message.type === 'text' && (
          <div className={`msg__bubble ${isAI ? 'msg__bubble--ai' : 'msg__bubble--user'}`}>
            {message.imageUrl && (
              <img
                src={message.imageUrl}
                className="msg__image"
                alt="上传的食物图片"
                onClick={(e) => {
                  // 点击放大预览
                  const url = message.imageUrl
                  if (!url) return
                  const win = window.open('', '_blank')
                  if (win) {
                    win.document.write(`<img src="${url}" style="max-width:100%">`)
                    win.document.title = '食物图片'
                  }
                  e.stopPropagation()
                }}
              />
            )}
            <p className="msg__text">
              {message.content || (isAI ? <span className="typing-inline"><span className="typing__dot" /><span className="typing__dot" /><span className="typing__dot" /></span> : '')}
            </p>
          </div>
        )}
        {/* 饮食确认按钮 */}
        {isAI && message.dietData && message.dietData.foods && message.dietData.foods.length > 0 && (
          <div className="diet-confirm">
            <div className="diet-confirm__summary">
              检测到饮食：{message.dietData.foods.map(f => f.food_name).join('、')}
              （共 {Math.round(message.dietData.total_calories)} kcal）
            </div>
            <div className="diet-confirm__detail">
              {message.dietData.foods.map((f, i) => (
                <span key={i} className="diet-confirm__food">
                  {f.food_name} {f.amount_g}g · {Math.round(f.calories)}kcal
                  {' · '}蛋白{f.protein_g}g 碳水{f.carbs_g}g 脂肪{f.fat_g}g
                </span>
              ))}
            </div>
            <div className="diet-confirm__actions">
              <button
                className="btn btn-primary btn-sm"
                onClick={() => confirmDiet(message.id, message.dietData!.foods)}
              >
                <Check size={12} /> 计入今日热量
              </button>
              <button
                className="btn btn-ghost btn-sm"
                onClick={() => dismissDiet(message.id)}
              >
                不计入
              </button>
            </div>
          </div>
        )}
        {/* 喝水确认按钮 */}
        {isAI && message.waterData && message.waterData.amount_ml > 0 && (
          <div className="water-confirm">
            <div className="water-confirm__summary">
              <Droplets size={14} />
              检测到饮水：{message.waterData.description || `${message.waterData.amount_ml}ml`}
              （{DRINK_TYPE_LABEL[message.waterData.drink_type] || message.waterData.drink_type} · {Math.round(message.waterData.amount_ml)}ml）
            </div>
            <div className="water-confirm__actions">
              <button
                className="btn btn-primary btn-sm"
                onClick={() => confirmWater(
                  message.id,
                  message.waterData!.amount_ml,
                  message.waterData!.drink_type,
                )}
              >
                <Check size={12} /> 计入今日饮水
              </button>
              <button
                className="btn btn-ghost btn-sm"
                onClick={() => dismissWater(message.id)}
              >
                不计入
              </button>
            </div>
          </div>
        )}
        {message.type === 'card' && message.cardData && (
          <DietCard data={message.cardData} />
        )}
        {message.type === 'recipe' && message.cardData && (
          <RecipeCard data={message.cardData} />
        )}
        <div className="msg__meta">
          <span className="msg__time">{message.timestamp}</span>
          {hovered && isAI && message.content && (
            <div className="msg__actions">
              <button title="复制" onClick={() => navigator.clipboard.writeText(message.content)}>
                <Copy size={14} />
              </button>
              <button title="赞"><ThumbsUp size={14} /></button>
              <button title="踩"><ThumbsDown size={14} /></button>
              <button title="反馈"><Flag size={14} /></button>
            </div>
          )}
          {hovered && !isAI && (
            <div className="msg__actions">
              <button title="复制" onClick={() => navigator.clipboard.writeText(message.content)}>
                <Copy size={14} />
              </button>
            </div>
          )}
        </div>
        {isAI && message.type !== 'text' && (
          <div className="msg__watermark">AI生成 · 仅供生活参考</div>
        )}
      </div>
    </div>
  )
}

/* —— 饮食卡片 —— */
function DietCard({ data }: { data: any }) {
  return (
    <div className="diet-card card">
      <div className="diet-card__header">
        <span className="diet-card__title">{data.title}</span>
        <span className="diet-card__total">{data.totalCalories} kcal</span>
      </div>
      <div className="diet-card__items">
        {data.items?.map((item: any, idx: number) => (
          <div key={idx} className="diet-card__item">
            <span className="diet-card__item-name">{item.name}</span>
            <span className="diet-card__item-amount">{item.amount}</span>
            <span className="diet-card__item-cal">{item.calories} kcal</span>
          </div>
        ))}
      </div>
      <div className="diet-card__footer">
        <button className="diet-card__action">替换菜品</button>
        <button className="diet-card__action">详情</button>
      </div>
    </div>
  )
}

/* —— 食谱卡片 —— */
function RecipeCard({ data }: { data: any }) {
  return (
    <div className="recipe-card card">
      <div className="recipe-card__header">
        <span className="recipe-card__title">{data.title}</span>
        <span className="recipe-card__target">目标 {data.targetCalories} kcal/天</span>
      </div>
      <div className="recipe-card__days">
        {data.days?.map((day: any, idx: number) => (
          <div key={idx} className="recipe-card__day">
            <div className="recipe-card__day-header">{day.day}</div>
            <div className="recipe-card__meals">
              {day.meals?.map((meal: any, mIdx: number) => (
                <div key={mIdx} className="recipe-card__meal">
                  <span className="recipe-card__meal-type">{meal.meal}</span>
                  <span className="recipe-card__meal-desc">{meal.desc}</span>
                  <span className="recipe-card__meal-cal">{meal.calories} kcal</span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
      <div className="recipe-card__footer">
        <button className="recipe-card__action">导出食谱</button>
        <button className="recipe-card__action recipe-card__action--primary">调整方案</button>
      </div>
    </div>
  )
}

/* —— 打字机动画指示器 —— */
function TypingIndicator() {
  return (
    <div className="msg msg--ai fade-in">
      <div className="msg__avatar">
        <img src="/meituan-logo.png" alt="美团 Logo" width="32" height="32" />
      </div>
      <div className="msg__body">
        <div className="msg__bubble msg__bubble--ai typing">
          <span className="typing__dot" />
          <span className="typing__dot" />
          <span className="typing__dot" />
        </div>
      </div>
    </div>
  )
}

/* —— 通用弹窗组件 —— */
function Modal({ title, children, onClose }: { title: string; children: React.ReactNode; onClose: () => void }) {
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal__header">
          <h3 className="modal__title">{title}</h3>
          <button className="modal__close" onClick={onClose}>
            <X size={18} />
          </button>
        </div>
        <div className="modal__body">{children}</div>
      </div>
    </div>
  )
}
