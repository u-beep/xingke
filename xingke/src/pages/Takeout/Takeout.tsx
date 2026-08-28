import { useState, useEffect, useMemo } from 'react'
import {
  ShoppingCart,
  Flame,
  Beef,
  X,
  Minus,
  Plus,
  CheckCircle2,
  Trash2,
  Loader2,
  Calculator,
  ImageOff,
} from 'lucide-react'
import {
  takeoutApi,
  type TakeoutDishInfo,
  type TakeoutOrderInfo,
  type TakeoutSummary,
} from '../../services/api'
import './Takeout.css'

const MEAL_TYPES = [
  { value: 'breakfast', label: '早餐' },
  { value: 'lunch', label: '午餐' },
  { value: 'dinner', label: '晚餐' },
  { value: 'snack', label: '加餐' },
]

const MEAL_LABEL: Record<string, string> = {
  breakfast: '早餐',
  lunch: '午餐',
  dinner: '晚餐',
  snack: '加餐',
}

export default function Takeout() {
  const [dishes, setDishes] = useState<TakeoutDishInfo[]>([])
  const [categories, setCategories] = useState<string[]>([])
  const [activeCategory, setActiveCategory] = useState<string>('')
  const [loading, setLoading] = useState(true)

  const [orders, setOrders] = useState<TakeoutOrderInfo[]>([])
  const [summary, setSummary] = useState<TakeoutSummary | null>(null)

  // 下单弹窗状态
  const [checkoutDish, setCheckoutDish] = useState<TakeoutDishInfo | null>(null)
  const [quantity, setQuantity] = useState(1)
  const [mealType, setMealType] = useState('lunch')
  const [includeInStats, setIncludeInStats] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null)

  useEffect(() => {
    fetchDishes()
    fetchCategories()
    fetchToday()
  }, [])

  useEffect(() => {
    if (activeCategory) {
      takeoutApi.dishes(activeCategory).then((r) => setDishes(r.dishes))
    } else {
      fetchDishes()
    }
  }, [activeCategory])

  const fetchDishes = async () => {
    setLoading(true)
    try {
      const result = await takeoutApi.dishes()
      setDishes(result.dishes)
    } catch (err) {
      console.error('获取外卖菜单失败:', err)
    } finally {
      setLoading(false)
    }
  }

  const fetchCategories = async () => {
    try {
      const result = await takeoutApi.categories()
      setCategories(result.categories)
    } catch (err) {
      console.error('获取分类失败:', err)
    }
  }

  const fetchToday = async () => {
    try {
      const result = await takeoutApi.todayOrders()
      setOrders(result.orders)
      setSummary(result.summary)
    } catch (err) {
      console.error('获取今日订单失败:', err)
    }
  }

  const openCheckout = (dish: TakeoutDishInfo) => {
    setCheckoutDish(dish)
    setQuantity(1)
    setMealType('lunch')
    setIncludeInStats(true)
  }

  const closeCheckout = () => {
    setCheckoutDish(null)
  }

  const showToast = (msg: string, ok: boolean) => {
    setToast({ msg, ok })
    setTimeout(() => setToast(null), 2400)
  }

  const handlePlaceOrder = async () => {
    if (!checkoutDish) return
    setSubmitting(true)
    try {
      const result = await takeoutApi.placeOrder({
        dish_id: checkoutDish.id,
        quantity,
        meal_type: mealType,
        include_in_stats: includeInStats,
      })
      if (result.success) {
        showToast(
          includeInStats
            ? `下单成功，已计入当日热量 ${result.today_summary?.stats_calories || 0} kcal`
            : '下单成功（未计入今日统计）',
          true,
        )
        closeCheckout()
        await fetchToday()
      } else {
        showToast(result.message || '下单失败', false)
      }
    } catch (err) {
      showToast('下单失败：服务异常', false)
    } finally {
      setSubmitting(false)
    }
  }

  const handleCancelOrder = async (orderId: number) => {
    try {
      const result = await takeoutApi.cancelOrder(orderId)
      if (result.success) {
        showToast('订单已取消', true)
        await fetchToday()
      } else {
        showToast(result.message || '取消失败', false)
      }
    } catch (err) {
      showToast('取消失败：服务异常', false)
    }
  }

  const groupedDishes = useMemo(() => {
    const map = new Map<string, TakeoutDishInfo[]>()
    for (const d of dishes) {
      const cat = d.category || '其他'
      if (!map.has(cat)) map.set(cat, [])
      map.get(cat)!.push(d)
    }
    return Array.from(map.entries())
  }, [dishes])

  return (
    <div className="takeout">
      {/* 今日订单概览 */}
      <div className="takeout__summary card">
        <div className="takeout-summary__item">
          <ShoppingCart size={20} className="takeout-summary__icon" />
          <div>
            <span className="takeout-summary__value">{summary?.order_count ?? 0}</span>
            <span className="takeout-summary__label">今日订单</span>
          </div>
        </div>
        <div className="takeout-summary__item">
          <Flame size={20} className="takeout-summary__icon" />
          <div>
            <span className="takeout-summary__value">
              {summary?.total_calories?.toFixed(0) ?? 0}
            </span>
            <span className="takeout-summary__label">外卖热量(kcal)</span>
          </div>
        </div>
        <div className="takeout-summary__item">
          <Calculator size={20} className="takeout-summary__icon" />
          <div>
            <span className="takeout-summary__value takeout-summary__value--accent">
              {summary?.stats_calories?.toFixed(0) ?? 0}
            </span>
            <span className="takeout-summary__label">已计入统计(kcal)</span>
          </div>
        </div>
        <div className="takeout-summary__item">
          <Beef size={20} className="takeout-summary__icon" />
          <div>
            <span className="takeout-summary__value takeout-summary__value--accent">
              {summary?.stats_protein_g?.toFixed(1) ?? 0}
            </span>
            <span className="takeout-summary__label">已计入蛋白质(g)</span>
          </div>
        </div>
      </div>

      {/* 分类筛选 */}
      <div className="takeout__tabs">
        <button
          className={`takeout-tab ${activeCategory === '' ? 'takeout-tab--active' : ''}`}
          onClick={() => setActiveCategory('')}
        >
          全部
        </button>
        {categories.map((c) => (
          <button
            key={c}
            className={`takeout-tab ${activeCategory === c ? 'takeout-tab--active' : ''}`}
            onClick={() => setActiveCategory(c)}
          >
            {c}
          </button>
        ))}
      </div>

      {/* 菜品列表 */}
      <div className="takeout__dishes">
        {loading ? (
          <div className="takeout__loading card">
            <Loader2 size={24} className="spin" /> 正在加载外卖菜单...
          </div>
        ) : dishes.length === 0 ? (
          <div className="takeout__empty card">暂无可选菜品</div>
        ) : (
          groupedDishes.map(([cat, items]) => (
            <div key={cat} className="takeout-group">
              <h3 className="takeout-group__title">{cat}</h3>
              <div className="takeout-group__grid">
                {items.map((dish) => (
                  <DishCard
                    key={dish.id}
                    dish={dish}
                    onOrder={() => openCheckout(dish)}
                  />
                ))}
              </div>
            </div>
          ))
        )}
      </div>

      {/* 今日订单列表 */}
      {orders.length > 0 && (
        <div className="takeout__orders">
          <h3 className="takeout-orders__title">今日订单</h3>
          <div className="takeout-orders__list">
            {orders.map((order) => (
              <OrderRow
                key={order.id}
                order={order}
                onCancel={() => handleCancelOrder(order.id)}
              />
            ))}
          </div>
        </div>
      )}

      {/* 下单弹窗 */}
      {checkoutDish && (
        <div className="modal-overlay" onClick={closeCheckout}>
          <div className="modal takeout-checkout" onClick={(e) => e.stopPropagation()}>
            <div className="modal__header">
              <h3 className="modal__title">确认下单</h3>
              <button className="modal__close" onClick={closeCheckout}>
                <X size={18} />
              </button>
            </div>
            <div className="modal__body">
              <div className="takeout-checkout__dish">
                {checkoutDish.image_url ? (
                  <img
                    src={checkoutDish.image_url}
                    alt={checkoutDish.dish_name}
                    className="takeout-checkout__img"
                  />
                ) : (
                  <div className="takeout-checkout__img takeout-checkout__img--placeholder">
                    <ImageOff size={20} />
                  </div>
                )}
                <div className="takeout-checkout__info">
                  <span className="takeout-checkout__name">{checkoutDish.dish_name}</span>
                  <span className="takeout-checkout__desc">{checkoutDish.description}</span>
                  <div className="takeout-checkout__meta">
                    <span><Flame size={12} /> {(checkoutDish.calories ?? 0).toFixed(0)} kcal</span>
                    <span><Beef size={12} /> {(checkoutDish.protein_g ?? 0).toFixed(1)}g 蛋白</span>
                    {checkoutDish.price > 0 && (
                      <span className="takeout-checkout__price">¥{checkoutDish.price}</span>
                    )}
                  </div>
                </div>
              </div>

              <div className="takeout-checkout__row">
                <label className="takeout-checkout__label">餐次</label>
                <div className="takeout-checkout__meal-types">
                  {MEAL_TYPES.map((m) => (
                    <button
                      key={m.value}
                      className={`takeout-meal-btn ${mealType === m.value ? 'takeout-meal-btn--active' : ''}`}
                      onClick={() => setMealType(m.value)}
                    >
                      {m.label}
                    </button>
                  ))}
                </div>
              </div>

              <div className="takeout-checkout__row">
                <label className="takeout-checkout__label">数量</label>
                <div className="takeout-checkout__quantity">
                  <button
                    className="takeout-qty-btn"
                    onClick={() => setQuantity((q) => Math.max(1, q - 1))}
                    disabled={quantity <= 1}
                  >
                    <Minus size={14} />
                  </button>
                  <span className="takeout-qty-value">{quantity}</span>
                  <button
                    className="takeout-qty-btn"
                    onClick={() => setQuantity((q) => Math.min(9, q + 1))}
                  >
                    <Plus size={14} />
                  </button>
                </div>
                <span className="takeout-checkout__total">
                  合计 <Flame size={12} />
                  {((checkoutDish.calories ?? 0) * quantity).toFixed(0)} kcal ·
                  <Beef size={12} />
                  {((checkoutDish.protein_g ?? 0) * quantity).toFixed(1)}g
                </span>
              </div>

              {/* 关键：是否计入统计勾选项 */}
              <label className="takeout-checkout__stats-toggle">
                <input
                  type="checkbox"
                  checked={includeInStats}
                  onChange={(e) => setIncludeInStats(e.target.checked)}
                />
                <span className="takeout-checkout__stats-label">
                  <CheckCircle2 size={16} />
                  将这份外卖计入当日热量与蛋白质统计
                </span>
              </label>
              {!includeInStats && (
                <p className="takeout-checkout__stats-hint">
                  未勾选时，订单仍会写入饮食记录中可见，但不会影响当日热量与蛋白质统计数据。
                </p>
              )}

              <div className="takeout-checkout__actions">
                <button className="btn btn-ghost" onClick={closeCheckout} disabled={submitting}>
                  取消
                </button>
                <button
                  className="btn btn-primary"
                  onClick={handlePlaceOrder}
                  disabled={submitting}
                >
                  {submitting ? <Loader2 size={14} className="spin" /> : <ShoppingCart size={14} />}
                  确认下单
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Toast 提示 */}
      {toast && (
        <div className={`takeout-toast ${toast.ok ? 'takeout-toast--ok' : 'takeout-toast--err'}`}>
          {toast.msg}
        </div>
      )}
    </div>
  )
}

