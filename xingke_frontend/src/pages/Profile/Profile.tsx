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
} from 'lucide-react'
import { toolsApi, weightApi, profileApi, dashboardApi } from '../../services/api'
import { getAuthUser } from '../../services/authStore'
import './Profile.css'

// ============================================
// 类型与常量
// ============================================

type Dimension = 'weight' | 'bodyFat' | 'waist' | 'hip'
type TimeRange = 'week' | 'month' | 'year'

const dimensionConfig: Record<Dimension, { label: string; color: string; unit: string }> = {
  weight: { label: '体重', color: '#ffc300', unit: 'kg' },
  bodyFat: { label: '体脂率', color: '#f59e0b', unit: '%' },
  waist: { label: '腰围', color: '#3b82f6', unit: 'cm' },
  hip: { label: '臀围', color: '#ec4899', unit: 'cm' },
}

const rangeDays: Record<TimeRange, number> = { week: 7, month: 30, year: 365 }

/** 身体数据点（趋势图统一格式） */
interface BodyDataPoint {
  date: string
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
  // —— 计算指标 ——
  const [bmrData, setBmrData] = useState<any>(null)
  const [tdeeData, setTdeeData] = useState<any>(null)
  // —— 本周摘要（后端 /dashboard/weekly-summary）——
  const [weekly, setWeekly] = useState<any>(null)
  // —— AI 解读 ——
  const [aiAnalysis, setAiAnalysis] = useState<string>('')
  const [analyzing, setAnalyzing] = useState(false)
  const [loading, setLoading] = useState(true)

  // —— 图表状态 ——
  const [selectedDim, setSelectedDim] = useState<Dimension>('weight')
  const [timeRange, setTimeRange] = useState<TimeRange>('month')

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

