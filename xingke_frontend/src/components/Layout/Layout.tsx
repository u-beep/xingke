import { useState, useEffect } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import Sidebar from '../Sidebar/Sidebar'
import TopBar from '../TopBar/TopBar'
import './Layout.css'

const pageMeta: Record<string, { title: string; subtitle?: string }> = {
  '/': { title: '我的专属身材管家' },
  '/diet': { title: '饮食记录', subtitle: '每日热量摄入管理' },
  '/exercise': { title: '运动记录', subtitle: '记录每日运动量，看见每一点进步' },
  '/activities': { title: '运动活动', subtitle: '同城运动伙伴与群聊' },
  '/profile': { title: '我的档案', subtitle: '身体数据与趋势总览' },
}

const SIDEBAR_COLLAPSED_KEY = 'xingke_sidebar_collapsed'

/** 读取持久化的侧边栏折叠状态（刷新后保持） */
function readCollapsedFromStorage(): boolean {
  try {
    return localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === '1'
  } catch {
    return false
  }
}

export default function Layout() {
  const [collapsed, setCollapsed] = useState<boolean>(() => readCollapsedFromStorage())
  const location = useLocation()
  const meta = pageMeta[location.pathname] || { title: '型刻' }

  const toggleCollapsed = () => {
    setCollapsed((prev) => {
      const next = !prev
      try {
        localStorage.setItem(SIDEBAR_COLLAPSED_KEY, next ? '1' : '0')
      } catch {
        // 存储不可用时忽略
      }
      return next
    })
  }

  // 路由切换时滚动条回到顶部
  useEffect(() => {
    const main = document.querySelector('.layout__content')
    main?.scrollTo({ top: 0 })
  }, [location.pathname])

  return (
    <div className="layout">
      <Sidebar collapsed={collapsed} onToggle={toggleCollapsed} />
      <div className="layout__main">
        <TopBar title={meta.title} subtitle={meta.subtitle} />
        <main className="layout__content">
          <div className="layout__content-inner">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  )
}
