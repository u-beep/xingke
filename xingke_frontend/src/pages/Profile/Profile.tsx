import { useState, useEffect, useRef } from 'react'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceDot,
} from 'recharts'
import {
  Weight,
  Percent,
  Dumbbell,
  TrendingUp,
  TrendingDown,
  Sparkles,
  Target,
  CalendarCheck,
  Flame,
  Loader2,
  Pencil,
  User,
  Activity,
  ChevronDown,
} from 'lucide-react'
import { weightApi, profileApi, dashboardApi } from '../../services/api'
import { getAuthUser } from '../../services/authStore'
import './Profile.css'

// ============================================
// 类型与常量
// ============================================

type Dimension = 'weight'

const dimensionConfig: Record<Dimension, { label: string; color: string; unit: string }> = {
weight: { label: '体重', color: '#ffc300', unit: 'kg' },
}

/** 身体数据点（趋势图统一格式） */
interface BodyDataPoint {
  date: string
  /** 完整日期 YYYY-MM-DD，用于月视图按周筛选定位 */
  iso?: string
  weight: number | null
  bodyFat: number | null
  waist: number | null
  hip: number | null
}

const GENDER_LABEL: Record<string, string> = { male: '男', female: '女' }
const GOAL_LABEL: Record<string, string> = {
  lose_weight: '减脂',
  maintain: '保持健康',
  gain_muscle: '增肌',
}

// ============================================
// 主组件
// ============================================

