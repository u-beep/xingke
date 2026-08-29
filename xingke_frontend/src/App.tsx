import { Routes, Route } from 'react-router-dom'
import Layout from './components/Layout/Layout'
import AIChat from './pages/AIChat/AIChat'
import Dashboard from './pages/Dashboard/Dashboard'
import DietRecord from './pages/DietRecord/DietRecord'
import ExercisePlan from './pages/ExercisePlan/ExercisePlan'
import Fridge from './pages/Fridge/Fridge'
import Profile from './pages/Profile/Profile'
import Takeout from './pages/Takeout/Takeout'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
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
