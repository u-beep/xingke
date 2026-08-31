import { useEffect, useRef, useState } from 'react'
import { Bell, HelpCircle, ChevronDown, LogOut } from 'lucide-react'
import { authApi } from '../../services/auth'
import { getAuthUser, clearAuth } from '../../services/authStore'
import './TopBar.css'

interface TopBarProps {
  title: string
  subtitle?: string
}

export default function TopBar({ title, subtitle }: TopBarProps) {
  const user = getAuthUser()
  const displayName = user?.nickname || user?.username || '未登录'
  const [isUserMenuOpen, setIsUserMenuOpen] = useState(false)
  const userMenuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const closeUserMenu = (event: MouseEvent) => {
      if (userMenuRef.current && !userMenuRef.current.contains(event.target as Node)) {
        setIsUserMenuOpen(false)
      }
    }
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setIsUserMenuOpen(false)
    }

    document.addEventListener('mousedown', closeUserMenu)
    document.addEventListener('keydown', closeOnEscape)
    return () => {
      document.removeEventListener('mousedown', closeUserMenu)
      document.removeEventListener('keydown', closeOnEscape)
    }
  }, [])

  const handleLogout = async () => {
    try {
      await authApi.logout()
    } catch {
      // 服务端吊销失败也无妨，本地清理后跳转
    }
    clearAuth()
    window.location.href = '/login'
  }

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
        <div className="topbar__user-wrapper" ref={userMenuRef}>
          <button
            type="button"
            className={`topbar__user-menu ${isUserMenuOpen ? 'topbar__user-menu--open' : ''}`}
            onClick={() => setIsUserMenuOpen((isOpen) => !isOpen)}
            aria-expanded={isUserMenuOpen}
            aria-haspopup="menu"
          >
            <span className="topbar__user-avatar">
              <img
                src={`https://api.dicebear.com/7.x/avataaars/svg?seed=${encodeURIComponent(user?.username || 'xingke')}`}
                alt=""
              />
            </span>
            <span className="topbar__user-name">{displayName}</span>
            <ChevronDown size={15} className="topbar__dropdown-icon" />
          </button>
          {isUserMenuOpen && (
            <div className="topbar__user-dropdown" role="menu">
              <button type="button" className="topbar__logout-btn" onClick={handleLogout} role="menuitem">
                <LogOut size={16} />
                <span>退出登录</span>
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  )
}
