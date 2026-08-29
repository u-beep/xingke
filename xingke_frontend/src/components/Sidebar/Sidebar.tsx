import { NavLink } from 'react-router-dom'
import {
  MessageSquareText,
  LayoutDashboard,
  UtensilsCrossed,
  ShoppingBag,
  Refrigerator,
  Dumbbell,
  UserRound,
  Settings,
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
  { path: '/dashboard', label: '身材仪表盘', icon: LayoutDashboard },
  { path: '/diet', label: '饮食记录', icon: UtensilsCrossed },
  { path: '/takeout', label: '外卖选购', icon: ShoppingBag },
  { path: '/fridge', label: '我的冰箱', icon: Refrigerator },
  { path: '/exercise', label: '运动计划', icon: Dumbbell },
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

      {/* 底部用户区 */}
      <div className="sidebar__footer">
        <div className="sidebar__user">
          <div className="sidebar__avatar">
            <img
              src="https://api.dicebear.com/7.x/avataaars/svg?seed=xingke"
              alt="头像"
            />
          </div>
          {!collapsed && (
            <div className="sidebar__user-info">
              <span className="sidebar__user-name">陈晓东</span>
              <span className="sidebar__user-settings">
                <Settings size={14} /> 设置
              </span>
            </div>
          )}
        </div>
      </div>

      {/* 折叠按钮 */}
      <button className="sidebar__toggle" onClick={onToggle}>
        {collapsed ? <ChevronRight size={16} /> : <ChevronLeft size={16} />}
      </button>
    </aside>
  )
}
