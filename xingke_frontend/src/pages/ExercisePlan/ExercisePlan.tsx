import { useState, useEffect, useMemo, useCallback } from 'react'
import {
  Dumbbell, Clock, Flame, Plus, Trash2, Loader2, Check, TrendingUp,
  History, ChevronLeft, ChevronRight, ListChecks, CalendarDays, X,
} from 'lucide-react'
import {
  exerciseApi, exercisePlanApi, workoutApi,
  type PlanSummary, type PlanItem, type WorkoutTemplateInfo,
  type ExerciseCalorieGroup, type ExerciseRecordInfo, type DailyStat,
} from '../../services/api'
import { getCurrentUserId } from '../../services/authStore'
import './ExercisePlan.css'

// ─── 类型与工具 ───

const TYPE_META: Record<string, { label: string; color: string }> = {
  cardio: { label: '有氧运动', color: '#3b82f6' },
  strength: { label: '力量训练', color: '#f59e0b' },
  anaerobic: { label: '无氧运动', color: '#ec4899' },
}

const WEEK_LABELS = ['一', '二', '三', '四', '五', '六', '日']

function toDateStr(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function todayStr(): string {
  return toDateStr(new Date())
}

/** 本周周一日期 */
function mondayOf(d: Date): Date {
  const m = new Date(d)
  m.setDate(d.getDate() - ((d.getDay() + 6) % 7))
  return m
}

/** 本周 7 天日期（周一起） */
function weekDates(): string[] {
  const monday = mondayOf(new Date())
  return Array.from({ length: 7 }, (_, i) => {
    const d = new Date(monday)
    d.setDate(monday.getDate() + i)
    return toDateStr(d)
  })
}

/** 计算热量: MET × 体重(kg) × 时长(h)，体重取后端同款默认值 71.5kg */
function calcCalories(met: number, durationMin: number): number {
  return Math.round(met * 71.5 * (durationMin / 60))
}

function typeLabel(t: string | null): string {
  if (!t) return '运动'
  if (TYPE_META[t]) return TYPE_META[t].label
  return t
}

function typeColor(t: string | null): string {
  if (!t) return '#94a6a1'
  if (TYPE_META[t]) return TYPE_META[t].color
  const found = Object.values(TYPE_META).find((m) => m.label === t)
  return found?.color || '#94a6a1'
}

/** 生成月历网格（周一起，固定 6 行 42 格） */
function monthDays(year: number, month: number): Array<{ date: Date; inMonth: boolean }> {
  const first = new Date(year, month, 1)
  const offset = (first.getDay() + 6) % 7
  return Array.from({ length: 42 }, (_, i) => {
    const d = new Date(year, month, 1 - offset + i)
    return { date: d, inMonth: d.getMonth() === month }
  })
}

const EMPTY_PLAN: PlanSummary = {
  total_calories: 0,
  total_duration: 0,
  completed_count: 0,
  planned_calories: 0,
  planned_duration: 0,
  item_count: 0,
  items: [],
}

type StatsFilter = 'week' | 'month' | 'year'

// ─── 页面组件 ───

export default function ExercisePlan() {
  const userId = getCurrentUserId()
  const loading = useState(true)[0]
  const setLoading = useState(true)[1]

  // 本周记录（汇总卡 + 周趋势）
  const [weekRecords, setWeekRecords] = useState<ExerciseRecordInfo[]>([])

  // ── 运动计划板块（复用 AI 聊天页方案） ──
  const [panelTab, setPanelTab] = useState<'plan' | 'burn'>('plan')
  const [exerciseGroup, setExerciseGroup] = useState<ExerciseCalorieGroup | null>(null)
  const [planSummary, setPlanSummary] = useState<PlanSummary>(EMPTY_PLAN)
  const [burnRecords, setBurnRecords] = useState<ExerciseRecordInfo[]>([])
  const [selectedType, setSelectedType] = useState<string>('cardio')
  const [selectedExercise, setSelectedExercise] = useState<string>('')
  const [duration, setDuration] = useState<number>(30)
  const [templates, setTemplates] = useState<WorkoutTemplateInfo[]>([])
  const [showSaveTemplate, setShowSaveTemplate] = useState(false)
  const [templateName, setTemplateName] = useState('')
  const [confirmingPlanItem, setConfirmingPlanItem] = useState<PlanItem | null>(null)
  const [completingItemId, setCompletingItemId] = useState<number | null>(null)

  // ── 日历历史 ──
  const now = new Date()
  const [calYear, setCalYear] = useState(now.getFullYear())
  const [calMonth, setCalMonth] = useState(now.getMonth())
  const [selectedDate, setSelectedDate] = useState<string>(todayStr())
  const [monthRecords, setMonthRecords] = useState<Record<string, ExerciseRecordInfo[]>>({})

  // ── 统计图表 ──
  const [statsFilter, setStatsFilter] = useState<StatsFilter>('week')
  const [statsYear, setStatsYear] = useState(now.getFullYear())
  const [statsPoints, setStatsPoints] = useState<DailyStat[]>([])
  const [hoverBar, setHoverBar] = useState<number | null>(null)

  const loadWeek = useCallback(async () => {
    try {
      const res = await exerciseApi.week()
      setWeekRecords(res?.records || [])
    } catch (err) {
      console.error('加载本周运动失败:', err)
    }
  }, [])

  const loadBurnRecords = useCallback(async () => {
    try {
      const res = await exerciseApi.history(90)
      setBurnRecords(res?.records || [])
    } catch (err) {
      console.error('加载消耗记录失败:', err)
    }
  }, [])

  const loadPlan = useCallback(async () => {
    try {
      const summary = await exercisePlanApi.today(userId)
      setPlanSummary({ ...EMPTY_PLAN, ...summary, items: summary.items || [] })
    } catch {
      // 静默失败
    }
  }, [userId])

  const loadTemplates = useCallback(async () => {
    try {
      const res = await workoutApi.listTemplates(userId)
      setTemplates(res.templates || [])
    } catch {
      // 静默失败
    }
  }, [userId])

  /** 加载指定月份的运动记录（日历打点 + 当日记录） */
  const loadMonthRecords = useCallback(async (year: number, month: number) => {
    const start = toDateStr(new Date(year, month, 1))
    const end = toDateStr(new Date(year, month + 1, 0))
    try {
      const res = await exerciseApi.range(start, end)
      const map: Record<string, ExerciseRecordInfo[]> = {}
      for (const r of (res?.records || []) as ExerciseRecordInfo[]) {
        const d = r.scheduled_date
        if (!d) continue
        if (!map[d]) map[d] = []
        map[d].push(r)
      }
      setMonthRecords(map)
    } catch (err) {
      console.error('加载月度运动记录失败:', err)
    }
  }, [])

  const reloadAll = useCallback(async () => {
    await Promise.all([loadWeek(), loadPlan(), loadBurnRecords(), loadMonthRecords(calYear, calMonth)])
  }, [loadWeek, loadPlan, loadBurnRecords, loadMonthRecords, calYear, calMonth])

  useEffect(() => {
    const init = async () => {
      try {
        const groups = await workoutApi.exercises()
        setExerciseGroup(groups)
        if (groups.cardio.length > 0) setSelectedExercise(groups.cardio[0].exercise_name)
      } catch {
        // 静默失败
      }
      await reloadAll()
      setLoading(false)
    }
    init()
    loadTemplates()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 月份切换时重新拉取该月记录
  useEffect(() => {
    loadMonthRecords(calYear, calMonth)
  }, [calYear, calMonth, loadMonthRecords])

  // 当前类型的运动选项
  const typeOptions = exerciseGroup?.[selectedType as keyof ExerciseCalorieGroup] || []

  // 切换类型后默认选中第一个运动
  useEffect(() => {
    const group = exerciseGroup?.[selectedType as keyof ExerciseCalorieGroup]
    if (group && group.length > 0 && !group.some((o) => o.exercise_name === selectedExercise)) {
      setSelectedExercise(group[0].exercise_name)
    }
  }, [selectedType, exerciseGroup]) // eslint-disable-line react-hooks/exhaustive-deps

  const selectedMet = typeOptions.find((o) => o.exercise_name === selectedExercise)?.met_value ?? 5.0
  const estCalories = calcCalories(selectedMet, duration)

  // ─── 本周统计 ───
  const weekStats = useMemo(() => ({
    count: weekRecords.length,
    duration: weekRecords.reduce((s, r) => s + (r.duration_min || 0), 0),
    calories: Math.round(weekRecords.reduce((s, r) => s + (r.calories_burned || 0), 0)),
  }), [weekRecords])

  // ─── 本周每日消耗（统计卡「周」视图，含热量/时长聚合） ───
  const weekChart = useMemo(() => {
    const agg = new Map<string, { calories: number; duration: number }>()
    weekRecords.forEach((r) => {
      const d = r.scheduled_date || ''
      const prev = agg.get(d) || { calories: 0, duration: 0 }
      agg.set(d, {
        calories: prev.calories + (r.calories_burned || 0),
        duration: prev.duration + (r.duration_min || 0),
      })
    })
    const dates = weekDates()
    const bars = dates.map((d, i) => {
      const a = agg.get(d)
      return {
        label: WEEK_LABELS[i],
        calories: Math.round(a?.calories || 0),
        duration: Math.round(a?.duration || 0),
        title: `${d.slice(5).replace('-', '/')} 周${WEEK_LABELS[i]}`,
        isToday: d === todayStr(),
      }
    })
    const max = Math.max(...bars.map((b) => b.calories), 100)
    return { bars, max }
  }, [weekRecords])

  // ─── 日历选中日的记录 ───
  const selectedDayRecords = monthRecords[selectedDate] || []
  const monthRecordCount = Object.keys(monthRecords).length

  // ─── 统计图表数据（按日聚合 → 月/年分桶；周视图用本地 weekRecords，无需请求） ───
  const statsRange = useMemo(() => {
    const t = new Date()
    if (statsFilter === 'month') {
      // 最近 12 个月
      const start = new Date(t.getFullYear(), t.getMonth() - 11, 1)
      return { start: toDateStr(start), end: toDateStr(t) }
    }
    if (statsFilter === 'year') {
      // 按年：整年区间，可切换到任意历史年份
      return { start: `${statsYear}-01-01`, end: `${statsYear}-12-31` }
    }
    return null
  }, [statsFilter, statsYear])

  useEffect(() => {
    if (!statsRange) return
    exerciseApi.stats(statsRange.start, statsRange.end)
      .then((res) => setStatsPoints(res?.stats || []))
      .catch(() => setStatsPoints([]))
  }, [statsRange])

  const statsChart = useMemo(() => {
    const statMap = new Map(statsPoints.map((p) => [p.date, p]))
    const buckets: Array<{ label: string; calories: number; duration: number; title: string; isToday?: boolean }> = []

    if (statsFilter === 'month') {
      // 最近 12 个月，横轴按月
      const t = new Date()
      for (let i = 11; i >= 0; i--) {
        const d = new Date(t.getFullYear(), t.getMonth() - i, 1)
        const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
        const inMonth = statsPoints.filter((p) => p.date.startsWith(key))
        buckets.push({
          label: `${String(d.getFullYear()).slice(2)}/${String(d.getMonth() + 1).padStart(2, '0')}`,
          calories: Math.round(inMonth.reduce((s, p) => s + p.calories, 0)),
          duration: inMonth.reduce((s, p) => s + p.duration_min, 0),
          title: `${d.getFullYear()}年${d.getMonth() + 1}月`,
        })
      }
    } else {
      // 按年：12 个月柱状，可切任意年份（不限当前年）
      for (let m = 0; m < 12; m++) {
        const key = `${statsYear}-${String(m + 1).padStart(2, '0')}`
        const inMonth = statsPoints.filter((p) => p.date.startsWith(key))
        buckets.push({
          label: `${m + 1}月`,
          calories: Math.round(inMonth.reduce((s, p) => s + p.calories, 0)),
          duration: inMonth.reduce((s, p) => s + p.duration_min, 0),
          title: `${statsYear}年${m + 1}月`,
        })
      }
    }
    const max = Math.max(...buckets.map((b) => b.calories), 100)
    return { buckets, max }
  }, [statsPoints, statsFilter, statsYear])

  // ─── 统计卡渲染数据（周视图取本地聚合，月/年取接口分桶） ───
  const chartBars = statsFilter === 'week'
    ? weekChart.bars
    : statsChart.buckets
  const chartMax = statsFilter === 'week' ? weekChart.max : statsChart.max
  const chartSummary = useMemo(() => ({
    total: chartBars.reduce((s, b) => s + b.calories, 0),
    dur: chartBars.reduce((s, b) => s + b.duration, 0),
  }), [chartBars])
  const chartPeakIdx = useMemo(() => {
    let idx = -1
    let best = 0
    chartBars.forEach((b, i) => {
      if (b.calories > best) {
        best = b.calories
        idx = i
      }
    })
    return idx
  }, [chartBars])

  // ─── 运动计划操作 ───
  const handleAddExercise = async () => {
    if (!selectedExercise) return
    try {
      await exercisePlanApi.add({
        exercise_type: selectedType,
        exercise_name: selectedExercise,
        duration_min: duration,
      })
      await loadPlan()
    } catch {
      // 静默失败
    }
  }

  const handleDeletePlanItem = async (itemId: number) => {
    try {
      await exercisePlanApi.deleteItem(itemId)
      await loadPlan()
    } catch {
      // 静默失败
    }
  }

  const handleConfirmComplete = async () => {
    if (!confirmingPlanItem) return
    setCompletingItemId(confirmingPlanItem.id)
    try {
      const result = await exercisePlanApi.completeItem(confirmingPlanItem.id)
      if (result.success) {
        setConfirmingPlanItem(null)
        await reloadAll()
      }
    } catch {
      // 保留确认弹窗便于重试
    } finally {
      setCompletingItemId(null)
    }
  }

  const handleApplyTemplate = async (templateId: number) => {
    try {
      await workoutApi.applyTemplate(templateId)
      await loadPlan()
    } catch {
      // 静默失败
    }
  }

  const handleDeleteTemplate = async (templateId: number) => {
    try {
      await workoutApi.deleteTemplate(templateId)
      await loadTemplates()
    } catch {
      // 静默失败
    }
  }

  const handleSaveTemplate = async () => {
    if (!templateName.trim() || planSummary.items.length === 0) return
    try {
      await workoutApi.createTemplate({
        template_name: templateName.trim(),
        items: planSummary.items.map((i) => ({
          exercise_name: i.exercise_name,
          exercise_type: i.exercise_type,
          duration_min: i.duration_min,
        })),
      })
      setTemplateName('')
      setShowSaveTemplate(false)
      await loadTemplates()
    } catch {
      // 静默失败
    }
  }

  // ─── 历史记录操作 ───
  const handleDeleteRecord = async (id: number) => {
    try {
      await exerciseApi.deleteRecord(id)
      await reloadAll()
    } catch (err) {
      console.error('删除失败:', err)
    }
  }

  // ─── 日历翻页 ───
  const handlePrevMonth = () => {
    if (calMonth === 0) {
      setCalYear(calYear - 1)
      setCalMonth(11)
    } else {
      setCalMonth(calMonth - 1)
    }
  }

  const handleNextMonth = () => {
    const t = new Date()
    // 不允许翻到未来月份
    if (calYear > t.getFullYear() || (calYear === t.getFullYear() && calMonth >= t.getMonth())) return
    if (calMonth === 11) {
      setCalYear(calYear + 1)
      setCalMonth(0)
    } else {
      setCalMonth(calMonth + 1)
    }
  }

  const handleBackToToday = () => {
    setCalYear(now.getFullYear())
    setCalMonth(now.getMonth())
    setSelectedDate(todayStr())
  }

  const handleDayClick = (d: Date) => {
    const ds = toDateStr(d)
    if (ds > todayStr()) return
    setSelectedDate(ds)
  }

  // ─── 统计筛选 ───
  const handleStatsFilter = (f: StatsFilter) => {
    setStatsFilter(f)
    setHoverBar(null)
    if (f === 'year') setStatsYear(new Date().getFullYear())
  }

  const handlePrevYear = () => setStatsYear(statsYear - 1)
  const handleNextYear = () => {
    if (statsYear < new Date().getFullYear()) setStatsYear(statsYear + 1)
  }

  return (
    <div className="exercise-plan">
      {/* ─── 本周统计 ─── */}
      <div className="exercise-plan__summary card">
        <div className="exercise-summary__item">
          <Dumbbell size={20} className="exercise-summary__icon" />
          <div>
            <span className="exercise-summary__value">{weekStats.count}</span>
            <span className="exercise-summary__label">本周运动(次)</span>
          </div>
        </div>
        <div className="exercise-summary__item">
          <Flame size={20} className="exercise-summary__icon" />
          <div>
            <span className="exercise-summary__value">{weekStats.calories}</span>
            <span className="exercise-summary__label">本周消耗(kcal)</span>
          </div>
        </div>
        <div className="exercise-summary__item">
          <Clock size={20} className="exercise-summary__icon" />
          <div>
            <span className="exercise-summary__value">{weekStats.duration}</span>
            <span className="exercise-summary__label">本周时长(分钟)</span>
          </div>
        </div>
      </div>

      {/* ─── 运动统计（周/月/年，统一的交互与汇总信息） ─── */}
      <div className="exercise-plan__stats card">
        <div className="exercise-stats__header">
          <div className="exercise-trend__header exercise-stats__title">
            <TrendingUp size={16} />
            <span>运动统计</span>
          </div>
          <div className="exercise-stats__filters">
            <div className="ep-tabs ep-tabs--inline">
              {(['week', 'month', 'year'] as StatsFilter[]).map((f) => (
                <button
                  key={f}
                  className={`ep-tab ${statsFilter === f ? 'ep-tab--active' : ''}`}
                  onClick={() => handleStatsFilter(f)}
                >
                  {{ week: '周', month: '月', year: '年' }[f]}
                </button>
              ))}
            </div>
            {statsFilter === 'year' && (
              <div className="exercise-stats__year-nav">
                <button onClick={handlePrevYear} title="上一年">
                  <ChevronLeft size={14} />
                </button>
                <span>{statsYear} 年</span>
                <button onClick={handleNextYear} disabled={statsYear >= now.getFullYear()} title="下一年">
                  <ChevronRight size={14} />
                </button>
              </div>
            )}
          </div>
        </div>
        {/* 汇总/悬停明细行：默认显示合计，悬停某柱时切换为该柱明细 */}
        <div className="exercise-stats__meta">
          <em>
            {statsFilter === 'week' && '本周 · 按天统计'}
            {statsFilter === 'month' && '近 12 个月 · 按月汇总'}
            {statsFilter === 'year' && `${statsYear} 年 · 按月分布`}
          </em>
          <span className="exercise-stats__detail">
            {hoverBar !== null && chartBars[hoverBar]
              ? `${chartBars[hoverBar].title}：${chartBars[hoverBar].calories} kcal · ${chartBars[hoverBar].duration} 分钟`
              : `合计 ${chartSummary.total} kcal · ${chartSummary.dur} 分钟`}
          </span>
        </div>
        <div className="exercise-trend__chart exercise-stats__chart" onMouseLeave={() => setHoverBar(null)}>
          {chartBars.map((b, i) => (
            <div
              key={i}
              className={`exercise-trend__col ${hoverBar === i ? 'exercise-trend__col--active' : ''}`}
              onMouseEnter={() => setHoverBar(i)}
            >
              <div className="exercise-trend__bar-wrap">
                {chartPeakIdx === i && b.calories > 0 && (
                  <span className="exercise-trend__peak">{b.calories}</span>
                )}
                <div
                  className={`exercise-trend__bar ${b.calories <= 0 ? 'exercise-trend__bar--zero' : ''} ${b.isToday ? 'exercise-trend__bar--today' : ''}`}
                  style={b.calories > 0 ? { height: `${Math.max((b.calories / chartMax) * 80, 6)}%` } : undefined}
                />
              </div>
              <span className={`exercise-trend__label ${b.isToday ? 'exercise-trend__label--today' : ''}`}>
                {b.label}
                {b.isToday && <i className="exercise-trend__dot" />}
              </span>
            </div>
          ))}
        </div>
        <div className="exercise-stats__unit">单位：kcal · 悬停柱形查看明细</div>
      </div>

      <div className="exercise-plan__grid">
        {/* ─── 左栏：运动计划板块（复用 AI 助手页） ─── */}
        <div className="exercise-plan__panel card">
          <div className="exercise-form__header">
            <Dumbbell size={16} />
            <span>{todayStr().slice(5)} 运动计划</span>
            {panelTab === 'plan' && planSummary.items.length > 0 && (
              <button
                className="exercise-panel__clear"
                onClick={() => exercisePlanApi.clearToday(userId).then(loadPlan)}
              >
                清空
              </button>
            )}
          </div>

          <div className="ep-tabs" role="tablist" aria-label="运动内容">
            <button
              role="tab"
              aria-selected={panelTab === 'plan'}
              className={`ep-tab ${panelTab === 'plan' ? 'ep-tab--active' : ''}`}
              onClick={() => setPanelTab('plan')}
            >
              <ListChecks size={13} /> 运动计划
            </button>
            <button
              role="tab"
              aria-selected={panelTab === 'burn'}
              className={`ep-tab ${panelTab === 'burn' ? 'ep-tab--active' : ''}`}
              onClick={() => setPanelTab('burn')}
            >
              <Flame size={13} /> 消耗记录
            </button>
          </div>

          {panelTab === 'plan' ? (
            <>
              {/* 快速选择模板 */}
              {templates.length > 0 && (
                <div className="ep-templates">
                  <div className="ep-templates__label">快速选择模板</div>
                  <div className="ep-templates__list">
                    {templates.map((tpl) => (
                      <div key={tpl.id} className="ep-tpl-card">
                        <div className="ep-tpl-card__info" onClick={() => handleApplyTemplate(tpl.id)}>
                          <span className="ep-tpl-card__name">{tpl.template_name}</span>
                          <span className="ep-tpl-card__meta">
                            {tpl.total_duration}min · {Math.round(tpl.estimated_calories)}kcal
                          </span>
                        </div>
                        <button
                          className="ep-tpl-card__delete"
                          onClick={(e) => { e.stopPropagation(); handleDeleteTemplate(tpl.id) }}
                          title="删除模板"
                        >
                          <Trash2 size={11} />
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* 保存为模板 */}
              {planSummary.items.length > 0 && !showSaveTemplate && (
                <button className="btn btn-ghost ep-save-tpl-btn" onClick={() => setShowSaveTemplate(true)}>
                  <Plus size={12} /> 保存为模板
                </button>
              )}
              {showSaveTemplate && (
                <div className="ep-save-tpl-form">
                  <input
                    type="text"
                    placeholder="模板名称，如：减脂有氧日"
                    value={templateName}
                    maxLength={30}
                    onChange={(e) => setTemplateName(e.target.value)}
                  />
                  <div className="ep-save-tpl-actions">
                    <button className="btn btn-primary btn-sm" onClick={handleSaveTemplate} disabled={!templateName.trim()}>
                      保存
                    </button>
                    <button className="btn btn-ghost btn-sm" onClick={() => { setShowSaveTemplate(false); setTemplateName('') }}>
                      取消
                    </button>
                  </div>
                </div>
              )}

              {/* 运动类型 */}
              <div className="ep-types">
                {Object.entries(TYPE_META).map(([key, meta]) => (
                  <button
                    key={key}
                    className={`ep-type-btn ${selectedType === key ? 'ep-type-btn--active' : ''}`}
                    style={selectedType === key ? { background: meta.color, borderColor: meta.color } : undefined}
                    onClick={() => setSelectedType(key)}
                  >
                    {meta.label}
                  </button>
                ))}
              </div>

              {/* 运动选择（含 MET） */}
              <select
                className="ep-select"
                value={selectedExercise}
                onChange={(e) => setSelectedExercise(e.target.value)}
              >
                {typeOptions.length === 0 && <option>加载中...</option>}
                {typeOptions.map((o) => (
                  <option key={o.exercise_name} value={o.exercise_name}>
                    {o.exercise_name}（MET {o.met_value}）
                  </option>
                ))}
              </select>

              {/* 时长滑块 */}
              <div className="ep-slider">
                <div className="ep-slider__header">
                  <span>时长</span>
                  <strong>{duration} 分钟</strong>
                </div>
                <input
                  type="range"
                  min={5}
                  max={120}
                  step={5}
                  value={duration}
                  onChange={(e) => setDuration(Number(e.target.value))}
                />
                <div className="ep-slider__marks">
                  <span>5min</span>
                  <span>60min</span>
                  <span>120min</span>
                </div>
                <div className="ep-slider__calorie">
                  <Flame size={13} />
                  预计消耗 <strong>{estCalories} kcal</strong>
                </div>
              </div>

              {/* 添加到计划 */}
              <button className="btn btn-primary ep-add-btn" onClick={handleAddExercise} disabled={!selectedExercise}>
                <Plus size={14} /> 添加到计划
              </button>

              {/* 计划列表 */}
              {planSummary.items.length > 0 && (
                <div className="ep-plan-list">
                  {planSummary.items.map((item) => (
                    <div key={item.id} className="ep-plan-item">
                      <div className="ep-plan-item__info">
                        <span className="ep-plan-item__dot" style={{ background: typeColor(item.exercise_type) }} />
                        <span className="ep-plan-item__name">{item.exercise_name}</span>
                        <span className="ep-plan-item__duration">{item.duration_min}min</span>
                      </div>
                      <div className="ep-plan-item__right">
                        <span className="ep-plan-item__calories">{Math.round(item.calories_burned)}kcal</span>
                        {item.completed ? (
                          <span className="ep-plan-item__done"><Check size={12} /> 已完成</span>
                        ) : (
                          <>
                            <button className="ep-plan-item__complete" onClick={() => setConfirmingPlanItem(item)}>
                              完成
                            </button>
                            <button
                              className="ep-plan-item__delete"
                              onClick={() => handleDeletePlanItem(item.id)}
                              aria-label={`删除${item.exercise_name}`}
                            >
                              <Trash2 size={12} />
                            </button>
                          </>
                        )}
                      </div>
                    </div>
                  ))}
                  <div className="ep-plan-summary">
                    已完成 {planSummary.completed_count}/{planSummary.item_count} 项 ·
                    消耗 {Math.round(planSummary.total_calories)} kcal
                  </div>
                </div>
              )}
            </>
          ) : (
            /* 消耗记录 */
            <div className="ep-burn-list">
              {loading ? (
                <div className="exercise-records__empty"><Loader2 size={16} className="spin" /> 加载中...</div>
              ) : burnRecords.length === 0 ? (
                <div className="exercise-records__empty">完成运动后，消耗热量会记录在这里。</div>
              ) : (
                burnRecords.slice(0, 30).map((record) => (
                  <div key={record.id} className="ep-burn-item">
                    <div className="ep-burn-item__main">
                      <span className="ep-plan-item__dot" style={{ background: typeColor(record.exercise_type) }} />
                      <div>
                        <div className="ep-burn-item__name">{record.exercise_name}</div>
                        <div className="ep-burn-item__meta">
                          {record.scheduled_date || '今日'} · {record.duration_min || 0} min
                        </div>
                      </div>
                    </div>
                    <div className="ep-burn-item__right">
                      <strong>+{Math.round(record.calories_burned || 0)} kcal</strong>
                      <button className="exercise-record__delete" onClick={() => handleDeleteRecord(record.id)} title="删除">
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </div>
                ))
              )}
            </div>
          )}
        </div>

        {/* ─── 右栏：日历历史 ─── */}
        <div className="exercise-plan__history card">
          <div className="exercise-records__header">
            <History size={16} />
            <span>历史记录</span>
            <em>{calYear}年{calMonth + 1}月 · {monthRecordCount} 天有运动</em>
          </div>

          {/* 日历 */}
          <div className="ep-calendar">
            <div className="ep-calendar__nav">
              <button onClick={handlePrevMonth} title="上一月"><ChevronLeft size={15} /></button>
              <span className="ep-calendar__month">{calYear}年{calMonth + 1}月</span>
              <button onClick={handleNextMonth} disabled={calYear === now.getFullYear() && calMonth === now.getMonth()} title="下一月">
                <ChevronRight size={15} />
              </button>
              <button className="ep-calendar__today" onClick={handleBackToToday}>今天</button>
            </div>
            <div className="ep-calendar__weekdays">
              {WEEK_LABELS.map((w) => <span key={w}>{w}</span>)}
            </div>
            <div className="ep-calendar__grid">
              {monthDays(calYear, calMonth).map(({ date: d, inMonth }, i) => {
                const ds = toDateStr(d)
                const isFuture = ds > todayStr()
                const hasRecord = !!monthRecords[ds]?.length
                const isSelected = ds === selectedDate
                const isToday = ds === todayStr()
                return (
                  <button
                    key={i}
                    className={[
                      'ep-calendar__day',
                      !inMonth && 'ep-calendar__day--other',
                      isFuture && 'ep-calendar__day--future',
                      hasRecord && 'ep-calendar__day--has-record',
                      isSelected && 'ep-calendar__day--selected',
                      isToday && 'ep-calendar__day--today',
                    ].filter(Boolean).join(' ')}
                    disabled={!inMonth || isFuture}
                    onClick={() => handleDayClick(d)}
                  >
                    <span>{d.getDate()}</span>
                    {hasRecord && <i className="ep-calendar__dot" />}
                  </button>
                )
              })}
            </div>
          </div>

          {/* 选中日期的记录 */}
          <div className="ep-day-records">
            <div className="ep-day-records__title">
              <CalendarDays size={14} />
              <span>{selectedDate.replace(/-/g, '/')} 的运动</span>
              <em>{selectedDayRecords.length} 条</em>
            </div>
            {selectedDayRecords.length === 0 ? (
              <div className="exercise-records__empty">这一天还没有运动记录</div>
            ) : (
              <div className="exercise-records__list">
                {selectedDayRecords.map((r) => (
                  <div key={r.id} className="exercise-record__item">
                    <span
                      className="exercise-record__badge"
                      style={{ background: `${typeColor(r.exercise_type)}15`, color: typeColor(r.exercise_type) }}
                    >
                      {typeLabel(r.exercise_type)}
                    </span>
                    <div className="exercise-record__info">
                      <span className="exercise-record__name">{r.exercise_name}</span>
                      <span className="exercise-record__meta">
                        {r.duration_min || 0} 分钟 · {Math.round(r.calories_burned || 0)} kcal
                        {r.recorded_at && ` · ${new Date(r.recorded_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}`}
                      </span>
                      {r.notes && <span className="exercise-record__notes">{r.notes}</span>}
                    </div>
                    <button className="exercise-record__delete" onClick={() => handleDeleteRecord(r.id)} title="删除">
                      <Trash2 size={14} />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ─── 完成计划确认弹窗 ─── */}
      {confirmingPlanItem && (
        <div className="modal-overlay" onClick={() => setConfirmingPlanItem(null)}>
          <div className="modal ep-confirm-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal__header">
              <h3 className="modal__title">确认完成运动？</h3>
              <button className="modal__close" onClick={() => setConfirmingPlanItem(null)}>
                <X size={16} />
              </button>
            </div>
            <div className="modal__body">
              <p className="ep-confirm-modal__text">
                将「{confirmingPlanItem.exercise_name} {confirmingPlanItem.duration_min}min · {Math.round(confirmingPlanItem.calories_burned)}kcal」标记为已完成？
              </p>
              <p className="ep-confirm-modal__hint">确认后实际消耗会写入运动记录，并计入本周消耗统计。</p>
              <div className="takeout-checkout__actions">
                <button className="btn btn-ghost" onClick={() => setConfirmingPlanItem(null)}>
                  取消
                </button>
                <button
                  className="btn btn-primary"
                  onClick={handleConfirmComplete}
                  disabled={completingItemId === confirmingPlanItem.id}
                >
                  {completingItemId === confirmingPlanItem.id
                    ? <Loader2 size={14} className="spin" />
                    : <Check size={14} />}
                  确认完成
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}