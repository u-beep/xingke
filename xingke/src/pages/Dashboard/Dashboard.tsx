import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
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
  HeartPulse,
  Dumbbell,
  TrendingUp,
  TrendingDown,
  Download,
  Sparkles,
  Target,
  CalendarCheck,
  Flame,
  ChevronDown,
  Loader2,
} from 'lucide-react'
import { mockWeightData, mockDashboardMetrics, mockWeeklySummary, mockGoalProgress } from '../../data/mockData'
import { toolsApi } from '../../services/api'
import './Dashboard.css'

type Dimension = 'weight' | 'bodyFat' | 'waist' | 'hip'
type TimeRange = 'week' | 'month' | 'year'

const dimensionConfig: Record<Dimension, { label: string; color: string; unit: string }> = {
  weight: { label: '体重', color: '#ffc300', unit: 'kg' },
  bodyFat: { label: '体脂率', color: '#f59e0b', unit: '%' },
  waist: { label: '腰围', color: '#3b82f6', unit: 'cm' },
  hip: { label: '臀围', color: '#ec4899', unit: 'cm' },
}

const USER_PROFILE = {
  gender: 'male',
  age: 28,
  weight: 71.5,
  height: 175,
  targetWeight: 68.0,
}

export default function Dashboard() {
  const navigate = useNavigate()
  const [selectedDims, setSelectedDims] = useState<Dimension[]>(['weight'])
  const [timeRange, setTimeRange] = useState<TimeRange>('week')

  // API 数据状态
  const [bmiData, setBmiData] = useState<any>(null)
  const [bmrData, setBmrData] = useState<any>(null)
  const [tdeeData, setTdeeData] = useState<any>(null)
  const [aiAnalysis, setAiAnalysis] = useState<string>('')
  const [analyzing, setAnalyzing] = useState(false)
  const [loading, setLoading] = useState(true)

  const toggleDimension = (dim: Dimension) => {
    setSelectedDims((prev) =>
      prev.includes(dim) ? prev.filter((d) => d !== dim) : [...prev, dim]
    )
  }

  // 页面加载时获取 BMI、BMR、TDEE
  useEffect(() => {
    fetchMetrics()
  }, [])

  const fetchMetrics = async () => {
    setLoading(true)
    try {
      const [bmi, bmr] = await Promise.all([
        toolsApi.calculateBMI({
          weight: USER_PROFILE.weight,
          height: USER_PROFILE.height,
        }).catch(() => null),
        toolsApi.calculateBMR({
          gender: USER_PROFILE.gender,
          age: USER_PROFILE.age,
          weight: USER_PROFILE.weight,
          height: USER_PROFILE.height,
        }).catch(() => null),
      ])

      if (bmi) setBmiData(bmi)
      if (bmr) {
        setBmrData(bmr)
        // 用 BMR 计算 TDEE
        try {
          const tdee = await toolsApi.calculateTDEE({
            bmr: typeof bmr === 'object' ? (bmr.bmr || bmr.value || 1680) : 1680,
            activity_level: 'moderate',
          })
          if (tdee) setTdeeData(tdee)
        } catch {}
      }
    } finally {
      setLoading(false)
    }
  }

  // AI 分析本周数据
  const handleAnalyzeBody = async (mode: 'navigate' | 'sidebar') => {
    if (mode === 'navigate') {
      navigate('/')
      return
    }

    setAnalyzing(true)
    try {
      const weightRecords = mockWeightData.map((d) => ({
        date: d.date,
        weight: d.weight,
      }))
      const bodyFatRecords = mockWeightData.map((d) => ({
        date: d.date,
        bodyFat: d.bodyFat,
      }))

      const result = await toolsApi.analyzeBody(
        { weight_records: weightRecords, body_fat_records: bodyFatRecords },
        { goal: '减脂', target_weight: USER_PROFILE.targetWeight }
      )

      const text = typeof result === 'string'
        ? result
        : (result.content || result.response || result.analysis || JSON.stringify(result, null, 2))
      setAiAnalysis(text)
    } catch (err) {
      setAiAnalysis('分析服务暂时不可用，请稍后再试。')
    } finally {
      setAnalyzing(false)
    }
  }

  const weights = mockWeightData.map((d) => d.weight)
  const maxWeight = Math.max(...weights)
  const minWeight = Math.min(...weights)
  const avgWeight = (weights.reduce((a, b) => a + b, 0) / weights.length).toFixed(1)
  const totalChange = (weights[weights.length - 1] - weights[0]).toFixed(1)

  // 合并 API 和 mock 数据
  const bmiValue = bmiData
    ? (bmiData.bmi ?? bmiData.value ?? bmiData.BMI ?? mockDashboardMetrics.bmi.value)
    : mockDashboardMetrics.bmi.value
  const bmiLabel = bmiData
    ? (bmiData.category ?? bmiData.label ?? bmiData.status ?? mockDashboardMetrics.bmi.label)
    : mockDashboardMetrics.bmi.label
  const bmrValue = bmrData
    ? (bmrData.bmr ?? bmrData.value ?? '—')
    : '—'
  const tdeeValue = tdeeData
    ? (tdeeData.tdee ?? tdeeData.value ?? '—')
    : '—'

  return (
    <div className="dashboard">
      {/* 顶部核心指标卡片矩阵 */}
      <div className="metrics-grid">
        <MetricCard
          icon={Weight}
          label="当前体重"
          value={mockDashboardMetrics.weight.value}
          unit={mockDashboardMetrics.weight.unit}
          change={mockDashboardMetrics.weight.change}
          changeLabel={mockDashboardMetrics.weight.label}
        />
        <MetricCard
          icon={Percent}
          label="体脂率"
          value={mockDashboardMetrics.bodyFat.value}
          unit={mockDashboardMetrics.bodyFat.unit}
          change={mockDashboardMetrics.bodyFat.change}
          changeLabel={mockDashboardMetrics.bodyFat.label}
        />
        <MetricCard
          icon={HeartPulse}
          label="BMI"
          value={loading ? '...' : bmiValue}
          unit=""
          change={0}
          changeLabel={loading ? '计算中' : String(bmiLabel)}
          status="normal"
        />
        <MetricCard
          icon={Dumbbell}
          label="本周运动"
          value={`${mockDashboardMetrics.exercise.count}/${mockDashboardMetrics.exercise.total}`}
          unit="次"
          changeLabel={mockDashboardMetrics.exercise.label}
          extra={`${mockDashboardMetrics.exercise.calories} kcal消耗`}
        />
      </div>

      {/* 中下分栏 */}
      <div className="dashboard__main">
        {/* 左侧趋势图 */}
        <div className="dashboard__chart card">
          <div className="chart-header">
            <div className="chart-dims">
              {(Object.keys(dimensionConfig) as Dimension[]).map((dim) => (
                <button
                  key={dim}
                  className={`chart-dim ${selectedDims.includes(dim) ? 'chart-dim--active' : ''}`}
                  style={selectedDims.includes(dim) ? { borderColor: dimensionConfig[dim].color, color: dimensionConfig[dim].color } : {}}
                  onClick={() => toggleDimension(dim)}
                >
                  {dimensionConfig[dim].label}
                </button>
              ))}
            </div>
            <div className="chart-controls">
              <div className="chart-range">
                {(['week', 'month', 'year'] as TimeRange[]).map((r) => (
                  <button
                    key={r}
                    className={`chart-range-btn ${timeRange === r ? 'chart-range-btn--active' : ''}`}
                    onClick={() => setTimeRange(r)}
                  >
                    {r === 'week' ? '周' : r === 'month' ? '月' : '年'}
                  </button>
                ))}
              </div>
              <button className="chart-export">
                <Download size={14} /> 导出
              </button>
            </div>
          </div>

          <div className="chart-body">
            <ResponsiveContainer width="100%" height={320}>
              <LineChart
                data={mockWeightData}
                margin={{ top: 10, right: 20, left: 0, bottom: 10 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f4f3" vertical={false} />
                <XAxis
                  dataKey="date"
                  tick={{ fontSize: 12, fill: '#94a6a1' }}
                  axisLine={{ stroke: '#e8edec' }}
                  tickLine={false}
                />
                <YAxis
                  domain={['dataMin - 0.5', 'dataMax + 0.5']}
                  tick={{ fontSize: 12, fill: '#94a6a1' }}
                  axisLine={false}
                  tickLine={false}
                />
                <Tooltip
                  content={({ active, payload, label }) => {
                    if (active && payload && payload.length) {
                      const data = payload[0].payload
                      return (
                        <div className="chart-tooltip">
                          <div className="chart-tooltip__date">{label}</div>
                          {selectedDims.map((dim) => (
                            <div key={dim} className="chart-tooltip__row">
                              <span style={{ color: dimensionConfig[dim].color }}>
                                {dimensionConfig[dim].label}
                              </span>
                              <span>
                                {data[dim]}{dimensionConfig[dim].unit}
                              </span>
                            </div>
                          ))}
                          <div className="chart-tooltip__row chart-tooltip__row--sub">
                            <span>BMR</span>
                            <span>{bmrValue} kcal</span>
                          </div>
                          <div className="chart-tooltip__row chart-tooltip__row--sub">
                            <span>TDEE</span>
                            <span>{tdeeValue} kcal</span>
                          </div>
                        </div>
                      )
                    }
                    return null
                  }}
                />
                {selectedDims.map((dim) => (
                  <Line
                    key={dim}
                    type="monotone"
                    dataKey={dim}
                    stroke={dimensionConfig[dim].color}
                    strokeWidth={2.5}
                    dot={{ r: 4, fill: '#fff', stroke: dimensionConfig[dim].color, strokeWidth: 2 }}
                    activeDot={{ r: 6 }}
                  />
                ))}
                {/* 里程碑节点 */}
                <ReferenceDot x="08/11" y={71.5} r={6} fill="#ffc300" stroke="#fff" strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          </div>

          {/* 图表数据说明 */}
          <div className="chart-summary">
            <div className="chart-summary__item">
              <span className="chart-summary__label">最高值</span>
              <span className="chart-summary__value">{maxWeight} kg</span>
            </div>
            <div className="chart-summary__item">
              <span className="chart-summary__label">最低值</span>
              <span className="chart-summary__value">{minWeight} kg</span>
            </div>
            <div className="chart-summary__item">
              <span className="chart-summary__label">平均值</span>
              <span className="chart-summary__value">{avgWeight} kg</span>
            </div>
            <div className="chart-summary__item">
              <span className="chart-summary__label">整体变化</span>
              <span className="chart-summary__value chart-summary__value--down">{totalChange} kg</span>
            </div>
          </div>
        </div>

        {/* 右侧信息区 */}
        <div className="dashboard__sidebar">
          {/* 目标进度 */}
          <div className="side-module card">
            <div className="side-module__header">
              <Target size={16} />
              <span>目标进度</span>
            </div>
            <div className="goal-ring">
              <svg viewBox="0 0 140 140" className="goal-ring__svg">
                <circle cx="70" cy="70" r="58" fill="none" stroke="#fff3c4" strokeWidth="10" />
                <circle
                  cx="70"
                  cy="70"
                  r="58"
                  fill="none"
                  stroke="url(#goalGradient)"
                  strokeWidth="10"
                  strokeLinecap="round"
                  strokeDasharray={`${(mockGoalProgress.percentage / 100) * 364} 364`}
                  transform="rotate(-90 70 70)"
                />
                <defs>
                  <linearGradient id="goalGradient" x1="0" y1="0" x2="1" y2="1">
                    <stop offset="0%" stopColor="#ffd84d" />
                    <stop offset="100%" stopColor="#f5a800" />
                  </linearGradient>
                </defs>
              </svg>
              <div className="goal-ring__center">
                <span className="goal-ring__percent">{mockGoalProgress.percentage}%</span>
                <span className="goal-ring__label">已完成</span>
              </div>
            </div>
            <div className="goal-info">
              <div className="goal-info__row">
                <span>当前体重</span>
                <span className="goal-info__value">{mockGoalProgress.currentWeight} kg</span>
              </div>
              <div className="goal-info__row">
                <span>目标体重</span>
                <span className="goal-info__value">{mockGoalProgress.targetWeight} kg</span>
              </div>
              <div className="goal-info__row">
                <span>还需减重</span>
                <span className="goal-info__value goal-info__value--accent">
                  {(mockGoalProgress.currentWeight - mockGoalProgress.targetWeight).toFixed(1)} kg
                </span>
              </div>
              <div className="goal-info__row">
                <span>基础代谢 (BMR)</span>
                <span className="goal-info__value">{loading ? '...' : bmrValue} kcal</span>
              </div>
              <div className="goal-info__row">
                <span>每日消耗 (TDEE)</span>
                <span className="goal-info__value">{loading ? '...' : tdeeValue} kcal</span>
              </div>
            </div>
            <div className="goal-info__tip">
              <Sparkles size={12} /> 健康速度：每周0.5斤
            </div>
          </div>

          {/* 周期数据摘要 */}
          <div className="side-module card">
            <div className="side-module__header">
              <CalendarCheck size={16} />
              <span>本周数据摘要</span>
            </div>
            <div className="summary-grid">
              <div className="summary-item">
                <Flame size={18} className="summary-item__icon" />
                <span className="summary-item__value">{mockWeeklySummary.avgCalorieDeficit}</span>
                <span className="summary-item__label">平均热量缺口</span>
              </div>
              <div className="summary-item">
                <Dumbbell size={18} className="summary-item__icon" />
                <span className="summary-item__value">{mockWeeklySummary.exerciseCount}</span>
                <span className="summary-item__label">运动次数</span>
              </div>
              <div className="summary-item">
                <TrendingDown size={18} className="summary-item__icon" />
                <span className="summary-item__value">{mockWeeklySummary.weightChange}</span>
                <span className="summary-item__label">体重变化(kg)</span>
              </div>
              <div className="summary-item">
                <Percent size={18} className="summary-item__icon" />
                <span className="summary-item__value">{mockWeeklySummary.dietCheckInRate}%</span>
                <span className="summary-item__label">饮食打卡率</span>
              </div>
            </div>
          </div>

          {/* AI解读模块 */}
          <div className="side-module side-module--ai card">
            <div className="side-module__header">
              <Sparkles size={16} />
              <span>AI解读</span>
            </div>
            <p className="ai-summary">
              {aiAnalysis || '本周体重持续下降，体脂率同步降低，运动执行率高。建议下周适当增加力量训练，有助于进一步提升代谢。'}
            </p>
            <button
              className="btn btn-primary ai-analyze-btn"
              onClick={() => handleAnalyzeBody('sidebar')}
              disabled={analyzing}
            >
              {analyzing ? <Loader2 size={16} className="spin" /> : <Sparkles size={16} />}
              {analyzing ? '分析中...' : 'AI分析本周数据'}
            </button>
            <div className="ai-analyze-options">
              <button
                className="ai-analyze-option"
                onClick={() => handleAnalyzeBody('navigate')}
              >
                跳转对话页分析
              </button>
              <button
                className="ai-analyze-option"
                onClick={() => handleAnalyzeBody('sidebar')}
              >
                侧边唤起对话
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* 下拉快速录入体重 */}
      <button className="quick-weight-btn" title="快速录入体重">
        <Weight size={20} />
        <ChevronDown size={14} />
      </button>
    </div>
  )
}

/* —— 指标卡片组件 —— */
function MetricCard({
  icon: Icon,
  label,
  value,
  unit,
  change,
  changeLabel,
  status,
  extra,
}: {
  icon: any
  label: string
  value: number | string
  unit: string
  change?: number
  changeLabel: string
  status?: string
  extra?: string
}) {
  return (
    <div className="metric-card card">
      <div className="metric-card__icon">
        <Icon size={18} />
      </div>
      <div className="metric-card__body">
        <span className="metric-card__label">{label}</span>
        <div className="metric-card__value-row">
          <span className="metric-card__value">{value}</span>
          {unit && <span className="metric-card__unit">{unit}</span>}
        </div>
        <div className="metric-card__footer">
          {change !== undefined && change !== 0 ? (
            <span className={`metric-card__change ${change > 0 ? 'metric-card__change--up' : 'metric-card__change--down'}`}>
              {change > 0 ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
              {change > 0 ? '+' : ''}{change}
            </span>
          ) : null}
          <span className="metric-card__change-label">{changeLabel}</span>
          {extra && <span className="metric-card__extra">{extra}</span>}
        </div>
      </div>
    </div>
  )
}
