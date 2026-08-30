import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { authApi } from '../../services/auth'
import { setAuth } from '../../services/authStore'
import './Login.css'

type Mode = 'login' | 'register'

export default function Login() {
  const navigate = useNavigate()
  const [mode, setMode] = useState<Mode>('login')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [nickname, setNickname] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const switchMode = (m: Mode) => {
    setMode(m)
    setError(null)
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (loading) return
    setError(null)

    const name = username.trim()
    if (name.length < 3) {
      setError('用户名至少 3 个字符')
      return
    }
    if (password.length < 6) {
      setError('密码至少 6 位')
      return
    }

    setLoading(true)
    try {
      const resp =
        mode === 'login'
          ? await authApi.login({ username: name, password })
          : await authApi.register({
              username: name,
              password,
              nickname: nickname.trim() || undefined,
            })
      setAuth(resp.token, resp.user)
      navigate('/', { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : '操作失败，请稍后重试')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-brand">
          <img src="/meituan-logo.png" alt="logo" className="login-brand__logo" />
          <h1 className="login-brand__title">型刻</h1>
          <p className="login-brand__subtitle">你的 AI 身材管理管家</p>
        </div>

        <div className="login-tabs">
          <button
            type="button"
            className={`login-tab ${mode === 'login' ? 'login-tab--active' : ''}`}
            onClick={() => switchMode('login')}
          >
            登录
          </button>
          <button
            type="button"
            className={`login-tab ${mode === 'register' ? 'login-tab--active' : ''}`}
            onClick={() => switchMode('register')}
          >
            注册
          </button>
        </div>

        <form className="login-form" onSubmit={handleSubmit}>
          <label className="login-field">
            <span className="login-field__label">用户名</span>
            <input
              className="login-field__input"
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="3-32位，字母/数字/下划线/中文"
              autoComplete="username"
              maxLength={32}
            />
          </label>

          {mode === 'register' && (
            <label className="login-field">
              <span className="login-field__label">昵称（可选）</span>
              <input
                className="login-field__input"
                type="text"
                value={nickname}
                onChange={(e) => setNickname(e.target.value)}
                placeholder="展示名称，默认同用户名"
                maxLength={32}
              />
            </label>
          )}

          <label className="login-field">
            <span className="login-field__label">密码</span>
            <input
              className="login-field__input"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="至少 6 位"
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
              maxLength={64}
            />
          </label>

          {error && <div className="login-error">{error}</div>}

          <button className="login-submit" type="submit" disabled={loading}>
            {loading ? '处理中...' : mode === 'login' ? '登 录' : '注册并登录'}
          </button>
        </form>

        <p className="login-tip">
          {mode === 'login' ? '还没有账号？' : '已有账号？'}
          <button
            type="button"
            className="login-switch"
            onClick={() => switchMode(mode === 'login' ? 'register' : 'login')}
          >
            {mode === 'login' ? '去注册' : '去登录'}
          </button>
        </p>
      </div>
    </div>
  )
}
