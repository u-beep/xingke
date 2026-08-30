import { useState, useMemo, useEffect } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { chatApi } from '../../services/api'
import { useChat } from '../../store/ChatContext'
import { getCurrentUserId } from '../../services/authStore'
import './CalendarPanel.css'

const USER_ID = getCurrentUserId()
const WEEKDAYS = ['日', '一', '二', '三', '四', '五', '六']
const MONTH_NAMES = ['1月', '2月', '3月', '4月', '5月', '6月', '7月', '8月', '9月', '10月', '11月', '12月']

function toDateStr(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

export default function CalendarPanel({ visible }: { visible: boolean }) {
  const { currentDate, loadSessionByDate } = useChat()
  const today = new Date()
  const todayStr = toDateStr(today)

  // 当前显示的月份
  const [viewYear, setViewYear] = useState(today.getFullYear())
  const [viewMonth, setViewMonth] = useState(today.getMonth())

  // 有对话记录的日期集合
  const [chatDates, setChatDates] = useState<Set<string>>(new Set())

  // 加载当前月份有对话记录的日期
  useEffect(() => {
    const loadChatDates = async () => {
      // 简单方案：查询最近30天的会话列表，提取日期
      try {
        const result = await chatApi.listSessions(USER_ID)
        const dates = new Set<string>()
        for (const s of result.sessions || []) {
          if (s.created_at) {
            // created_at 是 ISO 字符串，取日期部分
            const d = new Date(s.created_at)
            // 转为本地日期
            const dateStr = toDateStr(d)
            dates.add(dateStr)
          }
        }
        setChatDates(dates)
      } catch {
        // 静默失败
      }
    }
    loadChatDates()
  }, [currentDate])  // currentDate 变化时重新加载

  // 生成日历网格
  const calendarDays = useMemo(() => {
    const firstDay = new Date(viewYear, viewMonth, 1)
    const lastDay = new Date(viewYear, viewMonth + 1, 0)
    const firstWeekday = firstDay.getDay()  // 0=周日
    const daysInMonth = lastDay.getDate()

    const days: Array<{ date: Date; isOtherMonth: boolean }> = []

    // 上月填充
    for (let i = firstWeekday - 1; i >= 0; i--) {
      days.push({ date: new Date(viewYear, viewMonth, -i), isOtherMonth: true })
    }
    // 本月
    for (let i = 1; i <= daysInMonth; i++) {
      days.push({ date: new Date(viewYear, viewMonth, i), isOtherMonth: false })
    }
    // 下月填充到 42 格（6行）
    const remaining = 42 - days.length
    for (let i = 1; i <= remaining; i++) {
      days.push({ date: new Date(viewYear, viewMonth + 1, i), isOtherMonth: true })
    }

    return days
  }, [viewYear, viewMonth])

  const handlePrevMonth = () => {
    if (viewMonth === 0) {
      setViewYear(viewYear - 1)
      setViewMonth(11)
    } else {
      setViewMonth(viewMonth - 1)
    }
  }

  const handleNextMonth = () => {
    if (viewMonth === 11) {
      setViewYear(viewYear + 1)
      setViewMonth(0)
    } else {
      setViewMonth(viewMonth + 1)
    }
  }

  const handleDayClick = (dateStr: string, isFuture: boolean) => {
    if (isFuture) return
    loadSessionByDate(dateStr)
  }

  const handleBackToToday = () => {
    setViewYear(today.getFullYear())
    setViewMonth(today.getMonth())
    loadSessionByDate(todayStr)
  }

  return (
    <div className={`calendar-panel ${!visible ? 'calendar-panel--hidden' : ''}`}>
      {/* 月份切换 */}
      <div className="calendar-header">
        <span className="calendar-header__title">
          {viewYear}年 {MONTH_NAMES[viewMonth]}
        </span>
        <div className="calendar-header__nav">
          <button className="calendar-header__btn" onClick={handlePrevMonth} title="上一月">
            <ChevronLeft size={16} />
          </button>
          <button className="calendar-header__btn" onClick={handleNextMonth} title="下一月">
            <ChevronRight size={16} />
          </button>
        </div>
      </div>

      {/* 日历主体 */}
      <div className="calendar-body">
        <div className="calendar-weekdays">
          {WEEKDAYS.map((w) => (
            <div key={w} className="calendar-weekday">{w}</div>
          ))}
        </div>
        <div className="calendar-days">
          {calendarDays.map((day, idx) => {
            const dateStr = toDateStr(day.date)
            const isToday = dateStr === todayStr
            const isSelected = dateStr === currentDate
            const isFuture = day.date > today && !isToday
            const hasChat = chatDates.has(dateStr)

            return (
              <button
                key={idx}
                className={[
                  'calendar-day',
                  day.isOtherMonth ? 'calendar-day--other' : '',
                  isToday ? 'calendar-day--today' : '',
                  isSelected ? 'calendar-day--selected' : '',
                  hasChat ? 'calendar-day--has-chat' : '',
                  isFuture ? 'calendar-day--future' : '',
                ].filter(Boolean).join(' ')}
                onClick={() => handleDayClick(dateStr, isFuture)}
                disabled={isFuture}
                title={hasChat ? `${dateStr} 有对话记录` : dateStr}
              >
                {day.date.getDate()}
              </button>
            )
          })}
        </div>
      </div>

      {/* 底部 */}
      <div className="calendar-footer">
        <div className="calendar-footer__label">
          <span className="calendar-footer__dot" />
          有对话记录的日期
        </div>
        {currentDate !== todayStr && (
          <button className="calendar-footer__today-btn" onClick={handleBackToToday}>
            回到今天
          </button>
        )}
      </div>
    </div>
  )
}
