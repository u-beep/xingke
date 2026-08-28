import { useState, useEffect } from 'react'
import { User, Target, Activity, Award, Edit3 } from 'lucide-react'
import { toolsApi } from '../../services/api'
import './Profile.css'

const USER_PROFILE = {
  gender: 'male',
  age: 28,
  height: 175,
  weight: 71.5,
  targetWeight: 68.0,
}

export default function Profile() {
  const [bmr, setBmr] = useState<any>(null)
  const [tdee, setTdee] = useState<any>(null)
  const [bmi, setBmi] = useState<any>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchMetrics()
  }, [])

  const fetchMetrics = async () => {
    setLoading(true)
    try {
      const [bmrResult, bmiResult] = await Promise.all([
        toolsApi.calculateBMR({
          gender: USER_PROFILE.gender,
          age: USER_PROFILE.age,
          weight: USER_PROFILE.weight,
          height: USER_PROFILE.height,
        }).catch(() => null),
        toolsApi.calculateBMI({
          weight: USER_PROFILE.weight,
          height: USER_PROFILE.height,
        }).catch(() => null),
      ])

      if (bmrResult) {
        setBmr(bmrResult)
        const bmrVal = typeof bmrResult === 'object' ? (bmrResult.bmr || bmrResult.value || 1680) : 1680
        try {
          const tdeeResult = await toolsApi.calculateTDEE({ bmr: bmrVal, activity_level: 'moderate' })
          if (tdeeResult) setTdee(tdeeResult)
        } catch {}
      }
      if (bmiResult) setBmi(bmiResult)
    } finally {
      setLoading(false)
    }
  }

  const bmrVal = bmr ? (bmr.bmr ?? bmr.value ?? '—') : '—'
  const tdeeVal = tdee ? (tdee.tdee ?? tdee.value ?? '—') : '—'
  const bmiVal = bmi ? (bmi.bmi ?? bmi.value ?? '22.8') : '22.8'
  const bmiLabel = bmi ? (bmi.category ?? bmi.label ?? bmi.status ?? '正常') : '正常'
  const calorieBudget = tdeeVal !== '—' ? `${Number(tdeeVal) - 500} kcal` : '1600 kcal'

  return (
    <div className="profile">
      <div className="profile__header card">
        <div className="profile__avatar-large">
          <img src="https://api.dicebear.com/7.x/avataaars/svg?seed=xingke" alt="头像" />
        </div>
        <div className="profile__header-info">
          <h2 className="profile__name">陈晓东</h2>
          <span className="profile__motto">坚持型 · 已坚持减脂 42 天</span>
        </div>
        <button className="btn btn-ghost">
          <Edit3 size={14} /> 编辑资料
        </button>
      </div>

      <div className="profile__grid">
        <div className="profile-card card">
          <div className="profile-card__header">
            <User size={16} /> 基本信息
          </div>
          <div className="profile-card__list">
            <div className="profile-row"><span>性别</span><span>男</span></div>
            <div className="profile-row"><span>年龄</span><span>28岁</span></div>
            <div className="profile-row"><span>身高</span><span>175cm</span></div>
            <div className="profile-row"><span>当前体重</span><span>71.5kg</span></div>
            <div className="profile-row"><span>体脂率</span><span>21.5%</span></div>
            <div className="profile-row">
              <span>BMI</span>
              <span>{loading ? '计算中...' : `${bmiVal}（${bmiLabel}）`}</span>
            </div>
          </div>
        </div>

        <div className="profile-card card">
          <div className="profile-card__header">
            <Target size={16} /> 目标设置
          </div>
          <div className="profile-card__list">
            <div className="profile-row"><span>目标体重</span><span>68.0kg</span></div>
            <div className="profile-row"><span>目标体脂率</span><span>18%</span></div>
            <div className="profile-row"><span>目标期限</span><span>3个月</span></div>
            <div className="profile-row">
              <span>基础代谢 (BMR)</span>
              <span>{loading ? '计算中...' : `${bmrVal} kcal`}</span>
            </div>
            <div className="profile-row">
              <span>每日消耗 (TDEE)</span>
              <span>{loading ? '计算中...' : `${tdeeVal} kcal`}</span>
            </div>
            <div className="profile-row"><span>每日热量预算</span><span>{calorieBudget}</span></div>
          </div>
        </div>

        <div className="profile-card card">
          <div className="profile-card__header">
            <Activity size={16} /> 健康数据
          </div>
          <div className="profile-card__list">
            <div className="profile-row"><span>静息心率</span><span>68 bpm</span></div>
            <div className="profile-row"><span>腰围</span><span>79.5cm</span></div>
            <div className="profile-row"><span>臀围</span><span>94.8cm</span></div>
            <div className="profile-row"><span>腰臀比</span><span>0.84（健康）</span></div>
            <div className="profile-row">
              <span>基础代谢</span>
              <span>{loading ? '计算中...' : `${bmrVal} kcal`}</span>
            </div>
            <div className="profile-row">
              <span>每日总消耗</span>
              <span>{loading ? '计算中...' : `${tdeeVal} kcal`}</span>
            </div>
          </div>
        </div>

        <div className="profile-card card">
          <div className="profile-card__header">
            <Award size={16} /> 成就
          </div>
          <div className="profile-achievements">
            <div className="achievement">
              <div className="achievement__icon" style={{ background: '#ffc300' }}>42</div>
              <span className="achievement__label">连续打卡</span>
            </div>
            <div className="achievement">
              <div className="achievement__icon" style={{ background: '#f59e0b' }}>3.5</div>
              <span className="achievement__label">已减重(kg)</span>
            </div>
            <div className="achievement">
              <div className="achievement__icon" style={{ background: '#3b82f6' }}>28</div>
              <span className="achievement__label">运动次数</span>
            </div>
            <div className="achievement">
              <div className="achievement__icon" style={{ background: '#ec4899' }}>1%</div>
              <span className="achievement__label">体脂下降</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
