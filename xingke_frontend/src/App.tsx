import { Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/Layout/Layout'
import AIChat from './pages/AIChat/AIChat'
import DietRecord from './pages/DietRecord/DietRecord'
import ExercisePlan from './pages/ExercisePlan/ExercisePlan'
import Fridge from './pages/Fridge/Fridge'
import Profile from './pages/Profile/Profile'
import Takeout from './pages/Takeout/Takeout'
import Activities from './pages/Activities/Activities'
import ActivityDetail from './pages/Activities/ActivityDetail'
import Login from './pages/Login/Login'
import { isLoggedIn } from './services/authStore'
import type { ReactNode } from 'react'

/** 路由守卫：未登录跳转登录页 */
function RequireAuth({ children }: { children: ReactNode }) {
  if (!isLoggedIn()) {
    return <Navigate to="/login" replace />
  }
  return <>{children}</>
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route path="/" element={<AIChat />} />
        {/* 旧仪表盘已并入我的档案，兼容旧链接重定向 */}
        <Route path="/dashboard" element={<Navigate to="/profile" replace />} />
        <Route path="/diet" element={<DietRecord />} />
        <Route path="/takeout" element={<Takeout />} />
        <Route path="/activities" element={<Activities />} />
        <Route path="/activities/:id" element={<ActivityDetail />} />
        <Route path="/fridge" element={<Fridge />} />
        <Route path="/exercise" element={<ExercisePlan />} />
        <Route path="/profile" element={<Profile />} />
      </Route>
    </Routes>
  )
}
