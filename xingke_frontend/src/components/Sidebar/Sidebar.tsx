import { NavLink } from 'react-router-dom'
import {
  MessageSquareText,
  UtensilsCrossed,
  ShoppingBag,
  Refrigerator,
  Dumbbell,
  Trophy,
  UserRound,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react'
import './Sidebar.css'

interface SidebarProps {
  collapsed: boolean
  onToggle: () => void
}

const navItems = [
  { path: '/', label: 'AI对话', icon: MessageSquareText },
  { path: '/diet', label: '饮食记录', icon: UtensilsCrossed },
  { path: '/takeout', label: '外卖选购', icon: ShoppingBag },
  { path: '/fridge', label: '我的冰箱', icon: Refrigerator },
  { path: '/exercise', label: '运动记录', icon: Dumbbell },
  { path: '/activities', label: '活动', icon: Trophy },
  { path: '/profile', label: '我的档案', icon: UserRound },
]

export default function Sidebar({ collapsed, onToggle }: SidebarProps) {
  return (
    <aside className={`sidebar ${collapsed ? 'sidebar--collapsed' : ''}`}>
      {/* 品牌Logo —— 美团袋鼠 */}
      <div className="sidebar__brand">
        <div className="sidebar__logo">
          <img src="/meituan-logo.png" alt="美团 Logo" width="28" height="28" />
        </div>
        {!collapsed && <span className="sidebar__brand-name">型刻</span>}
      </div>

      {/* 导航菜单 */}
      <nav className="sidebar__nav">
        {navItems.map((item) => {
          const Icon = item.icon
          return (
            <NavLink
              key={item.path}
              to={item.path}
              end={item.path === '/'}
              className={({ isActive }) =>
                `sidebar__nav-item ${isActive ? 'sidebar__nav-item--active' : ''}`
              }
              title={collapsed ? item.label : undefined}
            >
              <Icon size={20} className="sidebar__nav-icon" />
              {!collapsed && <span className="sidebar__nav-label">{item.label}</span>}
            </NavLink>
          )
        })}
      </nav>
      {/* 折叠按钮 */}
      <button className="sidebar__toggle" onClick={onToggle}>
        {collapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
      </button>
    </aside>
  )
}