  // 身体数据就绪后：拉趋势 + 算 BMR/TDEE
  const metricsReady = bodyMetrics.weight !== null
  useEffect(() => {
    if (!metricsReady) return
    fetchHistory()
    fetchMetrics()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [metricsReady])

  /** 拉取体重历史并转为趋势图数据（按天数 → 周视图取最近7条，年视图按月聚合） */
  const fetchHistory = async (days: number = 365) => {
    try {
      const res = await weightApi.history(days, 500)
      const records: any[] = (res?.records || []).slice().reverse() // 接口倒序 → 时间升序
      const points: BodyDataPoint[] = records.map((r) => ({
        date: formatDate(r.recorded_at),
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

  /** 计算 BMR/TDEE（依赖资料中的身高/年龄/性别 + 当前体重） */
  const fetchMetrics = async (weight?: number) => {
    const w = weight ?? bodyMetrics.weight ?? undefined
    const height = profile?.height_cm ?? undefined
    if (!w || !height) return
    try {
      const bmr = await toolsApi.calculateBMR({
        gender: profile?.gender || 'male',
        age: profile?.age ?? undefined,
        weight: w,
        height,
      }).catch(() => null)
      if (bmr) {
        setBmrData(bmr)
        const bmrVal = typeof bmr === 'object' ? bmr.bmr ?? bmr.value : null
        if (bmrVal) {
          const tdee = await toolsApi.calculateTDEE({
            bmr: Number(bmrVal),
            activity_level: 'moderate',
          }).catch(() => null)
          if (tdee) setTdeeData(tdee)
        }
      }
    } catch {
      // 计算失败保持占位
    }
  }

  /** 编辑体重/体脂后入库并刷新派生指标 */
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
    fetchMetrics(next.weight)
    fetchHistory()
  }

  const handleSaveWeight = (v: number) => persistBodyRecord({ weight: v })
  const handleSaveBodyFat = (v: number) => persistBodyRecord({ bodyFat: v })
  /** BMI 是派生值：按身高反推体重后入库 */
  const heightCm = Number(profile?.height_cm) || 0
  const handleSaveBmi = (v: number) => {
    if (!heightCm) throw new Error('资料中暂无身高，请先在对话中完善资料')
    return persistBodyRecord({ weight: +(v * (heightCm / 100) ** 2).toFixed(1) })
  }

  /** AI 解读：喂真实体重/体脂历史 */
  const handleAnalyzeBody = async () => {
    setAnalyzing(true)
    try {
      const recent = history.slice(-14)
      const weightRecords = recent
        .filter((d) => d.weight != null)
        .map((d) => ({ date: d.date, weight: d.weight }))
      const bodyFatRecords = recent
        .filter((d) => d.bodyFat != null)
        .map((d) => ({ date: d.date, bodyFat: d.bodyFat }))

      const result = await toolsApi.analyzeBody(
        { weight_records: weightRecords, body_fat_records: bodyFatRecords },
        {
          goal: GOAL_LABEL[profile?.health_goal] || '减脂',
          target_weight: Number(profile?.target_weight_kg) || 0,
        },
      )
      const text =
        typeof result === 'string'
          ? result
          : result?.content || result?.response || result?.analysis || JSON.stringify(result, null, 2)
      setAiAnalysis(text)
    } catch {
      setAiAnalysis('分析服务暂时不可用，请稍后再试。')
    } finally {
      setAnalyzing(false)
    }
  }

  // —— 派生指标 ——
  const heightM = heightCm / 100
  const bmiValue = bodyMetrics.weight && heightM ? (bodyMetrics.weight / (heightM * heightM)).toFixed(1) : '—'
  const bmiLabel = bmiValue === '—' ? '' : bmiCategory(Number(bmiValue))
  const bmrValue = bmrData ? (bmrData.bmr ?? bmrData.value ?? '—') : '—'
  const tdeeValue = tdeeData ? (tdeeData.tdee ?? tdeeData.value ?? '—') : '—'

  // —— 目标进度（真实计算）——
  const targetWeight = Number(profile?.target_weight_kg) || null
  const goalPercent =
    targetWeight && bodyMetrics.weight && history.length > 1
      ? calcGoalPercent(history, bodyMetrics.weight, targetWeight)
      : targetWeight && bodyMetrics.weight
        ? 0
        : null

  // —— 趋势图数据（按时间范围裁剪）——
  const chartData = sliceByRange(history, timeRange)

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
          icon={Percent}
          label="体脂率"
          value={bodyMetrics.bodyFat ?? '—'}
          unit="%"
          changeLabel="来自最新记录"
          editable={!!bodyMetrics.bodyFat}
          onSave={handleSaveBodyFat}
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
          changeLabel="已完成"
          extra={weekly ? `${Math.round(weekly.weight_change ?? 0)}kg 体重变化` : undefined}
        />
      </div>

      {/* 中下分栏 */}
      <div className="profile__main">
        {/* 左侧：趋势图 + AI 解读 */}
        <div className="profile__left">
        <div className="profile-chart card">
          <div className="profile-chart__header">
            <div className="profile-chart__dims">
              {(Object.keys(dimensionConfig) as Dimension[]).map((dim) => (
                <button
                  key={dim}
                  className={`profile-chart__dim ${selectedDim === dim ? 'profile-chart__dim--active' : ''}`}
                  style={
                    selectedDim === dim
                      ? { borderColor: dimensionConfig[dim].color, color: dimensionConfig[dim].color }
                      : {}
                  }
                  onClick={() => setSelectedDim(dim)}
                >
                  {dimensionConfig[dim].label}
                </button>
              ))}
            </div>
            <div className="profile-chart__range">
              {(['week', 'month', 'year'] as TimeRange[]).map((r) => (
                <button
                  key={r}
                  className={`profile-chart__range-btn ${timeRange === r ? 'profile-chart__range-btn--active' : ''}`}
                  onClick={() => setTimeRange(r)}
                >
                  {r === 'week' ? '周' : r === 'month' ? '月' : '年'}
                </button>
              ))}
            </div>
          </div>

          <div className="profile-chart__body">
            {chartData.length === 0 ? (
              <div className="profile-chart__empty">
                <Loader2 size={20} className="spin" />
                <span>{loading ? '加载中...' : '暂无趋势数据，点击上方体重/体脂录入第一条记录'}</span>
              </div>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartData} margin={{ top: 10, right: 20, left: 0, bottom: 10 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0f4f3" vertical={false} />
                  <XAxis
                    dataKey="date"
                    tick={{ fontSize: 12, fill: '#94a6a1' }}
                    axisLine={{ stroke: '#e8edec' }}
                    tickLine={false}
                    interval="preserveStartEnd"
                    minTickGap={24}
                  />
                  <YAxis
                    domain={['dataMin - 0.5', 'dataMax + 0.5']}
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
                    type="monotone"
                    dataKey={selectedDim}
                    stroke={dimensionConfig[selectedDim].color}
                    strokeWidth={2.5}
                    connectNulls
                    dot={{ r: 4, fill: '#fff', stroke: dimensionConfig[selectedDim].color, strokeWidth: 2 }}
                    activeDot={{ r: 6 }}
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

          {/* 图表统计说明（基于当前范围内有效数据） */}
          {chartData.length > 0 && <ChartSummary data={chartData} dim={selectedDim} />}
        </div>

        {/* AI 解读（横向紧凑，与图表同列填满剩余高度） */}
        <div className="profile-card profile-card--ai card profile__ai-card">
          <div className="profile-card__header">
            <Sparkles size={16} /> AI 解读
          </div>
          <p className="ai-summary">
            {aiAnalysis || '基于你的真实身体数据记录，AI 将给出阶段性分析与建议。'}
          </p>
          <div className="profile-ai__actions">
            <button
              className="btn btn-primary profile-ai-btn"
              onClick={handleAnalyzeBody}
              disabled={analyzing || history.length === 0}
            >
              {analyzing ? <Loader2 size={16} className="spin" /> : <Sparkles size={16} />}
              {analyzing ? '分析中...' : 'AI 分析我的数据'}
            </button>
            {history.length === 0 && (
              <p className="profile-card__empty-tip">录入体重记录后可使用 AI 分析</p>
            )}
          </div>
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
              <div className="profile-row">
                <span>腰围</span>
                <span>{bodyExtras.waist ? `${bodyExtras.waist}cm` : '—'}</span>
              </div>
              <div className="profile-row">
                <span>臀围</span>
                <span>{bodyExtras.hip ? `${bodyExtras.hip}cm` : '—'}</span>
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
                  <div className="goal-info__row">
                    <span>基础代谢 (BMR)</span>
                    <span className="goal-info__value">{bmrValue === '—' ? '—' : `${bmrValue} kcal`}</span>
                  </div>
                  <div className="goal-info__row">
                    <span>每日消耗 (TDEE)</span>
                    <span className="goal-info__value">{tdeeValue === '—' ? '—' : `${tdeeValue} kcal`}</span>
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

/** 指标卡片（点击数值内联编辑，保存后入库） */
function MetricCard({
  icon: Icon,
  label,
  value,
  unit,
  change,
  changeLabel,
  extra,
  editable = false,
  onSave,
}: {
  icon: any
  label: string
  value: number | string
  unit: string
  change?: number
  changeLabel: string
  extra?: string
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
          <span className="metric-card__change-label">{changeLabel}</span>
          {extra && <span className="metric-card__extra">{extra}</span>}
        </div>
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

/** 按时间范围裁剪图表数据（week=最近7点，month=最近30点，year=按月聚合均值） */
function sliceByRange(points: BodyDataPoint[], range: TimeRange): BodyDataPoint[] {
  if (points.length === 0) return []
  if (range === 'week') return points.slice(-7)
  if (range === 'month') return points.slice(-30)
  // year: 按月份聚合
  const monthly = new Map<string, BodyDataPoint[]>()
  for (const p of points) {
    // date 格式 MM/DD，无法区分年份 → 用解析原始 ISO 兜底
    const key = p.date.slice(0, 5)
    if (!monthly.has(key)) monthly.set(key, [])
    monthly.get(key)!.push(p)
  }
  // 近 12 个月
  const keys = [...monthly.keys()].slice(-12)
  return keys.map((k) => {
    const group = monthly.get(k)!
    const avg = (field: 'weight' | 'bodyFat' | 'waist' | 'hip') => {
      const vals = group.map((g) => g[field]).filter((v): v is number => v != null)
      return vals.length ? +(vals.reduce((a, b) => a + b, 0) / vals.length).toFixed(1) : null
    }
    return { date: k, weight: avg('weight'), bodyFat: avg('bodyFat'), waist: avg('waist'), hip: avg('hip') }
  })
}

/** 目标进度百分比：基于历史最早体重 → 当前体重的减重进度 */
function calcGoalPercent(history: BodyDataPoint[], current: number, target: number): number {
  const start = history.find((p) => p.weight != null)?.weight
  if (start == null || start === target) return 0
  const progress = (start - current) / (start - target)
  return Math.max(0, Math.min(100, Math.round(progress * 100)))
}
