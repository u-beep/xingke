import { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  ChevronLeft,
  Loader2,
  MapPin,
  Users,
  CalendarClock,
  MessageCircle,
  UserPlus,
  LogOut,
  Trash2,
  Send,
  Crown,
  X,
  Megaphone,
  Pencil,
  UserMinus,
  List,
  AlertTriangle,
} from 'lucide-react'
import {
  activityApi,
  type ActivityInfo,
  type ActivityMemberInfo,
  type ActivityGroupInfo,
  type ActivityMessageInfo,
} from '../../services/api'
import { getCurrentUserId } from '../../services/authStore'
import { formatTime } from './Activities'
import './Activities.css'

const SPORT_EMOJI: Record<string, string> = {
  '篮球': '🏀', '足球': '⚽', '羽毛球': '🏸', '乒乓球': '🏓', '网球': '🎾',
  '跑步': '🏃', '骑行': '🚴', '游泳': '🏊', '健身': '💪', '瑜伽': '🧘',
  '徒步': '🥾', '爬山': '⛰️', '滑板': '🛹', '跳绳': '🪢', '排球': '🏐', '其他': '🎯',
}

/** 消息轮询间隔(ms) */
const POLL_INTERVAL = 3000

export default function ActivityDetail() {
  const { id } = useParams<{ id: string }>()
  const activityId = Number(id)
  const navigate = useNavigate()
  const userId = getCurrentUserId()

  // 详情数据
  const [activity, setActivity] = useState<ActivityInfo | null>(null)
  const [memberCount, setMemberCount] = useState(0)
  const [myRole, setMyRole] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  // 视图: info 活动信息 / chat 群聊（同步 URL ?tab=, 刷新后保持当前视图）
  const [searchParams, setSearchParams] = useSearchParams()
  const [view, setViewState] = useState<'info' | 'chat'>(() =>
    searchParams.get('tab') === 'chat' ? 'chat' : 'info',
  )

  const setView = (v: 'info' | 'chat') => {
    setViewState(v)
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        if (v === 'chat') next.set('tab', 'chat')
        else next.delete('tab')
        return next
      },
      { replace: true },
    )
  }

  const fetchDetail = useCallback(async () => {
    try {
      const result = await activityApi.detail(activityId)
      setActivity(result.activity)
      setMemberCount(result.member_count)
      setMyRole(result.my_role)
    } catch (err: any) {
      if (String(err?.message).includes('不存在')) {
        navigate('/activities', { replace: true })
      }
    } finally {
      setLoading(false)
    }
  }, [activityId, navigate])

  useEffect(() => {
    if (!Number.isFinite(activityId)) return
    fetchDetail()
  }, [activityId, fetchDetail])

  if (loading) {
    return (
      <div className="activities__loading card" style={{ margin: 24 }}>
        <Loader2 size={24} className="spin" /> 正在加载活动...
      </div>
    )
  }

  if (!activity) {
    return (
      <div className="activities__empty card" style={{ margin: 24 }}>
        <p>活动不存在或已被解散</p>
        <button className="btn btn-ghost" onClick={() => navigate('/activities')}>返回活动列表</button>
      </div>
    )
  }

  return (
    <div className="activities">
      {/* 顶部返回 + 标题 */}
      <div className="activity-detail__header card">
        <button className="activity-detail__back" onClick={() => navigate('/activities')}>
          <ChevronLeft size={16} /> 返回
        </button>
        <div className="activity-detail__title-wrap">
          <span className="activity-card__emoji">{SPORT_EMOJI[activity.sport_type] || '🎯'}</span>
          <div>
            <h2 className="activity-detail__title">{activity.title}</h2>
            <div className="activity-detail__meta">
              <span><MapPin size={12} /> {activity.city}{activity.district ? ` · ${activity.district}` : ''}{activity.location ? ` · ${activity.location}` : ''}</span>
              <span><CalendarClock size={12} /> {formatTime(activity.start_time)}</span>
              <span><Users size={12} /> {memberCount}/{activity.max_participants}</span>
            </div>
          </div>
        </div>
        {/* 视图切换 */}
        <div className="activity-detail__tabs">
          <button
            className={`activity-detail__tab ${view === 'info' ? 'activity-detail__tab--active' : ''}`}
            onClick={() => setView('info')}
          >
            <List size={14} /> 活动信息
          </button>
          <button
            className={`activity-detail__tab ${view === 'chat' ? 'activity-detail__tab--active' : ''}`}
            onClick={() => setView('chat')}
          >
            <MessageCircle size={14} /> 群聊
          </button>
        </div>
      </div>

      {view === 'info' ? (
        <ActivityInfoView
          activity={activity}
          memberCount={memberCount}
          myRole={myRole}
          userId={userId}
          onRefresh={fetchDetail}
          onEnterChat={() => setView('chat')}
        />
      ) : (
        <GroupChatView
          activity={activity}
          myRole={myRole}
          userId={userId}
          onRefresh={fetchDetail}
        />
      )}
    </div>
  )
}


