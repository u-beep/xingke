import { useState, useEffect } from 'react'
import { Dumbbell, Clock, Flame, Check, Play, ChevronRight, Loader2, RefreshCw } from 'lucide-react'
import { toolsApi } from '../../services/api'
import { getCurrentUserId } from '../../services/authStore'
import './ExercisePlan.css'

const typeColors: Record<string, string> = {
  '有氧': '#3b82f6',
  '力量': '#f59e0b',
  '核心': '#ec4899',
  '柔韧': '#8b5cf6',
  '休息': '#94a6a1',
}

export default function ExercisePlan() {
  const [plan, setPlan] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [doneSet, setDoneSet] = useState<Set<number>>(new Set())

  useEffect(() => {
    fetchExercisePlan()
  }, [])

  /** 调用API生成运动计划 */
  const fetchExercisePlan = async () => {
    setLoading(true)
    try {
      const result = await toolsApi.generateExercisePlan({
        fitness_level: 'beginner',
        available_days: 7,
        time_per_session: 45,
        equipment: 'none',
        target_areas: '全身',
        goal: '减脂',
        user_id: getCurrentUserId(),
      })
      setPlan(result)
    } catch (err) {
      console.error('获取运动计划失败:', err)
      setPlan(null)
    } finally {
      setLoading(false)
    }
  }

  // 从API结果解析运动计划，如果失败用默认数据
  const weeklyPlan = plan
    ? (plan.plan || plan.exercise_plan || plan.days || [])
    : [
        { day: '周一', name: 'HIIT燃脂训练', duration: '30分钟', calories: 320, type: '有氧' },
        { day: '周二', name: '上肢力量训练', duration: '45分钟', calories: 280, type: '力量' },
        { day: '周三', name: '休息日', duration: '—', calories: 0, type: '休息' },
        { day: '周四', name: '核心训练', duration: '30分钟', calories: 240, type: '核心' },
        { day: '周五', name: '下肢力量训练', duration: '40分钟', calories: 300, type: '力量' },
        { day: '周六', name: '有氧慢跑', duration: '40分钟', calories: 350, type: '有氧' },
        { day: '周日', name: '瑜伽拉伸', duration: '30分钟', calories: 150, type: '柔韧' },
      ]

  const toggleDone = (idx: number) => {
    setDoneSet((prev) => {
      const next = new Set(prev)
      if (next.has(idx)) next.delete(idx)
      else next.add(idx)
      return next
    })
  }

  const doneCount = doneSet.size
  const totalCalories = weeklyPlan
    .filter((_: any, idx: number) => doneSet.has(idx))
    .reduce((s: number, d: any) => s + (d.calories || 0), 0)

  return (
    <div className="exercise-plan">
      <div className="exercise-plan__summary card">
        <div className="exercise-summary__item">
          <Dumbbell size={20} className="exercise-summary__icon" />
          <div>
            <span className="exercise-summary__value">{doneCount}/{weeklyPlan.length}</span>
            <span className="exercise-summary__label">本周完成</span>
          </div>
        </div>
        <div className="exercise-summary__item">
          <Flame size={20} className="exercise-summary__icon" />
          <div>
            <span className="exercise-summary__value">{totalCalories}</span>
            <span className="exercise-summary__label">总消耗(kcal)</span>
          </div>
        </div>
        <div className="exercise-summary__item">
          <Clock size={20} className="exercise-summary__icon" />
          <div>
            <span className="exercise-summary__value">{doneCount * 40}</span>
            <span className="exercise-summary__label">本周时长(分钟)</span>
          </div>
        </div>
        <button className="btn btn-ghost exercise-plan__refresh" onClick={fetchExercisePlan}>
          {loading ? <Loader2 size={14} className="spin" /> : <RefreshCw size={14} />} 刷新计划
        </button>
      </div>

      {plan && (
        <div className="exercise-plan__ai-tip card">
          <span className="ai-tip__text">
            {plan.summary || plan.advice || 'AI已根据你的身体状况生成本周训练计划，建议按顺序执行以获得最佳效果。'}
          </span>
        </div>
      )}

      <div className="exercise-plan__list">
        {loading ? (
          <div className="exercise-record__loading card">
            <Loader2 size={24} className="spin" /> 正在生成个性化运动计划...
          </div>
        ) : (
          weeklyPlan.map((day: any, idx: number) => {
            const dayName = day.day || `第${idx + 1}天`
            const exerciseName = day.name || day.exercise || day.title
            const duration = day.duration || `${day.time || day.time_per_session || 45}分钟`
            const calories = day.calories || day.calorie_burn || 0
            const type = day.type || day.category || '有氧'
            const isDone = doneSet.has(idx)
            const isToday = idx === 4

            return (
              <div
                key={idx}
                className={`exercise-card card ${isToday ? 'exercise-card--today' : ''} ${isDone ? 'exercise-card--done' : ''}`}
              >
                <div className="exercise-card__day">
                  <span className="exercise-card__day-name">{dayName}</span>
                  {isToday && <span className="exercise-card__today-badge">今天</span>}
                </div>
                <div className="exercise-card__body">
                  <div className="exercise-card__info">
                    <span className="exercise-card__name">{exerciseName}</span>
                    <div className="exercise-card__meta">
                      <span
                        className="exercise-card__type"
                        style={{ background: `${typeColors[type] || '#94a6a1'}15`, color: typeColors[type] || '#94a6a1' }}
                      >
                        {type}
                      </span>
                      {duration !== '—' && (
                        <>
                          <span className="exercise-card__duration">
                            <Clock size={12} /> {duration}
                          </span>
                          <span className="exercise-card__cal">
                            <Flame size={12} /> {calories} kcal
                          </span>
                        </>
                      )}
                    </div>
                  </div>
                </div>
                <div className="exercise-card__action">
                  {isDone ? (
                    <span className="exercise-card__done" onClick={() => toggleDone(idx)}>
                      <Check size={16} /> 已完成
                    </span>
                  ) : isToday ? (
                    <button
                      className="btn btn-primary exercise-card__start"
                      onClick={() => toggleDone(idx)}
                    >
                      <Play size={14} /> 开始训练
                    </button>
                  ) : (
                    <ChevronRight size={18} className="exercise-card__arrow" onClick={() => toggleDone(idx)} />
                  )}
                </div>
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}