export default function Profile() {
  const authUser = getAuthUser()
  const displayName = authUser?.nickname || authUser?.username || '我'

  // —— 用户资料（后端 /profile/me）——
  const [profile, setProfile] = useState<any>(null)
  // —— 身体指标（最新体重记录优先，可编辑入库）——
  const [bodyMetrics, setBodyMetrics] = useState<{ weight: number | null; bodyFat: number | null }>({
    weight: null,
    bodyFat: null,
  })
  const [bodyExtras, setBodyExtras] = useState<{ waist: number | null; hip: number | null }>({
    waist: null,
    hip: null,
  })
  // —— 体重历史（趋势图数据源）——
  const [history, setHistory] = useState<BodyDataPoint[]>([])
  // —— 本周摘要（后端 /dashboard/weekly-summary）——
  const [weekly, setWeekly] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  // —— 图表状态 ——
  const [selectedDim] = useState<Dimension>('weight')
  // 图表固定为「按周展示」模式：左上年月只负责筛选显示范围，以周为单位选择（默认当前周）
  const [monthCursor, setMonthCursor] = useState<string>(() => toIsoDate(new Date()).slice(0, 7))
  const [weekIndex, setWeekIndex] = useState(0)
  // 下拉筛选器开关（年份 / 月份 / 周）
  const [yearMenuOpen, setYearMenuOpen] = useState(false)
  const [monthMenuOpen, setMonthMenuOpen] = useState(false)
  const [weekMenuOpen, setWeekMenuOpen] = useState(false)

  // 页面加载：并行拉取资料、最新身体数据、周摘要
  useEffect(() => {
    ;(async () => {
      setLoading(true)
      try {
        const [profileRes, latestRes, weeklyRes] = await Promise.all([
          profileApi.me().catch(() => null),
          weightApi.latest().catch(() => null),
          dashboardApi.weeklySummary().catch(() => null),
        ])

        if (profileRes?.profile) setProfile(profileRes.profile)

        const record = latestRes?.record
        if (record) {
          setBodyMetrics({
            weight: Number(record.weight_kg ?? record.weight) || null,
            bodyFat: Number(record.body_fat_pct ?? record.bodyFat) || null,
          })
          setBodyExtras({
            waist: Number(record.waist_cm ?? record.waist) || null,
            hip: Number(record.hip_cm ?? record.hip) || null,
          })
        }

        if (weeklyRes) setWeekly(weeklyRes)
      } finally {
        setLoading(false)
      }
    })()
  }, [])

  // 身体数据就绪后：拉取趋势
  const metricsReady = bodyMetrics.weight !== null
  useEffect(() => {
    if (!metricsReady) return
    fetchHistory()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [metricsReady])

  /** 拉取体重历史并转为趋势图数据（按天数 → 周视图取最近7条，年视图按月聚合） */
  const fetchHistory = async (days: number = 365) => {
    try {
      const res = await weightApi.history(days, 500)
      const records: any[] = (res?.records || []).slice().reverse() // 接口倒序 → 时间升序
      const points: BodyDataPoint[] = records.map((r) => ({
        date: formatDate(r.recorded_at),
        iso: toIsoDate(new Date(r.recorded_at)),
        weight: r.weight_kg != null ? Number(r.weight_kg) : null,
        bodyFat: r.body_fat_pct != null ? Number(r.body_fat_pct) : null,
        waist: r.waist_cm != null ? Number(r.waist_cm) : null,
        hip: r.hip_cm != null ? Number(r.hip_cm) : null,
      }))
      setHistory(points)
    } catch {
      // 静默失败，图表显示空态
    }
  }

  /** 编辑体重/体脂后入库并刷新趋势 */
  const persistBodyRecord = async (patch: { weight?: number; bodyFat?: number }) => {
    const next = {
      weight: patch.weight ?? bodyMetrics.weight ?? null,
      bodyFat: patch.bodyFat ?? bodyMetrics.bodyFat ?? null,
    }
    if (next.weight == null) throw new Error('暂无体重数据，无法保存')
    const result = await weightApi.record({
      weight_kg: next.weight,
      body_fat_pct: next.bodyFat ?? undefined,
      waist_cm: bodyExtras.waist ?? undefined,
      hip_cm: bodyExtras.hip ?? undefined,
    })
    if (!result?.success) throw new Error(result?.message || '保存失败，请稍后重试')
    setBodyMetrics(next)
    fetchHistory()
  }

  const handleSaveWeight = (v: number) => persistBodyRecord({ weight: v })
  /** BMI 是派生值：按身高反推体重后入库 */
  const heightCm = Number(profile?.height_cm) || 0
  const handleSaveBmi = (v: number) => {
    if (!heightCm) throw new Error('资料中暂无身高，请先在对话中完善资料')
    return persistBodyRecord({ weight: +(v * (heightCm / 100) ** 2).toFixed(1) })
  }

  // —— 派生指标 ——
  const heightM = heightCm / 100
  const bmiValue = bodyMetrics.weight && heightM ? (bodyMetrics.weight / (heightM * heightM)).toFixed(1) : '—'
  const bmiLabel = bmiValue === '—' ? '' : bmiCategory(Number(bmiValue))

  // —— 目标进度（真实计算）——
  const targetWeight = Number(profile?.target_weight_kg) || null
  const goalPercent =
    targetWeight && bodyMetrics.weight && history.length > 1
      ? calcGoalPercent(history, bodyMetrics.weight, targetWeight)
      : targetWeight && bodyMetrics.weight
        ? 0
        : null

  // —— 趋势图数据 ——
  // 年月筛选 + 以周为单位选择（默认当前周，可回看历史周），横轴为该周 7 天日期。
  // 体重规则：当天有记录用记录；未修改则当天零点起沿用前一天的值；还没到的天不显示点。
  const monthWeeksList = monthWeeks(Number(monthCursor.slice(0, 4)), Number(monthCursor.slice(5, 7)))
  const todayIso = toIsoDate(new Date())
  const safeWeekIndex = Math.max(0, Math.min(weekIndex, monthWeeksList.length - 1))
  const activeWeek = monthWeeksList[safeWeekIndex]
  const fmtMD = (d: Date) => `${String(d.getMonth() + 1).padStart(2, '0')}/${String(d.getDate()).padStart(2, '0')}`
  const isCurrentWeek = activeWeek
    ? toIsoDate(activeWeek.start) <= todayIso && todayIso <= toIsoDate(activeWeek.end)
    : false

  // 近三年年份列表（供年份下拉）
  const nowYear = new Date().getFullYear()
  const yearOptions = [nowYear, nowYear - 1, nowYear - 2]
  const selectedYear = Number(monthCursor.slice(0, 4))
  const selectedMonth = Number(monthCursor.slice(5, 7))

  const gotoMonth = (ym: string) => {
    setMonthCursor(ym)
    setWeekIndex(defaultWeekIndex(monthWeeks(Number(ym.slice(0, 4)), Number(ym.slice(5, 7))), todayIso))
    setYearMenuOpen(false)
    setMonthMenuOpen(false)
  }

  /** 选择年份：若落到未来月份则钳到今年当月 */
  const selectYear = (year: number) => {
    let month = selectedMonth
    if (`${year}-${String(month).padStart(2, '0')}` > todayIso.slice(0, 7)) {
      month = Number(todayIso.slice(5, 7))
    }
    gotoMonth(`${year}-${String(month).padStart(2, '0')}`)
  }

  const gotoWeek = (idx: number) => {
    const wk = monthWeeksList[idx]
    if (!wk || toIsoDate(wk.end) > todayIso) return // 未来周不可选
    setWeekIndex(idx)
    setWeekMenuOpen(false)
  }

  const chartData: BodyDataPoint[] = []
  if (activeWeek) {
    const byIso = new Map(history.map((p) => [p.iso, p]))
    const weekStartIso = toIsoDate(activeWeek.start)
    // 周开始前最近的一条体重记录，作为周初的沿用基准
    let lastWeight: number | null = null
    for (const p of history) {
      if (p.iso && p.iso < weekStartIso && p.weight != null) lastWeight = p.weight
    }
    const cur = new Date(activeWeek.start)
    for (let i = 0; i < 7; i++) {
      const iso = toIsoDate(cur)
      const src = byIso.get(iso)
      const isFuture = iso > todayIso
      if (src?.weight != null) lastWeight = src.weight
      chartData.push({
        iso,
        date: fmtMD(cur),
        // 未来（还没到的天）不显示；已过去但当天无记录时沿用前一天的体重
        weight: isFuture ? null : (src?.weight ?? lastWeight),
        bodyFat: src?.bodyFat ?? null,
        waist: src?.waist ?? null,
        hip: src?.hip ?? null,
      })
      cur.setDate(cur.getDate() + 1)
    }
  }
  const hasChartData = chartData.some((d) => d[selectedDim] != null)

  return (
    <div className="profile">
      {/* 顶部核心指标卡片 */}
      <div className="profile__metrics-grid">
        <MetricCard
          icon={Weight}
          label="当前体重"
          value={bodyMetrics.weight ?? '—'}
          unit="kg"
          changeLabel="来自最新记录"
          editable={!!bodyMetrics.weight}
          onSave={handleSaveWeight}
        />
        <MetricCard
          icon={Activity}
          label="BMI"
          value={bmiValue}
          unit=""
          changeLabel={bmiLabel || (loading ? '计算中' : '完善身高后计算')}
          editable={!!bodyMetrics.weight && !!heightCm}
          onSave={handleSaveBmi}
        />
        <MetricCard
          icon={Dumbbell}
          label="本周运动"
          value={
            weekly
              ? `${weekly.exercise_count ?? 0}次`
              : loading
                ? '...'
                : '—'
          }
          unit=""
        />
      </div>

      {/* 中下分栏 */}
      <div className="profile__main">
        {/* 左侧：体重趋势图 */}
        <div className="profile__left">
        <div className="profile-chart card">
          <div className="profile-chart__header">
            <div className="profile-chart__dims">
              <span className="profile-chart__title">体重趋势</span>
            </div>
          </div>

          <div className="profile-chart__body">
            {monthWeeksList.length > 0 && activeWeek && (
              <div className="profile-chart__filters">
                <div className="profile-chart__nav">
                  {/* 年份下拉（近三年） */}
                  <div className="profile-chart__select">
                    <button
                      className="profile-chart__nav-label profile-chart__nav-label--clickable"
                      onClick={() => { setYearMenuOpen((o) => !o); setMonthMenuOpen(false); setWeekMenuOpen(false) }}
                    >
                      {selectedYear}年
                      <ChevronDown size={12} className={`profile-chart__select-caret ${yearMenuOpen ? 'profile-chart__select-caret--open' : ''}`} />
                    </button>
                    {yearMenuOpen && (
                      <>
                        <div className="profile-chart__menu-overlay" onClick={() => setYearMenuOpen(false)} />
                        <div className="profile-chart__menu profile-chart__menu--left">
                          {yearOptions.map((year) => (
                            <button
                              key={year}
                              className={`profile-chart__menu-item ${year === selectedYear ? 'profile-chart__menu-item--active' : ''}`}
                              onClick={() => selectYear(year)}
                            >
                              {year}年
                            </button>
                          ))}
                        </div>
                      </>
                    )}
                  </div>
                  {/* 月份下拉 */}
                  <div className="profile-chart__select">
                    <button
                      className="profile-chart__nav-label profile-chart__nav-label--clickable"
                      onClick={() => { setMonthMenuOpen((o) => !o); setYearMenuOpen(false); setWeekMenuOpen(false) }}
                    >
                      {selectedMonth}月
                      <ChevronDown size={12} className={`profile-chart__select-caret ${monthMenuOpen ? 'profile-chart__select-caret--open' : ''}`} />
                    </button>
                    {monthMenuOpen && (
                      <>
                        <div className="profile-chart__menu-overlay" onClick={() => setMonthMenuOpen(false)} />
                        <div className="profile-chart__menu profile-chart__menu--left">
                          {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => {
                            const ym = `${selectedYear}-${String(m).padStart(2, '0')}`
                            const disabled = ym > todayIso.slice(0, 7)
                            return (
                              <button
                                key={m}
                                className={`profile-chart__menu-item ${m === selectedMonth ? 'profile-chart__menu-item--active' : ''} ${disabled ? 'profile-chart__menu-item--disabled' : ''}`}
                                disabled={disabled}
                                onClick={() => gotoMonth(ym)}
                              >
                                {m}月
                              </button>
                            )
                          })}
                        </div>
                      </>
                    )}
                  </div>
                </div>
                <div className="profile-chart__select">
                    <button
                      className={`profile-chart__week-label profile-chart__nav-label--clickable ${isCurrentWeek ? 'profile-chart__week-label--current' : ''}`}
                      title={isCurrentWeek ? '当前周，点击快速选择其他周' : '历史周，点击快速选择'}
                      onClick={() => { setWeekMenuOpen((o) => !o); setYearMenuOpen(false); setMonthMenuOpen(false) }}
                    >
                      第{safeWeekIndex + 1}周 · {fmtMD(activeWeek.start)} – {fmtMD(activeWeek.end)}
                      <ChevronDown size={12} className={`profile-chart__select-caret ${weekMenuOpen ? 'profile-chart__select-caret--open' : ''}`} />
                    </button>
                    {weekMenuOpen && (
                      <>
                        <div className="profile-chart__menu-overlay" onClick={() => setWeekMenuOpen(false)} />
                        <div className="profile-chart__menu profile-chart__menu--right">
                          {monthWeeksList.map((wk, idx) => {
                            const disabled = toIsoDate(wk.end) > todayIso
                            return (
                              <button
                                key={idx}
                                className={`profile-chart__menu-item ${idx === safeWeekIndex ? 'profile-chart__menu-item--active' : ''} ${disabled ? 'profile-chart__menu-item--disabled' : ''}`}
                                disabled={disabled}
                                onClick={() => gotoWeek(idx)}
                              >
                                第{idx + 1}周 · {fmtMD(wk.start)} – {fmtMD(wk.end)}
                                {toIsoDate(wk.start) <= todayIso && todayIso <= toIsoDate(wk.end) ? '（本周）' : ''}
                              </button>
                            )
                          })}
                        </div>
                      </>
                    )}
                  </div>
              </div>
            )}
            {/* 图表固定展示：仅完全没有历史数据时提示录入 */}
            {!loading && history.length === 0 ? (
              <div className="profile-chart__empty">
                <Loader2 size={20} className="spin" />
                <span>暂无趋势数据，点击上方体重卡录入第一条记录</span>
              </div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartData} margin={{ top: 10, right: 20, left: 0, bottom: 10 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0f4f3" vertical={false} />
                  <XAxis
                    dataKey="date"
                    tick={{ fontSize: 12, fill: '#94a6a1' }}
                    axisLine={false}
                    tickLine={false}
                    interval="preserveStartEnd"
                    minTickGap={24}
                  />
                  <YAxis
                    domain={hasChartData ? ['dataMin - 0.5', 'dataMax + 0.5'] : [40, 120]}
                    tick={{ fontSize: 12, fill: '#94a6a1' }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <Tooltip
                    content={({ active, payload, label }: any) => {
                      if (active && payload?.length) {
                        const data = payload[0].payload as BodyDataPoint
                        return (
                          <div className="profile-tooltip">
                            <div className="profile-tooltip__date">{label}</div>
                            <div className="profile-tooltip__row">
                              <span style={{ color: dimensionConfig[selectedDim].color }}>
                                {dimensionConfig[selectedDim].label}
                              </span>
                              <span>
                                {data[selectedDim]}
                                {dimensionConfig[selectedDim].unit}
                              </span>
                            </div>
                          </div>
                        )
                      }
                      return null
                    }}
                  />
                  <Line
                    type="linear"
                    dataKey={selectedDim}
                    stroke={dimensionConfig[selectedDim].color}
                    strokeWidth={2}
                    connectNulls
                    dot={{ r: 3.5, fill: '#fff', stroke: dimensionConfig[selectedDim].color, strokeWidth: 2 }}
                    activeDot={{ r: 5 }}
                  />
                  {(() => {
                    const last = [...chartData].reverse().find((d) => d[selectedDim] != null)
                    if (!last) return null
                    return (
                      <ReferenceDot
                        x={last.date}
                        y={last[selectedDim] as number}
                        r={6}
                        fill={dimensionConfig[selectedDim].color}
                        stroke="#fff"
                        strokeWidth={2}
                      />
                    )
                  })()}
                </LineChart>
              </ResponsiveContainer>
            )}
          </div>

          {/* 图表统计说明（基于当前周内有效数据） */}
          {hasChartData && <ChartSummary data={chartData} dim={selectedDim} />}
        </div>
        </div>

        {/* 右侧信息区 */}
        <div className="profile__sidebar">
          {/* 基本信息 */}
          <div className="profile-card card">
            <div className="profile-card__header">
              <User size={16} /> 基本信息
            </div>
            <div className="profile-card__list">
              <div className="profile-row">
                <span>昵称</span>
                <span>{displayName}</span>
              </div>
              <div className="profile-row">
                <span>性别</span>
                <span>{profile?.gender ? GENDER_LABEL[profile.gender] || profile.gender : '—'}</span>
              </div>
              <div className="profile-row">
                <span>年龄</span>
                <span>{profile?.age ? `${profile.age}岁` : '—'}</span>
              </div>
              <div className="profile-row">
                <span>身高</span>
                <span>{profile?.height_cm ? `${profile.height_cm}cm` : '—'}</span>
              </div>
            </div>
          </div>

          {/* 目标进度 */}
          <div className="profile-card card profile__goal-card">
            <div className="profile-card__header">
              <Target size={16} /> 目标进度
            </div>
            {goalPercent === null ? (
              <p className="profile-card__empty-tip">
                <Sparkles size={12} /> 在对话中告诉 AI 你的目标体重，即可追踪进度
              </p>
            ) : (
              <>
                <div className="goal-ring">
                  <svg viewBox="0 0 140 140" className="goal-ring__svg">
                    <circle cx="70" cy="70" r="58" fill="none" stroke="#fff3c4" strokeWidth="10" />
                    <circle
                      cx="70"
                      cy="70"
                      r="58"
                      fill="none"
                      stroke="url(#profileGoalGradient)"
                      strokeWidth="10"
                      strokeLinecap="round"
                      strokeDasharray={`${(goalPercent / 100) * 364} 364`}
                      transform="rotate(-90 70 70)"
                    />
                    <defs>
                      <linearGradient id="profileGoalGradient" x1="0" y1="0" x2="1" y2="1">
                        <stop offset="0%" stopColor="#ffd84d" />
                        <stop offset="100%" stopColor="#f5a800" />
                      </linearGradient>
                    </defs>
                  </svg>
                  <div className="goal-ring__center">
                    <span className="goal-ring__percent">{goalPercent}%</span>
                    <span className="goal-ring__label">已完成</span>
                  </div>
                </div>
                <div className="goal-info">
                  <div className="goal-info__row">
                    <span>当前体重</span>
                    <span className="goal-info__value">{bodyMetrics.weight} kg</span>
                  </div>
                  <div className="goal-info__row">
                    <span>目标体重</span>
                    <span className="goal-info__value">{targetWeight} kg</span>
                  </div>
                  <div className="goal-info__row">
                    <span>还需减重</span>
                    <span className="goal-info__value goal-info__value--accent">
                      {targetWeight != null ? `${Math.max(0, +((bodyMetrics.weight ?? 0) - targetWeight).toFixed(1))} kg` : '—'}
                    </span>
                  </div>
                </div>
              </>
            )}
          </div>

          {/* 本周数据摘要（真实接口） */}
          <div className="profile-card card">
            <div className="profile-card__header">
              <CalendarCheck size={16} /> 本周数据摘要
            </div>
            <div className="summary-grid">
              <div className="summary-item">
                <Flame size={18} className="summary-item__icon" />
                <span className="summary-item__value">{weekly?.avg_calorie_intake ?? '—'}</span>
                <span className="summary-item__label">日均摄入(kcal)</span>
              </div>
              <div className="summary-item">
                <Dumbbell size={18} className="summary-item__icon" />
                <span className="summary-item__value">{weekly?.exercise_count ?? '—'}</span>
                <span className="summary-item__label">运动次数</span>
              </div>
              <div className="summary-item">
                <TrendingDown size={18} className="summary-item__icon" />
                <span className="summary-item__value">{weekly?.weight_change ?? '—'}</span>
                <span className="summary-item__label">体重变化(kg)</span>
              </div>
              <div className="summary-item">
                <Percent size={18} className="summary-item__icon" />
                <span className="summary-item__value">{weekly ? `${weekly.diet_check_in_rate}%` : '—'}</span>
                <span className="summary-item__label">饮食打卡率</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

// ============================================
// 子组件
// ============================================

/** 图表统计说明 */
function ChartSummary({ data, dim }: { data: BodyDataPoint[]; dim: Dimension }) {
  const unit = dimensionConfig[dim].unit
  const values = data.map((d) => d[dim]).filter((v): v is number => v != null)
  if (values.length === 0) return null
  const maxValue = Math.max(...values)
  const minValue = Math.min(...values)
  const avgValue = (values.reduce((a, b) => a + b, 0) / values.length).toFixed(1)
  const totalChange = (values[values.length - 1] - values[0]).toFixed(1)

  return (
    <div className="profile-chart__summary">
      <div className="profile-chart__summary-item">
        <span className="profile-chart__summary-label">最高值</span>
        <span className="profile-chart__summary-value">
          {maxValue} {unit}
        </span>
      </div>
      <div className="profile-chart__summary-item">
        <span className="profile-chart__summary-label">最低值</span>
        <span className="profile-chart__summary-value">
          {minValue} {unit}
        </span>
      </div>
      <div className="profile-chart__summary-item">
        <span className="profile-chart__summary-label">平均值</span>
        <span className="profile-chart__summary-value">
          {avgValue} {unit}
        </span>
      </div>
      <div className="profile-chart__summary-item">
        <span className="profile-chart__summary-label">整体变化</span>
        <span
          className={`profile-chart__summary-value ${Number(totalChange) <= 0 ? 'profile-chart__summary-value--down' : 'profile-chart__summary-value--up'}`}
        >
          {Number(totalChange) > 0 ? '+' : ''}
          {totalChange} {unit}
        </span>
      </div>
    </div>
  )
}

/** 指标卡片（点击数值内联编辑，保存后入库；无 footer 信息时不渲染底栏） */
function MetricCard({
  icon: Icon,
  label,
  value,
  unit,
  change,
  changeLabel,
  editable = false,
  onSave,
}: {
  icon: any
  label: string
  value: number | string
  unit: string
  change?: number
  changeLabel?: string
  editable?: boolean
  onSave?: (newValue: number) => Promise<void>
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [saving, setSaving] = useState(false)
  const skipCommitRef = useRef(false)

  const startEdit = () => {
    if (!editable || saving) return
    skipCommitRef.current = false
    setDraft(String(value))
    setEditing(true)
  }

  const commit = async () => {
    if (!editing) return
    if (skipCommitRef.current) {
      skipCommitRef.current = false
      setEditing(false)
      return
    }
    const parsed = parseFloat(draft)
    if (isNaN(parsed) || parsed <= 0 || parsed === Number(value)) {
      setEditing(false)
      return
    }
    if (!onSave) {
      setEditing(false)
      return
    }
    setSaving(true)
    try {
      await onSave(parsed)
      setEditing(false)
    } catch (err: any) {
      alert(err?.message || '保存失败，请稍后重试')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="metric-card card">
      <div className="metric-card__icon">
        <Icon size={18} />
      </div>
      <div className="metric-card__body">
        <span className="metric-card__label">{label}</span>
        <div
          className={`metric-card__value-row ${editable ? 'metric-card__value-row--editable' : ''}`}
          onClick={startEdit}
          title={editable ? '点击修改，保存后实时同步' : undefined}
        >
          {editing ? (
            <input
              className="metric-card__edit-input"
              type="number"
              step="0.1"
              min="0"
              value={draft}
              autoFocus
              disabled={saving}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') commit()
                else if (e.key === 'Escape') {
                  skipCommitRef.current = true
                  setEditing(false)
                }
              }}
              onBlur={commit}
              onClick={(e) => e.stopPropagation()}
            />
          ) : (
            <>
              <span className="metric-card__value">{saving ? '保存中...' : value}</span>
              {unit && <span className="metric-card__unit">{unit}</span>}
              {editable && !saving && <Pencil size={12} className="metric-card__edit-icon" />}
            </>
          )}
        </div>
        {(change !== undefined && change !== 0) || changeLabel ? (
          <div className="metric-card__footer">
            {change !== undefined && change !== 0 ? (
              <span
                className={`metric-card__change ${change > 0 ? 'metric-card__change--up' : 'metric-card__change--down'}`}
              >
                {change > 0 ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
                {change > 0 ? '+' : ''}
                {change}
              </span>
            ) : null}
            {changeLabel && <span className="metric-card__change-label">{changeLabel}</span>}
          </div>
        ) : null}
      </div>
    </div>
  )
}

// ============================================
// 工具函数
// ============================================

/** BMI 分类（中国标准） */
function bmiCategory(bmi: number): string {
  if (bmi < 18.5) return '偏瘦'
  if (bmi < 24) return '正常'
  if (bmi < 28) return '超重'
  return '肥胖'
}

/** ISO 时间 → MM/DD */
function formatDate(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  return `${String(d.getMonth() + 1).padStart(2, '0')}/${String(d.getDate()).padStart(2, '0')}`
}

/** Date → 本地时区 YYYY-MM-DD */
function toIsoDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/** 给定年月，返回覆盖该月所有日期的周区间列表（周一为一周起点，首尾周可跨月） */
function monthWeeks(year: number, month: number): Array<{ start: Date; end: Date }> {
  const monthEnd = new Date(year, month, 0) // 该月最后一天
  const weeks: Array<{ start: Date; end: Date }> = []
  const cur = new Date(year, month - 1, 1)
  cur.setDate(cur.getDate() - ((cur.getDay() + 6) % 7)) // 回退到周一
  while (cur <= monthEnd) {
    const start = new Date(cur)
    const end = new Date(cur)
    end.setDate(end.getDate() + 6)
    weeks.push({ start, end })
    cur.setDate(cur.getDate() + 7)
  }
  return weeks
}

/** 默认选中的周：今天所在周；今天不在该月内时，过去月取最后一周，未来月取第一周 */
function defaultWeekIndex(weeks: Array<{ start: Date; end: Date }>, todayIso: string): number {
  for (let i = 0; i < weeks.length; i++) {
    const s = toIsoDate(weeks[i].start)
    const e = toIsoDate(weeks[i].end)
    if (s <= todayIso && todayIso <= e) return i
  }
  return toIsoDate(weeks[weeks.length - 1].start) <= todayIso ? weeks.length - 1 : 0
}

/** 目标进度百分比：基于历史最早体重 → 当前体重的减重进度 */
function calcGoalPercent(history: BodyDataPoint[], current: number, target: number): number {
  const start = history.find((p) => p.weight != null)?.weight
  if (start == null || start === target) return 0
  const progress = (start - current) / (start - target)
  return Math.max(0, Math.min(100, Math.round(progress * 100)))
}
