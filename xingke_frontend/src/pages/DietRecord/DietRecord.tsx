import { useState, useEffect } from 'react'
import { Flame, Loader2, X, Pencil, RefreshCw, ChevronLeft, ChevronRight, ShoppingCart, MessageSquare, Refrigerator } from 'lucide-react'
import { dietApi, profileApi, type DailyDietRecord } from '../../services/api'
import DatePicker from '../../components/DatePicker/DatePicker'
import './DietRecord.css'

const USER_ID = 'user_web_001'

/** 今天日期 YYYY-MM-DD */
function todayStr(): string {
  const d = new Date()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${m}-${day}`
}

/** 日期 +/-1 天 */
function shiftDate(dateStr: string, days: number): string {
  const d = new Date(dateStr + 'T00:00:00')
  d.setDate(d.getDate() + days)
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${m}-${day}`
}

/** ISO → "HH:MM" */
function fmtTime(iso?: string | null): string {
  if (!iso) return ''
  const m = iso.match(/T(\d{2}):(\d{2})/)
  return m ? `${m[1]}:${m[2]}` : ''
}

/** 餐次显示名 */
const MEAL_LABELS: Record<string, string> = {
  breakfast: '早餐',
  lunch: '午餐',
  dinner: '晚餐',
  snack: '加餐',
}

/** 来源图标 */
function SourceIcon({ source }: { source: string }) {
  if (source === 'order') return <ShoppingCart size={12} />
  if (source === 'fridge') return <Refrigerator size={12} />
  return <MessageSquare size={12} />
}

