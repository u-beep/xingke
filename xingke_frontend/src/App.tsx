import { Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/Layout/Layout'
import AIChat from './pages/AIChat/AIChat'
import Dashboard from './pages/Dashboard/Dashboard'
import DietRecord from './pages/DietRecord/DietRecord'
import ExercisePlan from './pages/ExercisePlan/ExercisePlan'
import Fridge from './pages/Fridge/Fridge'
import Profile from './pages/Profile/Profile'
import Takeout from './pages/Takeout/Takeout'
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
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/diet" element={<DietRecord />} />
        <Route path="/takeout" element={<Takeout />} />
        <Route path="/fridge" element={<Fridge />} />
        <Route path="/exercise" element={<ExercisePlan />} />
        <Route path="/profile" element={<Profile />} />
      </Route>
    </Routes>
  )
}
