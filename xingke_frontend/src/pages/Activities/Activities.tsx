import { useState, useEffect, useCallback } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  Search,
  Plus,
  Loader2,
  MapPin,
  Users,
  CalendarClock,
  X,
  Trophy,
  Megaphone,
  Dumbbell,
  MessageCircle,
} from 'lucide-react'
import {
  activityApi,
  type ActivityInfo,
} from '../../services/api'
import { getCurrentUserId } from '../../services/authStore'
import './Activities.css'

/** 运动类型对应的图标 emoji（纯前端展示用） */
const SPORT_EMOJI: Record<string, string> = {
  '篮球': '🏀', '足球': '⚽', '羽毛球': '🏸', '乒乓球': '🏓', '网球': '🎾',
  '跑步': '🏃', '骑行': '🚴', '游泳': '🏊', '健身': '💪', '瑜伽': '🧘',
  '徒步': '🥾', '爬山': '⛰️', '滑板': '🛹', '跳绳': '🪢', '排球': '🏐', '其他': '🎯',
}

const STATUS_LABEL: Record<string, string> = {
  open: '报名中',
  full: '已满员',
  closed: '已关闭',
  finished: '已结束',
}

export default function Activities() {
  const navigate = useNavigate()
  const userId = getCurrentUserId()

  // 筛选条件同步 URL（刷新后保持筛选/搜索状态）
  const [searchParams, setSearchParams] = useSearchParams()

  // 列表数据
  const [activities, setActivities] = useState<ActivityInfo[]>([])
  const [memberCounts, setMemberCounts] = useState<number[]>([])
  const [loading, setLoading] = useState(true)

  // 筛选条件（URL 参数优先, 刷新后恢复）
  const [keyword, setKeyword] = useState(() => searchParams.get('q') || '')
  const [searchInput, setSearchInput] = useState(() => searchParams.get('q') || '')
  const [city, setCity] = useState(() => searchParams.get('city') || '')
  const [district, setDistrict] = useState(() => searchParams.get('district') || '')
  const [sportType, setSportType] = useState(() => searchParams.get('type') || '')
  const [onlyMine, setOnlyMine] = useState(() => searchParams.get('mine') === '1')

  // 筛选选项
  const [sportTypes, setSportTypes] = useState<string[]>([])
  const [cities, setCities] = useState<string[]>([])
  const [districts, setDistricts] = useState<string[]>([])

  // 我的活动 id 集合（用于列表上显示"已加入"标记）
  const [mineIds, setMineIds] = useState<Set<number>>(new Set())

  // 创建弹窗
  const [showCreate, setShowCreate] = useState(false)

  const fetchList = useCallback(async () => {
    setLoading(true)
    try {
      const result = await activityApi.list({
        keyword: keyword || undefined,
        city: city || undefined,
        district: district || undefined,
        sport_type: sportType || undefined,
        only_mine: onlyMine || undefined,
      })
      setActivities(result.activities)
      setMemberCounts(result.member_counts)
    } catch (err) {
      console.error('获取活动列表失败:', err)
    } finally {
      setLoading(false)
    }
  }, [keyword, city, district, sportType, onlyMine])

  const fetchMine = useCallback(async () => {
    try {
      const result = await activityApi.mine()
      setMineIds(new Set(result.activities.map((a) => a.id)))
    } catch {
      // 忽略
    }
  }, [])

  useEffect(() => {
    fetchList()
  }, [fetchList])

  useEffect(() => {
    fetchMine()
    activityApi.sportTypes().then((r) => setSportTypes(r.sport_types)).catch(() => {})
    activityApi.cities().then((r) => setCities(r.cities)).catch(() => {})
  }, [fetchMine])

  // 城市变化时拉取该城市行政区
  useEffect(() => {
    setDistrict('')
    if (city) {
      activityApi.districts(city).then((r) => setDistricts(r.districts)).catch(() => {})
    } else {
      setDistricts([])
    }
  }, [city])

  const doSearch = () => {
    const q = searchInput.trim()
    setKeyword(q)
    syncFilterToUrl({ q })
  }

  /** 将筛选条件同步到 URL query（刷新后可恢复） */
  const syncFilterToUrl = (overrides: Record<string, string | null> = {}) => {
    const current: Record<string, string | null> = {
      q: keyword || null,
      city: city || null,
      district: district || null,
      type: sportType || null,
      mine: onlyMine ? '1' : null,
      ...overrides,
    }
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        for (const [k, v] of Object.entries(current)) {
          if (v) next.set(k, v)
          else next.delete(k)
        }
        return next
      },
      { replace: true },
    )
  }

  // 筛选条件变化时同步 URL（搜索词由 doSearch 触发, 避免逐字写入）
  useEffect(() => {
    syncFilterToUrl()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [city, district, sportType, onlyMine])

  const handleCreated = () => {
    setShowCreate(false)
    fetchList()
    fetchMine()
  }

  return (
    <div className="activities">
      {/* 顶部：标题 + 搜索 + 创建按钮 */}
      <div className="activities__header card">
        <div className="activities__title-wrap">
          <div className="activities__title-icon">
            <Trophy size={22} />
          </div>
          <div>
            <h1 className="activities__title">运动活动</h1>
            <p className="activities__subtitle">找到同城运动伙伴，加入即进群聊</p>
          </div>
        </div>
        <div className="activities__actions">
          <div className="activities__search">
            <Search size={15} className="activities__search-icon" />
            <input
              className="activities__search-input"
              placeholder="搜索活动名称 / 地点 / 描述"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && doSearch()}
            />
            {searchInput && (
              <button className="activities__search-clear" onClick={() => { setSearchInput(''); setKeyword('') }}>
                <X size={13} />
              </button>
            )}
          </div>
          <button className="btn btn-primary" onClick={() => setShowCreate(true)}>
            <Plus size={14} /> 发起活动
          </button>
        </div>
      </div>

      {/* 筛选区 */}
      <div className="activities__filters card">
        <div className="activities__filter-group">
          <span className="activities__filter-label">城市</span>
          <select className="activities__select" value={city} onChange={(e) => setCity(e.target.value)}>
            <option value="">全部城市</option>
            {cities.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
        <div className="activities__filter-group">
          <span className="activities__filter-label">行政区</span>
          <select
            className="activities__select"
            value={district}
            onChange={(e) => setDistrict(e.target.value)}
            disabled={!city}
          >
            <option value="">全部区域</option>
            {districts.map((d) => <option key={d} value={d}>{d}</option>)}
          </select>
        </div>
        <div className="activities__filter-group">
          <span className="activities__filter-label">运动类型</span>
          <select className="activities__select" value={sportType} onChange={(e) => setSportType(e.target.value)}>
            <option value="">全部类型</option>
            {sportTypes.map((t) => <option key={t} value={t}>{SPORT_EMOJI[t] || ''} {t}</option>)}
          </select>
        </div>
        <label className="activities__mine-toggle">
          <input type="checkbox" checked={onlyMine} onChange={(e) => setOnlyMine(e.target.checked)} />
          <span>只看我的</span>
        </label>
        {(city || district || sportType || onlyMine || keyword) && (
          <button
            className="activities__filter-reset"
            onClick={() => { setCity(''); setDistrict(''); setSportType(''); setOnlyMine(false); setKeyword(''); setSearchInput('') }}
          >
            重置
          </button>
        )}
      </div>

      {/* 活动列表 */}
      {loading ? (
        <div className="activities__loading card">
          <Loader2 size={24} className="spin" /> 正在加载活动...
        </div>
      ) : activities.length === 0 ? (
        <div className="activities__empty card">
          <Trophy size={36} />
          <p>暂无符合条件的活动</p>
          <button className="btn btn-primary" onClick={() => setShowCreate(true)}>
            <Plus size={14} /> 发起第一个活动
          </button>
        </div>
      ) : (
        <div className="activities__grid">
          {activities.map((act, i) => {
            const count = memberCounts[i] ?? 0
            const joined = mineIds.has(act.id)
            const full = count >= act.max_participants
            return (
              <div key={act.id} className="activity-card card" onClick={() => navigate(`/activities/${act.id}`)}>
                <div className="activity-card__top">
                  <span className="activity-card__emoji">{SPORT_EMOJI[act.sport_type] || '🎯'}</span>
                  <span className={`activity-card__status ${act.status === 'open' ? (full ? 'activity-card__status--full' : 'activity-card__status--open') : 'activity-card__status--closed'}`}>
                    {act.status === 'open' ? (full ? '已满员' : '报名中') : STATUS_LABEL[act.status]}
                  </span>
                </div>
                <h3 className="activity-card__title">{act.title}</h3>
                <div className="activity-card__meta">
                  <span><MapPin size={12} /> {act.city}{act.district ? ` · ${act.district}` : ''}{act.location ? ` · ${act.location}` : ''}</span>
                  <span><CalendarClock size={12} /> {formatTime(act.start_time)}</span>
                </div>
                {act.description && <p className="activity-card__desc">{act.description}</p>}
                <div className="activity-card__footer">
                  <span className="activity-card__members">
                    <Users size={12} /> {count}/{act.max_participants}
                  </span>
                  <div className="activity-card__footer-right">
                    {joined && (
                      <span className="activity-card__joined">
                        <MessageCircle size={12} /> 已加入
                      </span>
                    )}
                    <span className="activity-card__go">详情 ›</span>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* 创建活动弹窗 */}
      {showCreate && (
        <CreateActivityModal
          sportTypes={sportTypes}
          onClose={() => setShowCreate(false)}
          onCreated={handleCreated}
        />
      )}
    </div>
  )
}


// ─── 子组件：创建活动弹窗 ───

function CreateActivityModal({
  sportTypes,
  onClose,
  onCreated,
}: {
  sportTypes: string[]
  onClose: () => void
  onCreated: () => void
}) {
  const [title, setTitle] = useState('')
  const [sportType, setSportType] = useState('篮球')
  const [city, setCity] = useState('北京')
  const [district, setDistrict] = useState('')
  const [location, setLocation] = useState('')
  const [date, setDate] = useState('')
  const [time, setTime] = useState('19:00')
  const [maxParticipants, setMaxParticipants] = useState(10)
  const [description, setDescription] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const submit = async () => {
    setError('')
    if (!title.trim()) { setError('请填写活动名称'); return }
    if (!city.trim()) { setError('请填写城市'); return }
    if (!date) { setError('请选择活动日期'); return }
    const startTime = `${date}T${time}:00`
    setSubmitting(true)
    try {
      await activityApi.create({
        title: title.trim(),
        sport_type: sportType,
        city: city.trim(),
        district: district.trim(),
        location: location.trim(),
        start_time: startTime,
        max_participants: maxParticipants,
        description: description.trim(),
      })
      onCreated()
    } catch (err: any) {
      setError(err?.message || '创建失败，请重试')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal activities-create" onClick={(e) => e.stopPropagation()}>
        <div className="modal__header">
          <h3 className="modal__title">
            <Dumbbell size={16} /> 发起运动活动
          </h3>
          <button className="modal__close" onClick={onClose}><X size={18} /></button>
        </div>
        <div className="modal__body">
          <div className="activities-create__form">
            <label className="activities-create__label">
              活动名称 <em>*</em>
              <input
                className="activities-create__input"
                placeholder="如：周末朝阳公园篮球局"
                value={title}
                maxLength={128}
                onChange={(e) => setTitle(e.target.value)}
              />
            </label>

            <div className="activities-create__row">
              <label className="activities-create__label">
                运动类型 <em>*</em>
                <select className="activities-create__input" value={sportType} onChange={(e) => setSportType(e.target.value)}>
                  {sportTypes.map((t) => <option key={t} value={t}>{SPORT_EMOJI[t] || ''} {t}</option>)}
                </select>
              </label>
              <label className="activities-create__label">
                人数上限 <em>*</em>
                <input
                  type="number"
                  className="activities-create__input"
                  value={maxParticipants}
                  min={1}
                  max={500}
                  onChange={(e) => setMaxParticipants(Number(e.target.value) || 1)}
                />
              </label>
            </div>

            <div className="activities-create__row">
              <label className="activities-create__label">
                城市 <em>*</em>
                <input className="activities-create__input" placeholder="北京" value={city} onChange={(e) => setCity(e.target.value)} />
              </label>
              <label className="activities-create__label">
                行政区
                <input className="activities-create__input" placeholder="朝阳区" value={district} onChange={(e) => setDistrict(e.target.value)} />
              </label>
            </div>

            <label className="activities-create__label">
              具体地点
              <input className="activities-create__input" placeholder="如：朝阳公园南门篮球场" value={location} onChange={(e) => setLocation(e.target.value)} />
            </label>

            <div className="activities-create__row">
              <label className="activities-create__label">
                日期 <em>*</em>
                <input type="date" className="activities-create__input" value={date} onChange={(e) => setDate(e.target.value)} />
              </label>
              <label className="activities-create__label">
                时间
                <input type="time" className="activities-create__input" value={time} onChange={(e) => setTime(e.target.value)} />
              </label>
            </div>

            <label className="activities-create__label">
              活动描述
              <textarea
                className="activities-create__textarea"
                placeholder="活动安排、注意事项、装备要求等"
                value={description}
                maxLength={2000}
                rows={3}
                onChange={(e) => setDescription(e.target.value)}
              />
            </label>

            <div className="activities-create__hint">
              <Megaphone size={13} /> 创建后将自动建立活动群聊，你将以管理员身份进入
            </div>

            {error && <p className="activities-create__error">{error}</p>}

            <div className="activities-create__actions">
              <button className="btn btn-ghost" onClick={onClose} disabled={submitting}>取消</button>
              <button className="btn btn-primary" onClick={submit} disabled={submitting}>
                {submitting ? <Loader2 size={14} className="spin" /> : <Plus size={14} />} 创建活动
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}


// ─── 工具 ───

export function formatTime(iso: string | null): string {
  if (!iso) return '时间待定'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}
