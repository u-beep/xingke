import { Bell, HelpCircle, ChevronDown } from 'lucide-react'
import './TopBar.css'

interface TopBarProps {
  title: string
  subtitle?: string
}

export default function TopBar({ title, subtitle }: TopBarProps) {
  return (
    <header className="topbar">
      <div className="topbar__left">
        <h1 className="topbar__title">{title}</h1>
        {subtitle && <span className="topbar__subtitle">{subtitle}</span>}
      </div>
      <div className="topbar__right">
        <button className="topbar__icon-btn" title="消息通知">
          <Bell size={18} />
          <span className="topbar__badge" />
        </button>
        <button className="topbar__icon-btn" title="帮助中心">
          <HelpCircle size={18} />
        </button>
        <div className="topbar__user-menu">
          <div className="topbar__user-avatar">
            <img
              src="https://api.dicebear.com/7.x/avataaars/svg?seed=xingke"
              alt="头像"
            />
          </div>
          <span className="topbar__user-name">陈晓东</span>
          <ChevronDown size={15} className="topbar__dropdown-icon" />
        </div>
      </div>
    </header>
  )
}