// ─── 子组件：菜品卡片 ───

function DishCard({
  dish,
  onOrder,
}: {
  dish: TakeoutDishInfo
  onOrder: () => void
}) {
  return (
    <div className="dish-card card">
      {dish.image_url ? (
        <img src={dish.image_url} alt={dish.dish_name} className="dish-card__img" />
      ) : (
        <div className="dish-card__img dish-card__img--placeholder">
          <ImageOff size={20} />
        </div>
      )}
      <div className="dish-card__body">
        <span className="dish-card__name">{dish.dish_name}</span>
        <span className="dish-card__desc">{dish.description}</span>
        <div className="dish-card__meta">
          <span><Flame size={12} /> {(dish.calories ?? 0).toFixed(0)} kcal</span>
          <span><Beef size={12} /> {(dish.protein_g ?? 0).toFixed(1)}g 蛋白</span>
        </div>
        <div className="dish-card__footer">
          {dish.price > 0 ? (
            <span className="dish-card__price">¥{dish.price.toFixed(0)}</span>
          ) : (
            <span className="dish-card__price dish-card__price--free">免费</span>
          )}
          <button className="btn btn-primary dish-card__order-btn" onClick={onOrder}>
            <ShoppingCart size={12} /> 立即下单
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── 子组件：订单行 ───

function OrderRow({
  order,
  onCancel,
}: {
  order: TakeoutOrderInfo
  onCancel: () => void
}) {
  const cancelled = order.order_status === 'cancelled'
  return (
    <div className={`takeout-order-row card ${cancelled ? 'takeout-order-row--cancelled' : ''}`}>
      {order.image_url ? (
        <img src={order.image_url} alt={order.dish_name} className="takeout-order-row__img" />
      ) : (
        <div className="takeout-order-row__img takeout-order-row__img--placeholder">
          <ImageOff size={14} />
        </div>
      )}
      <div className="takeout-order-row__info">
        <span className="takeout-order-row__name">
          {order.dish_name} <span className="takeout-order-row__qty">x{order.quantity}</span>
        </span>
        <span className="takeout-order-row__meta">
          {MEAL_LABEL[order.meal_type] || order.meal_type} · {order.total_calories.toFixed(0)} kcal ·
          {order.total_protein_g.toFixed(1)}g 蛋白
        </span>
      </div>
      <div className="takeout-order-row__right">
        {cancelled ? (
          <span className="takeout-order-row__status takeout-order-row__status--cancelled">已取消</span>
        ) : order.include_in_stats ? (
          <span className="takeout-order-row__status takeout-order-row__status--stats">
            <CheckCircle2 size={12} /> 已计入统计
          </span>
        ) : (
          <span className="takeout-order-row__status takeout-order-row__status--skip">未计入统计</span>
        )}
        {!cancelled && (
          <button className="btn btn-ghost takeout-order-row__cancel" onClick={onCancel}>
            <Trash2 size={12} /> 取消
          </button>
        )}
      </div>
    </div>
  )
}