// ─── 子组件：活动信息视图 ───

function ActivityInfoView({
  activity,
  memberCount,
  myRole,
  userId,
  onRefresh,
  onEnterChat,
}: {
  activity: ActivityInfo
  memberCount: number
  myRole: string | null
  userId: string
  onRefresh: () => void
  onEnterChat: () => void
}) {
  const navigate = useNavigate()
  const [members, setMembers] = useState<ActivityMemberInfo[]>([])
  const [joining, setJoining] = useState(false)
  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)

  const isOwner = myRole === 'owner' || activity.creator_id === userId
  const full = memberCount >= activity.max_participants

  const showToast = (msg: string, ok: boolean) => {
    setToast({ msg, ok })
    setTimeout(() => setToast(null), 2400)
  }

  const fetchMembers = useCallback(async () => {
    if (!myRole) return
    try {
      const result = await activityApi.members(activity.id)
      setMembers(result.members)
    } catch {
      // 忽略
    }
  }, [activity.id, myRole])

  useEffect(() => {
    fetchMembers()
  }, [fetchMembers])

  const handleJoin = async () => {
    setJoining(true)
    try {
      await activityApi.join(activity.id)
      showToast('已加入活动，自动进入群聊', true)
      onRefresh()
      onEnterChat()
    } catch (err: any) {
      showToast(err?.message || '加入失败', false)
    } finally {
      setJoining(false)
    }
  }

  const handleLeave = async () => {
    try {
      await activityApi.leave(activity.id)
      showToast('已退出活动', true)
      onRefresh()
    } catch (err: any) {
      showToast(err?.message || '退出失败', false)
    }
  }

  const handleDisband = async () => {
    try {
      await activityApi.remove(activity.id)
      navigate('/activities')
    } catch (err: any) {
      showToast(err?.message || '解散失败', false)
      setConfirmDelete(false)
    }
  }

  const handleRemoveMember = async (targetUserId: string) => {
    try {
      await activityApi.removeMember(activity.id, targetUserId)
      showToast(`已移除成员 ${targetUserId}`, true)
      fetchMembers()
      onRefresh()
    } catch (err: any) {
      showToast(err?.message || '移除失败', false)
    }
  }

  return (
    <>
      {/* 信息卡片 */}
      <div className="activity-info card">
        <div className="activity-info__row">
          <span className="activity-info__label">运动类型</span>
          <span className="activity-info__value">{SPORT_EMOJI[activity.sport_type] || ''} {activity.sport_type}</span>
        </div>
        <div className="activity-info__row">
          <span className="activity-info__label">活动地点</span>
          <span className="activity-info__value">{activity.city}{activity.district ? ` ${activity.district}` : ''}{activity.location ? ` · ${activity.location}` : ''}</span>
        </div>
        <div className="activity-info__row">
          <span className="activity-info__label">活动时间</span>
          <span className="activity-info__value">{formatTime(activity.start_time)}</span>
        </div>
        <div className="activity-info__row">
          <span className="activity-info__label">人数</span>
          <span className="activity-info__value">{memberCount} / {activity.max_participants}</span>
        </div>
        <div className="activity-info__row">
          <span className="activity-info__label">发起者</span>
          <span className="activity-info__value">
            {activity.creator_id}
            {activity.creator_id === userId && <span className="activity-info__me">（我）</span>}
          </span>
        </div>
        {activity.description && (
          <div className="activity-info__row activity-info__row--desc">
            <span className="activity-info__label">活动描述</span>
            <p className="activity-info__desc">{activity.description}</p>
          </div>
        )}

        {/* 操作按钮 */}
        <div className="activity-info__actions">
          {!myRole ? (
            <button
              className="btn btn-primary"
              onClick={handleJoin}
              disabled={joining || activity.status !== 'open' || full}
            >
              {joining ? <Loader2 size={14} className="spin" /> : <UserPlus size={14} />}
              {activity.status !== 'open' ? '活动不可加入' : full ? '已满员' : '加入活动'}
            </button>
          ) : (
            <>
              <button className="btn btn-primary" onClick={onEnterChat}>
                <MessageCircle size={14} /> 进入群聊
              </button>
              {!isOwner && (
                <button className="btn btn-ghost" onClick={handleLeave}>
                  <LogOut size={14} /> 退出活动
                </button>
              )}
              {isOwner && (
                <button className="btn btn-ghost activity-info__disband" onClick={() => setConfirmDelete(true)}>
                  <Trash2 size={14} /> 解散活动
                </button>
              )}
            </>
          )}
        </div>
      </div>

      {/* 成员列表（仅成员可见） */}
      {myRole && (
        <div className="activity-members card">
          <div className="activity-members__header">
            <h3 className="activity-members__title">
              <Users size={15} /> 成员列表（{members.length}）
            </h3>
          </div>
          <div className="activity-members__list">
            {members.map((m) => (
              <div key={m.id} className="activity-members__item">
                <div className="activity-members__avatar">
                  {m.nickname.slice(0, 1).toUpperCase()}
                </div>
                <div className="activity-members__info">
                  <span className="activity-members__name">
                    {m.nickname}
                    {m.user_id === userId && <span className="activity-info__me">（我）</span>}
                  </span>
                  <span className="activity-members__id">@{m.user_id}</span>
                </div>
                {m.role === 'owner' ? (
                  <span className="activity-members__owner">
                    <Crown size={12} /> 管理员
                  </span>
                ) : isOwner ? (
                  <button
                    className="activity-members__remove"
                    onClick={() => handleRemoveMember(m.user_id)}
                    title="移除成员"
                  >
                    <UserMinus size={13} /> 移除
                  </button>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 解散确认弹窗 */}
      {confirmDelete && (
        <div className="modal-overlay" onClick={() => setConfirmDelete(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()} style={{ width: 380 }}>
            <div className="modal__header">
              <h3 className="modal__title"><AlertTriangle size={16} /> 解散活动</h3>
              <button className="modal__close" onClick={() => setConfirmDelete(false)}><X size={18} /></button>
            </div>
            <div className="modal__body">
              <p className="activity-confirm__text">
                确定解散「{activity.title}」吗？群聊与消息将一并删除，此操作不可恢复。
              </p>
              <div className="activities-create__actions">
                <button className="btn btn-ghost" onClick={() => setConfirmDelete(false)}>取消</button>
                <button className="btn btn-primary" style={{ background: 'var(--color-danger)' }} onClick={handleDisband}>
                  <Trash2 size={14} /> 确认解散
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {toast && (
        <div className={`takeout-toast ${toast.ok ? 'takeout-toast--ok' : 'takeout-toast--err'}`}>
          {toast.msg}
        </div>
      )}
    </>
  )
}


// ─── 子组件：群聊视图 ───

function GroupChatView({
  activity,
  myRole,
  userId,
  onRefresh,
}: {
  activity: ActivityInfo
  myRole: string | null
  userId: string
  onRefresh: () => void
}) {
  // 聊天状态
  const [group, setGroup] = useState<ActivityGroupInfo | null>(null)
  const [messages, setMessages] = useState<ActivityMessageInfo[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [loadingMessages, setLoadingMessages] = useState(true)
  const [showMembers, setShowMembers] = useState(false)
  const [members, setMembers] = useState<ActivityMemberInfo[]>([])
  const [editingGroup, setEditingGroup] = useState(false)
  const [showAnnouncement, setShowAnnouncement] = useState(false)
  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null)

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const lastMessageIdRef = useRef<number>(0)

  const showToast = (msg: string, ok: boolean) => {
    setToast({ msg, ok })
    setTimeout(() => setToast(null), 2400)
  }

  const isOwner = myRole === 'owner'

  const scrollToBottom = useCallback((smooth = true) => {
    messagesEndRef.current?.scrollIntoView({ behavior: smooth ? 'smooth' : 'auto' })
  }, [])

  // 拉取消息（首次全量 + 轮询增量）
  const fetchMessages = useCallback(async (initial = false) => {
    try {
      const result = await activityApi.messages(activity.id, undefined, 50)
      if (initial) {
        setMessages(result.messages)
        setLoadingMessages(false)
        if (result.messages.length > 0) {
          lastMessageIdRef.current = result.messages[result.messages.length - 1].id
          setTimeout(() => scrollToBottom(false), 50)
        }
      } else {
        // 增量: 只取比本地最新的
        const newOnes = result.messages.filter((m) => m.id > lastMessageIdRef.current)
        if (newOnes.length > 0) {
          setMessages((prev) => [...prev, ...newOnes])
          lastMessageIdRef.current = newOnes[newOnes.length - 1].id
          setTimeout(() => scrollToBottom(), 50)
        }
      }
    } catch {
      if (initial) setLoadingMessages(false)
    }
  }, [activity.id, scrollToBottom])

  const fetchGroup = useCallback(async () => {
    try {
      const result = await activityApi.group(activity.id)
      setGroup(result.group)
    } catch {
      // 忽略
    }
  }, [activity.id])

  const fetchMembers = useCallback(async () => {
    try {
      const result = await activityApi.members(activity.id)
      setMembers(result.members)
    } catch {
      // 忽略
    }
  }, [activity.id])

  useEffect(() => {
    if (myRole) {
      fetchGroup()
      fetchMembers()
      fetchMessages(true)
    } else {
      setLoadingMessages(false)
    }
  }, [myRole, fetchGroup, fetchMembers, fetchMessages])

  // 轮询新消息
  useEffect(() => {
    if (!myRole) return
    const timer = setInterval(() => fetchMessages(false), POLL_INTERVAL)
    return () => clearInterval(timer)
  }, [myRole, fetchMessages])

  const handleSend = async () => {
    const content = input.trim()
    if (!content || sending) return
    setSending(true)
    try {
      const result = await activityApi.sendMessage(activity.id, content)
      setMessages((prev) => [...prev, result.message])
      lastMessageIdRef.current = result.message.id
      setInput('')
      setTimeout(() => scrollToBottom(), 50)
    } catch (err: any) {
      showToast(err?.message || '发送失败', false)
    } finally {
      setSending(false)
    }
  }

  const handleRemoveMember = async (targetUserId: string) => {
    try {
      await activityApi.removeMember(activity.id, targetUserId)
      showToast(`已移除 ${targetUserId}`, true)
      fetchMembers()
      onRefresh()
    } catch (err: any) {
      showToast(err?.message || '移除失败', false)
    }
  }

  // 未加入群聊提示
  if (!myRole) {
    return (
      <div className="activity-chat__forbidden card">
        <MessageCircle size={32} />
        <p>加入活动后即可进入群聊</p>
      </div>
    )
  }

  return (
    <div className="activity-chat card">
      {/* 群聊头部 */}
      <div className="activity-chat__header">
        <div className="activity-chat__header-left">
          <MessageCircle size={16} className="activity-chat__header-icon" />
          <div>
            <span className="activity-chat__group-name">{group?.group_name || activity.title}</span>
            <span className="activity-chat__group-count">{members.length} 人</span>
          </div>
        </div>
        <div className="activity-chat__header-actions">
          {group?.announcement && (
            <div className="activity-chat__ann-wrap">
              <button
                className={`activity-chat__header-btn ${showAnnouncement ? 'activity-chat__header-btn--active' : ''}`}
                onClick={() => setShowAnnouncement(!showAnnouncement)}
                title="群公告"
              >
                <Megaphone size={14} />
              </button>
              {showAnnouncement && (
                <>
                  {/* 点击气泡外区域关闭 */}
                  <button
                    className="activity-chat__ann-backdrop"
                    onClick={() => setShowAnnouncement(false)}
                    aria-label="关闭群公告"
                  />
                  <div className="activity-chat__ann-pop">
                    <div className="activity-chat__ann-title">
                      <Megaphone size={12} /> 群公告
                    </div>
                    <div className="activity-chat__ann-content">{group.announcement}</div>
                  </div>
                </>
              )}
            </div>
          )}
          {isOwner && (
            <button
              className="activity-chat__header-btn"
              onClick={() => setEditingGroup(true)}
              title="修改群信息"
            >
              <Pencil size={13} />
            </button>
          )}
          <button
            className="activity-chat__header-btn"
            onClick={() => setShowMembers(!showMembers)}
            title="成员列表"
          >
            <Users size={14} />
          </button>
        </div>
      </div>

      <div className="activity-chat__body">
        {/* 消息区 */}
        <div className="activity-chat__messages">
          {loadingMessages ? (
            <div className="activity-chat__loading">
              <Loader2 size={20} className="spin" /> 加载消息...
            </div>
          ) : messages.length === 0 ? (
            <div className="activity-chat__loading">
              还没有消息，来打个招呼吧 👋
            </div>
          ) : (
            messages.map((msg) => {
              const mine = msg.sender_id === userId
              return (
                <div key={msg.id} className={`activity-msg ${mine ? 'activity-msg--mine' : ''}`}>
                  {!mine && (
                    <div className="activity-msg__avatar">{(msg.sender_nickname || msg.sender_id).slice(0, 1).toUpperCase()}</div>
                  )}
                  <div className="activity-msg__main">
                    <span className="activity-msg__sender">
                      {mine ? '我' : (msg.sender_nickname || msg.sender_id)}
                      <span className="activity-msg__time">{formatMsgTime(msg.created_at)}</span>
                    </span>
                    <div className={`activity-msg__bubble ${mine ? 'activity-msg__bubble--mine' : ''}`}>
                      {msg.content}
                    </div>
                  </div>
                </div>
              )
            })
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* 成员侧栏 */}
        {showMembers && (
          <div className="activity-chat__members">
            <div className="activity-chat__members-header">
              <span>群成员（{members.length}）</span>
              <button onClick={() => setShowMembers(false)}><X size={14} /></button>
            </div>
            <div className="activity-chat__members-list">
              {members.map((m) => (
                <div key={m.id} className="activity-chat__member">
                  <div className="activity-chat__member-avatar">{m.nickname.slice(0, 1).toUpperCase()}</div>
                  <span className="activity-chat__member-name">
                    {m.nickname}
                    {m.user_id === userId && <em>（我）</em>}
                  </span>
                  {m.role === 'owner' ? (
                    <Crown size={12} className="activity-chat__member-crown" />
                  ) : isOwner ? (
                    <button
                      className="activity-members__remove"
                      onClick={() => handleRemoveMember(m.user_id)}
                    >
                      移除
                    </button>
                  ) : null}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* 输入区 */}
      <div className="activity-chat__input-bar">
        <textarea
          className="activity-chat__input"
          placeholder="输入消息... (Enter 发送, Shift+Enter 换行)"
          value={input}
          rows={1}
          maxLength={2000}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              handleSend()
            }
          }}
        />
        <button
          className="btn btn-primary activity-chat__send"
          onClick={handleSend}
          disabled={!input.trim() || sending}
        >
          {sending ? <Loader2 size={14} className="spin" /> : <Send size={14} />}
        </button>
      </div>

      {/* 修改群信息弹窗 */}
      {editingGroup && group && (
        <EditGroupModal
          group={group}
          onClose={() => setEditingGroup(false)}
          onSaved={(g) => { setGroup(g); showToast('群信息已更新', true) }}
          activityId={activity.id}
        />
      )}

      {toast && (
        <div className={`takeout-toast ${toast.ok ? 'takeout-toast--ok' : 'takeout-toast--err'}`}>
          {toast.msg}
        </div>
      )}
    </div>
  )
}


// ─── 子组件：修改群信息弹窗 ───

function EditGroupModal({
  group,
  activityId,
  onClose,
  onSaved,
}: {
  group: ActivityGroupInfo
  activityId: number
  onClose: () => void
  onSaved: (group: ActivityGroupInfo) => void
}) {
  const [groupName, setGroupName] = useState(group.group_name)
  const [announcement, setAnnouncement] = useState(group.announcement)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  const submit = async () => {
    setSubmitting(true)
    setError('')
    try {
      const result = await activityApi.updateGroup(activityId, {
        group_name: groupName.trim() || undefined,
        announcement,
      })
      onSaved(result.group)
      onClose()
    } catch (err: any) {
      setError(err?.message || '保存失败')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()} style={{ width: 420 }}>
        <div className="modal__header">
          <h3 className="modal__title"><Pencil size={15} /> 修改群信息</h3>
          <button className="modal__close" onClick={onClose}><X size={18} /></button>
        </div>
        <div className="modal__body">
          <div className="activities-create__form">
            <label className="activities-create__label">
              群名称
              <input
                className="activities-create__input"
                value={groupName}
                maxLength={128}
                onChange={(e) => setGroupName(e.target.value)}
              />
            </label>
            <label className="activities-create__label">
              群公告
              <textarea
                className="activities-create__textarea"
                value={announcement}
                maxLength={1000}
                rows={4}
                placeholder="如：请提前 10 分钟到场热身"
                onChange={(e) => setAnnouncement(e.target.value)}
              />
            </label>
            {error && <p className="activities-create__error">{error}</p>}
            <div className="activities-create__actions">
              <button className="btn btn-ghost" onClick={onClose} disabled={submitting}>取消</button>
              <button className="btn btn-primary" onClick={submit} disabled={submitting}>
                {submitting ? <Loader2 size={14} className="spin" /> : null} 保存
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}


// ─── 工具 ───

function formatMsgTime(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (isNaN(d.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  const now = new Date()
  const sameDay = d.toDateString() === now.toDateString()
  return sameDay
    ? `${pad(d.getHours())}:${pad(d.getMinutes())}`
    : `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}
