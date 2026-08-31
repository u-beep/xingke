import { useState, useRef, useEffect } from 'react'
import { getCurrentUserId } from '../../services/authStore'
import {
  Flag,
  Trash2,
  Send,
  Plus,
  Mic,
  Camera,
  Scale,
  CalendarDays,
  ChefHat,
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
} from 'lucide-react'
import { mockGoalProgress } from '../../data/mockData'
import { useChat } from '../../store/ChatContext'
import { exerciseApi, exercisePlanApi, workoutApi, type ExerciseCalorieGroup, type WorkoutTemplateInfo, type ExerciseRecordInfo, type PlanSummary } from '../../services/api'
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
}

export default function AIChat() {
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
    generateRecipe,
    clearChat,
    loadSessionByDate,
    confirmDiet,
    dismissDiet,
    confirmWater,
    dismissWater,
    stopGeneration,
  } = useChat()

  // 仅本页的 UI 局部状态
  const [input, setInput] = useState('')
  const [showWeightModal, setShowWeightModal] = useState(false)
  const [showRecipeModal, setShowRecipeModal] = useState(false)
  const [showConfirmClear, setShowConfirmClear] = useState(false)
  const [rightPanelVisible, setRightPanelVisible] = useState(true)
const [visibleCards, setVisibleCards] = useState<string[]>(loadVisibleCards)
const [showCardPicker, setShowCardPicker] = useState(false)
  const [calendarVisible, setCalendarVisible] = useState(false)
  const [weightInput, setWeightInput] = useState('')
  const [recipeDays, setRecipeDays] = useState<'1' | '7'>('1')
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
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const now = new Date()
  const todayStr = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
  const isViewingHistory = currentDate !== todayStr

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // 页面加载后拉取当天会话（无历史时不自动发问候，保持空对话）
  useEffect(() => {
    // loadTodaySession 已在 ChatContext 的 useEffect 中触发
    // 这里不需要额外操作
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
        break
      case 'plan':
        sendChatMessage('请给我今日的饮食和运动总览')
        break
      case 'recipe':
        setShowRecipeModal(true)
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

  /** 体重录入 */
  const handleWeightSubmit = async () => {
    if (!weightInput) return
    const weight = weightInput
    setShowWeightModal(false)
    setWeightInput('')
    await sendChatMessage(`请帮我记录今日体重：${weight}kg，并给出趋势反馈`)
  }

  /** 生成食谱 */
  const handleGenerateRecipe = async () => {
    setShowRecipeModal(false)
    await generateRecipe(recipeDays === '7' ? 7 : 1)
  }

  /** 清空对话 */
  const handleClearChat = async () => {
    setShowConfirmClear(false)
    await clearChat()
  }

  const caloriePercent = Math.min(100, Math.round((calorieSummary.total_calories / calorieSummary.budget) * 100))

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
            <button className="quick-btn" onClick={() => handleQuickAction('weight')}>
              <Scale size={16} /> 记体重
            </button>
            <button className="quick-btn" onClick={() => handleQuickAction('plan')}>
              <CalendarDays size={16} /> 今日计划
            </button>
            <button className="quick-btn" onClick={() => handleQuickAction('recipe')}>
              <ChefHat size={16} /> 生成食谱
            </button>
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
            <button className="chat-input__mic" title="语音输入">
              <Mic size={18} />
            </button>
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
<span className="info-card__link">详情 →</span>
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
                  strokeDasharray={`${(caloriePercent / 100) * 314} 314`}
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
                <span className="calorie-stat__value">{calorieSummary.budget}</span>
              </div>
              <div className="calorie-stat">
                <span className="calorie-stat__label">剩余</span>
                <span className="calorie-stat__value calorie-stat__value--accent">
                  {calorieSummary.remaining}
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
                    style={{ width: `${Math.min(100, (calorieSummary.total_protein_g / 120) * 100)}%` }}
                  />
                </div>
                <span className="macro-item__target">目标 120g</span>
              </div>
              <div className="macro-item">
                <div className="macro-item__header">
                  <span className="macro-item__name">碳水化合物</span>
                  <span className="macro-item__value">{Math.round(calorieSummary.total_carbs_g)}g</span>
                </div>
                <div className="macro-item__bar">
                  <div
                    className="macro-item__fill macro-item__fill--carbs"
                    style={{ width: `${Math.min(100, (calorieSummary.total_carbs_g / 200) * 100)}%` }}
                  />
                </div>
                <span className="macro-item__target">目标 200g</span>
              </div>
              <div className="macro-item">
                <div className="macro-item__header">
                  <span className="macro-item__name">脂肪</span>
                  <span className="macro-item__value">{Math.round(calorieSummary.total_fat_g)}g</span>
                </div>
                <div className="macro-item__bar">
                  <div
                    className="macro-item__fill macro-item__fill--fat"
                    style={{ width: `${Math.min(100, (calorieSummary.total_fat_g / 60) * 100)}%` }}
                  />
                </div>
                <span className="macro-item__target">目标 60g</span>
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
                <span className="water-stat__value">{Math.round(waterSummary.total_ml)} ml</span>
              </div>
              <div className="water-stat">
                <span className="water-stat__label">目标</span>
                <span className="water-stat__value">{waterSummary.goal_ml} ml</span>
              </div>
              <div className="water-stat">
                <span className="water-stat__label">还需</span>
                <span className="water-stat__value water-stat__value--accent">
                  {Math.round(waterSummary.remaining_ml)} ml
                </span>
              </div>
            </div>
            {Object.keys(waterSummary.type_breakdown || {}).length > 0 && (
              <div className="water-types">
                {Object.entries(waterSummary.type_breakdown).map(([type, ml]) => (
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
                  style={{ width: `${mockGoalProgress.percentage}%` }}
                />
              </div>
              <span className="goal-progress__percent">{mockGoalProgress.percentage}%</span>
            </div>
            <div className="goal-stats">
              <div className="goal-stat">
                <span className="goal-stat__label">当前</span>
                <span className="goal-stat__value">{mockGoalProgress.currentWeight}kg</span>
              </div>
              <div className="goal-stat">
                <span className="goal-stat__label">目标</span>
                <span className="goal-stat__value">{mockGoalProgress.targetWeight}kg</span>
              </div>
              <div className="goal-stat">
                <span className="goal-stat__label">本周</span>
                <span className="goal-stat__value goal-stat__value--down">
                  {mockGoalProgress.weeklyChange}kg
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
            <div className="weight-modal__hint">AI将根据体重变化趋势生成反馈</div>
            <button className="btn btn-primary weight-modal__submit" onClick={handleWeightSubmit}>
              确认记录
            </button>
          </div>
        </Modal>
      )}

      {/* 生成食谱确认弹窗 */}
      {showRecipeModal && (
        <Modal title="生成食谱" onClose={() => setShowRecipeModal(false)}>
          <div className="recipe-modal">
            <p className="recipe-modal__desc">请选择生成范围，AI将根据你的身体数据定制食谱：</p>
            <div className="recipe-modal__options">
              <button
                className={`recipe-modal__option ${recipeDays === '1' ? 'recipe-modal__option--active' : ''}`}
                onClick={() => setRecipeDays('1')}
              >
                <CalendarDays size={20} />
                <span>当日食谱</span>
                <small>3餐 · 约1600千卡</small>
              </button>
              <button
                className={`recipe-modal__option ${recipeDays === '7' ? 'recipe-modal__option--active' : ''}`}
                onClick={() => setRecipeDays('7')}
              >
                <CalendarDays size={20} />
                <span>本周食谱</span>
                <small>21餐 · 7天计划</small>
              </button>
            </div>
            <button
              className="btn btn-primary recipe-modal__submit"
              onClick={handleGenerateRecipe}
            >
              确认生成
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
                  {' · '}P{f.protein_g}g C{f.carbs_g}g F{f.fat_g}g
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
              （{message.waterData.drink_type} · {Math.round(message.waterData.amount_ml)}ml）
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
