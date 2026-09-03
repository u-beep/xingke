import { useState, useEffect } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import Sidebar from '../Sidebar/Sidebar'
import TopBar from '../TopBar/TopBar'
import OnboardingModal from '../OnboardingModal/OnboardingModal'
import { profileApi, weightApi } from '../../services/api'
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
  // 新用户/存量用户引导：身高、体重、性别任一缺失时弹窗强制补录。
  // 每次进入都以服务端资料为准（不依赖本地标记，存量用户缺数据同样弹出）。
  const [showOnboarding, setShowOnboarding] = useState(false)

  const checkOnboarding = async () => {
    try {
      const res = await profileApi.me()
      const p = res?.profile
      if (!p || !p.height_cm || !p.weight_kg || !p.gender) {
        setShowOnboarding(true)
        return
      }
      // 存量兼容：资料有体重但体重记录表为空（早期引导只写资料表），
      // 自动补一条初始记录，让「当前体重」卡与趋势图有数据
      try {
        const hist = await weightApi.history(365, 1)
        if (!hist?.records?.length && Number(p.weight_kg) > 0) {
          await weightApi.record({ weight_kg: Number(p.weight_kg), notes: '初始身体数据补录' })
        }
      } catch {
        // 静默，不影响主界面
      }
    } catch {
      // 拉取失败不阻断主界面，下次进入重试
    }
  }

  useEffect(() => {
    checkOnboarding()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

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
      {showOnboarding && (
        <OnboardingModal
          onComplete={() => setShowOnboarding(false)}
        />
      )}
    </div>
  )
}
