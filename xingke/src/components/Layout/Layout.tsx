import { useState } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import Sidebar from '../Sidebar/Sidebar'
import TopBar from '../TopBar/TopBar'
import './Layout.css'

const pageMeta: Record<string, { title: string; subtitle?: string }> = {
  '/': { title: '我的专属身材管家', subtitle: '已同步你的最新身体数据' },
  '/dashboard': { title: '身材仪表盘', subtitle: '数据可视化中心' },
  '/diet': { title: '饮食记录', subtitle: '每日热量摄入管理' },
  '/exercise': { title: '运动计划', subtitle: '科学训练，高效燃脂' },
  '/profile': { title: '我的档案', subtitle: '个人健康信息管理' },
}

export default function Layout() {
  const [collapsed, setCollapsed] = useState(false)
  const location = useLocation()
  const meta = pageMeta[location.pathname] || { title: '型刻' }

  return (
    <div className="layout">
      <Sidebar collapsed={collapsed} onToggle={() => setCollapsed(!collapsed)} />
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