export default function DietRecord() {
  // 选中的日期(默认今天)
  const [date, setDate] = useState<string>(todayStr())
  // 当日聚合数据(记录+统计)
  const [daily, setDaily] = useState<DailyDietRecord[] | null>(null)
  const [summary, setSummary] = useState<any>(null)
  const [loading, setLoading] = useState(false)

  // 用户热量预算
  const [budgetInfo, setBudgetInfo] = useState<any>(null)

  // 预算编辑弹窗
  const [showBudgetModal, setShowBudgetModal] = useState(false)
  const [budgetInput, setBudgetInput] = useState('')
  const [savingBudget, setSavingBudget] = useState(false)

  useEffect(() => {
    fetchDaily(date)
    fetchBudget()
  }, [date])

  /** 获取指定日期的饮食记录与统计 */
  const fetchDaily = async (d: string) => {
    setLoading(true)
    try {
      const result = await dietApi.daily(d)
      setDaily(result.records)
      setSummary(result.summary)
    } catch (err) {
      console.error('获取饮食记录失败:', err)
      setDaily([])
    } finally {
      setLoading(false)
    }
  }

  /** 获取用户热量预算 */
  const fetchBudget = async () => {
    try {
      const info = await profileApi.getCalorieBudget(USER_ID)
      setBudgetInfo(info)
    } catch (err) {
      console.error('获取热量预算失败:', err)
    }
  }

  /** 保存热量预算 */
  const handleSaveBudget = async () => {
    const val = parseInt(budgetInput, 10)
    if (isNaN(val) || val < 800 || val > 5000) {
      alert('请输入 800-5000 之间的合理热量值')
      return
    }
    setSavingBudget(true)
    try {
      await profileApi.setCalorieBudget(USER_ID, val)
      await fetchBudget()
      await fetchDaily(date)
      setShowBudgetModal(false)
    } catch (err) {
      alert('保存预算失败，请稍后再试')
    } finally {
      setSavingBudget(false)
    }
  }

  // 摄入与预算
  const consumed = summary?.total_calories || 0
  const budget = budgetInfo?.daily_calorie_budget || budgetInfo?.suggested_budget || summary?.budget || 1600
  const remaining = Math.max(0, Math.round(budget - consumed))
  const percent = budget > 0 ? Math.min(100, Math.round((consumed / budget) * 100)) : 0
  const hasCustomBudget = budgetInfo?.has_custom === true
  const isToday = date === todayStr()

  const records = daily || []

  return (
    <div className="diet-record">
      {/* 今日热量概览（真实摄入 + 自定义预算） */}
      <div className="diet-record__overview card">
        <div className="diet-overview__left">
          <div className="diet-overview__ring">
            <svg viewBox="0 0 100 100" width="100" height="100">
              <circle cx="50" cy="50" r="42" fill="none" stroke="#fff3c4" strokeWidth="8" />
              <circle
                cx="50" cy="50" r="42" fill="none" stroke="#ffc300" strokeWidth="8"
                strokeLinecap="round"
                strokeDasharray={`${(percent / 100) * 264} 264`}
                transform="rotate(-90 50 50)"
              />
            </svg>
            <div className="diet-overview__center">
              <span className="diet-overview__percent">{percent}%</span>
              <span className="diet-overview__label">已摄入</span>
            </div>
          </div>
        </div>
        <div className="diet-overview__stats">
          <div className="diet-stat-item">
            <span className="diet-stat-item__label">已摄入</span>
            <span className="diet-stat-item__value">{Math.round(consumed)}</span>
          </div>
          <div className="diet-stat-item">
            <span className="diet-stat-item__label">
              热量预算
              <button className="budget-edit-btn" onClick={() => { setBudgetInput(String(budget)); setShowBudgetModal(true) }} title="自定义热量预算">
                <Pencil size={12} />
              </button>
            </span>
            <span className="diet-stat-item__value">
              {budget}
              {!hasCustomBudget && budgetInfo?.suggested_budget ? <em className="budget-source-tag">TDEE建议</em> : null}
            </span>
          </div>
          <div className="diet-stat-item">
            <span className="diet-stat-item__label">剩余可吃</span>
            <span className="diet-stat-item__value diet-stat-item__value--accent">{remaining}</span>
          </div>
          <div className="diet-stat-item">
            <span className="diet-stat-item__label">三大营养素</span>
            <span className="diet-stat-item__sub">
              蛋白 {Math.round(summary?.total_protein_g || 0)}g · 碳水 {Math.round(summary?.total_carbs_g || 0)}g · 脂肪 {Math.round(summary?.total_fat_g || 0)}g
            </span>
          </div>
        </div>
        <div className="diet-overview__actions">
          <button className="btn btn-ghost" onClick={() => fetchDaily(date)} title="刷新数据">
            <RefreshCw size={16} /> 刷新
          </button>
        </div>
      </div>

      {/* 食物记录列表（按日期查阅） */}
      <div className="diet-record__list">
        <div className="diet-record__section-head">
          <span className="diet-record__section-title">
            <Flame size={15} />
            {isToday ? '今日饮食记录' : `${date} 饮食记录`}
            <em className="diet-record__section-total">{Math.round(consumed)} kcal</em>
          </span>
          {/* 右上角日期切换 */}
          <div className="diet-date-nav">
            <button className="diet-date-nav__btn" onClick={() => setDate(shiftDate(date, -1))} title="前一天">
              <ChevronLeft size={16} />
            </button>
            <DatePicker
              value={date}
              onChange={(d) => setDate(d)}
              max={todayStr()}
            />
            <button
              className="diet-date-nav__btn"
              onClick={() => setDate(shiftDate(date, 1))}
              disabled={isToday}
              title="后一天"
            >
              <ChevronRight size={16} />
            </button>
          </div>
        </div>

        {loading ? (
          <div className="diet-record__loading card">
            <Loader2 size={24} className="spin" /> 正在加载饮食记录...
          </div>
        ) : records.length > 0 ? (
          <div className="diet-records">
            {records.map((r) => (
              <div key={r.record_key} className={`diet-record-item card ${r.include_in_stats ? '' : 'diet-record-item--excluded'}`}>
                <div className="diet-record-item__main">
                  <div className="diet-record-item__name-row">
                    <span className="diet-record-item__name">{r.food_name}</span>
                    <span className={`diet-record-item__source diet-record-item__source--${r.source}`}>
                      <SourceIcon source={r.source} />
                      {r.source_label}
                    </span>
                    {r.meal_type && MEAL_LABELS[r.meal_type] && (
                      <span className="diet-record-item__meal">{MEAL_LABELS[r.meal_type]}</span>
                    )}
                  </div>
                  {(r.amount_g != null || r.ingredients_summary) && (
                    <div className="diet-record-item__detail">
                      {r.amount_g != null && <span>{Math.round(r.amount_g)}g</span>}
                      {r.ingredients_summary && <span className="diet-record-item__ingredients" title={r.ingredients_summary}>{r.ingredients_summary}</span>}
                    </div>
                  )}
                  {!r.include_in_stats && (
                    <div className="diet-record-item__excluded-tag">未计入统计</div>
                  )}
                </div>
                <div className="diet-record-item__side">
                  <span className="diet-record-item__cal">
                    <Flame size={13} /> {r.calories != null ? Math.round(r.calories) : '-'}
                  </span>
                  {r.recorded_at && (
                    <span className="diet-record-item__time">{fmtTime(r.recorded_at)}</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="diet-record__empty card">
            {isToday ? '今日暂无饮食记录' : `${date} 无饮食记录`}
            <span className="diet-record__empty-hint">来源：外卖下单、冰箱菜谱确认、对话上报</span>
          </div>
        )}
      </div>

      {/* 热量预算编辑弹窗 */}
      {showBudgetModal && (
        <div className="modal-overlay" onClick={() => setShowBudgetModal(false)}>
          <div className="modal modal--small" onClick={(e) => e.stopPropagation()}>
            <div className="modal__header">
              <h3 className="modal__title">自定义每日热量预算</h3>
              <button className="modal__close" onClick={() => setShowBudgetModal(false)}>
                <X size={18} />
              </button>
            </div>
            <div className="modal__body">
              <div className="budget-modal">
                <p className="budget-modal__hint">
                  设置每日热量目标预算（kcal）。推荐范围：减脂期 1200-1600，维持期 1600-2000，增肌期 2000-2800。
                </p>
                {budgetInfo?.suggested_budget ? (
                  <p className="budget-modal__suggested">
                    根据你的身体数据，TDEE 建议值：<strong>{budgetInfo.suggested_budget} kcal</strong>
                  </p>
                ) : null}
                <div className="budget-modal__quick">
                  {[1400, 1600, 1800, 2000].map((v) => (
                    <button key={v} className="budget-modal__quick-btn" onClick={() => setBudgetInput(String(v))}>
                      {v}
                    </button>
                  ))}
                </div>
                <input
                  className="budget-modal__input"
                  type="number"
                  min={800}
                  max={5000}
                  value={budgetInput}
                  onChange={(e) => setBudgetInput(e.target.value)}
                  placeholder="输入热量目标"
                />
                <button
                  className="btn btn-primary budget-modal__submit"
                  disabled={savingBudget || !budgetInput}
                  onClick={handleSaveBudget}
                >
                  {savingBudget ? <Loader2 size={16} className="spin" /> : null} 保存预算
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
