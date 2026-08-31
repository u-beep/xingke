import { Sparkles } from 'lucide-react'
import './Cover.css'

export default function Cover() {
  return (
    <div className="cover">
      <div className="cover__bg" />
      <div className="cover__content">
        <div className="cover__badge">
          <Sparkles size={14} />
          <span>型刻 · 你的专属身材管理 AI 中台</span>
        </div>
        <h1 className="cover__title">
          <span>型</span>
          <span>刻</span>
        </h1>
        <p className="cover__subtitle">
          AI 对话驱动 · 身体数据趋势 · 个性化减脂方案
        </p>
        <div className="cover__tags">
          <span>对话管理</span>
          <span>仪表盘</span>
          <span>饮食记录</span>
          <span>运动方案</span>
          <span>我的冰箱</span>
          <span>同城活动</span>
        </div>
      </div>
    </div>
  )
}
