import { useState, useMemo, useRef, useEffect } from 'react'
import { ChevronLeft, ChevronRight, CalendarDays } from 'lucide-react'
import '../../components/CalendarPanel/CalendarPanel.css'
import './DatePicker.css'

const WEEKDAYS = ['日', '一', '二', '三', '四', '五', '六']
const MONTH_NAMES = ['1月', '2月', '3月', '4月', '5月', '6月', '7月', '8月', '9月', '10月', '11月', '12月']

function toDateStr(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

interface DatePickerProps {
  /** 当前选中日期 YYYY-MM-DD */
  value: string
  /** 选中日期变更回调 */
  onChange: (date: string) => void
  /** 最大可选日期(禁用未来),默认今天 */
  max?: string
  /** 触发按钮宽度 */
  width?: number
}

/** 通用日期选择器(与 CalendarPanel 同款主题,弹出式) */
export default function DatePicker({ value, onChange, max, width = 130 }: DatePickerProps) {
  const todayStr = toDateStr(new Date())
  const maxStr = max || todayStr
  const maxDate = new Date(maxStr + 'T00:00:00')

  const [open, setOpen] = useState(false)
  // 当前展示月份(初始为选中日期所在月)
  const initial = value ? new Date(value + 'T00:00:00') : new Date()
  const [viewYear, setViewYear] = useState(initial.getFullYear())
  const [viewMonth, setViewMonth] = useState(initial.getMonth())
  const rootRef = useRef<HTMLDivElement>(null)

  // 点击外部关闭
  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  // 选中日期变化时同步视图月份
  useEffect(() => {
    if (value) {
      const d = new Date(value + 'T00:00:00')
      setViewYear(d.getFullYear())
      setViewMonth(d.getMonth())
    }
  }, [value])

  const calendarDays = useMemo(() => {
    const firstDay = new Date(viewYear, viewMonth, 1)
    const lastDay = new Date(viewYear, viewMonth + 1, 0)
    const firstWeekday = firstDay.getDay()
    const daysInMonth = lastDay.getDate()

    const days: Array<{ date: Date; isOtherMonth: boolean }> = []
    for (let i = firstWeekday - 1; i >= 0; i--) {
      days.push({ date: new Date(viewYear, viewMonth, -i), isOtherMonth: true })
    }
    for (let i = 1; i <= daysInMonth; i++) {
      days.push({ date: new Date(viewYear, viewMonth, i), isOtherMonth: false })
    }
    const remaining = 42 - days.length
    for (let i = 1; i <= remaining; i++) {
      days.push({ date: new Date(viewYear, viewMonth + 1, i), isOtherMonth: true })
    }
    return days
  }, [viewYear, viewMonth])

  const handlePrevMonth = () => {
    if (viewMonth === 0) { setViewYear(viewYear - 1); setViewMonth(11) }
    else setViewMonth(viewMonth - 1)
  }
  const handleNextMonth = () => {
    if (viewMonth === 11) { setViewYear(viewYear + 1); setViewMonth(0) }
    else setViewMonth(viewMonth + 1)
  }

  const handleDayClick = (dateStr: string, disabled: boolean) => {
    if (disabled) return
    onChange(dateStr)
    setOpen(false)
  }

  const handleBackToToday = () => {
    if (todayStr <= maxStr) {
      onChange(todayStr)
      setOpen(false)
    }
  }

  return (
    <div className="date-picker" ref={rootRef}>
      <button
        className="date-picker__trigger"
        style={{ width }}
        onClick={() => setOpen(!open)}
        title="选择日期"
      >
        <CalendarDays size={14} />
        <span>{value}</span>
        <ChevronRight
          size={12}
          style={{ transform: open ? 'rotate(90deg)' : 'rotate(-90deg)' }}
        />
      </button>

      {open && (
        <div className="date-picker__popover">
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
                const isSelected = dateStr === value
                const isDisabled = day.date > maxDate && !isToday
                return (
                  <button
                    key={idx}
                    className={[
                      'calendar-day',
                      day.isOtherMonth ? 'calendar-day--other' : '',
                      isToday ? 'calendar-day--today' : '',
                      isSelected ? 'calendar-day--selected' : '',
                      isDisabled ? 'calendar-day--future' : '',
                    ].filter(Boolean).join(' ')}
                    onClick={() => handleDayClick(dateStr, isDisabled)}
                    disabled={isDisabled}
                  >
                    {day.date.getDate()}
                  </button>
                )
              })}
            </div>
          </div>

          {value !== todayStr && (
            <div className="calendar-footer">
              <button className="calendar-footer__today-btn" onClick={handleBackToToday}>
                回到今天
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
