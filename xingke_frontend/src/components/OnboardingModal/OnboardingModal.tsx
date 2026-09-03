import { useState, type FormEvent } from 'react'
import { Ruler, Weight, UserRound } from 'lucide-react'
import { profileApi, weightApi } from '../../services/api'
import './OnboardingModal.css'

/**
 * 新用户身体数据引导弹窗。
 *
 * 注册后资料缺少身高/体重/性别时弹出，必须完整录入才能进入主应用——
 * 这三项是 BMI、BMR/TDEE 热量预算、运动建议等核心功能的计算基础。
 */
export default function OnboardingModal({ onComplete }: { onComplete: () => void }) {
  const [height, setHeight] = useState('')
  const [weight, setWeight] = useState('')
  const [gender, setGender] = useState<'male' | 'female' | ''>('')
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (saving) return
    setError(null)

    const h = parseFloat(height)
    const w = parseFloat(weight)
    if (isNaN(h) || h < 80 || h > 250) {
      setError('请输入 80-250 之间的身高(cm)')
      return
    }
    if (isNaN(w) || w < 20 || w > 300) {
      setError('请输入 20-300 之间的体重(kg)')
      return
    }
    if (!gender) {
      setError('请选择性别')
      return
    }

    setSaving(true)
    try {
      // 体重同时写入资料表与体重记录表：前者供 BMI/TDEE 计算，
      // 后者驱动「当前体重」卡片与体重趋势图（两条链路独立存储）
      const payload = {
        height_cm: Math.round(h * 10) / 10,
        weight_kg: Math.round(w * 10) / 10,
        gender,
      }
      await Promise.all([
        profileApi.update(payload),
        weightApi.record({ weight_kg: payload.weight_kg, notes: '初始身体数据录入' }),
      ])
      onComplete()
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败，请稍后重试')
      setSaving(false)
    }
  }

  return (
    <div className="onboarding-overlay">
      <form className="onboarding-modal" onSubmit={handleSubmit}>
        <div className="onboarding-brand">
          <img src="/meituan-logo.png" alt="logo" className="onboarding-brand__logo" />
          <h2 className="onboarding-brand__title">完善你的身体数据</h2>
          <p className="onboarding-brand__subtitle">
            身高、体重和性别是计算 BMI、每日热量预算与运动建议的基础
          </p>
        </div>

        <div className="onboarding-grid">
          <label className="onboarding-field">
            <span className="onboarding-field__label">
              <Ruler size={14} /> 身高
            </span>
            <div className="onboarding-field__input-wrap">
              <input
                className="onboarding-field__input"
                type="number"
                inputMode="decimal"
                step="0.1"
                min="80"
                max="250"
                placeholder="如 175"
                value={height}
                onChange={(e) => setHeight(e.target.value)}
                autoFocus
              />
              <span className="onboarding-field__unit">cm</span>
            </div>
          </label>

          <label className="onboarding-field">
            <span className="onboarding-field__label">
              <Weight size={14} /> 体重
            </span>
            <div className="onboarding-field__input-wrap">
              <input
                className="onboarding-field__input"
                type="number"
                inputMode="decimal"
                step="0.1"
                min="20"
                max="300"
                placeholder="如 65.5"
                value={weight}
                onChange={(e) => setWeight(e.target.value)}
              />
              <span className="onboarding-field__unit">kg</span>
            </div>
          </label>
        </div>

        <div className="onboarding-field">
          <span className="onboarding-field__label">
            <UserRound size={14} /> 性别
          </span>
          <div className="onboarding-gender">
            <button
              type="button"
              className={`onboarding-gender__btn ${gender === 'male' ? 'onboarding-gender__btn--active' : ''}`}
              onClick={() => setGender('male')}
            >
              男
            </button>
            <button
              type="button"
              className={`onboarding-gender__btn ${gender === 'female' ? 'onboarding-gender__btn--active' : ''}`}
              onClick={() => setGender('female')}
            >
              女
            </button>
          </div>
        </div>

        {error && <div className="onboarding-error">{error}</div>}

        <button className="onboarding-submit" type="submit" disabled={saving}>
          {saving ? '保存中...' : '开始使用'}
        </button>
      </form>
    </div>
  )
}
