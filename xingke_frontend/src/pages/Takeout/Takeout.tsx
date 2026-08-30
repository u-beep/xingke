import { useState, useEffect } from 'react'
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
  Star,
  Clock,
  Truck,
  ChevronLeft,
  Store,
} from 'lucide-react'
import {
  takeoutApi,
  type TakeoutShopInfo,
  type TakeoutShopDetail,
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
  // 一级：店家列表 / 二级：店内菜单
  const [shops, setShops] = useState<TakeoutShopInfo[]>([])
  const [shopCategories, setShopCategories] = useState<string[]>([])
  const [activeShopCategory, setActiveShopCategory] = useState<string>('')
  const [loadingShops, setLoadingShops] = useState(true)

  const [shopDetail, setShopDetail] = useState<TakeoutShopDetail | null>(null)
  const [loadingMenu, setLoadingMenu] = useState(false)

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
    fetchShops()
    fetchShopCategories()
    fetchToday()
  }, [])

  useEffect(() => {
    if (activeShopCategory) {
      takeoutApi.shops(activeShopCategory).then((r) => setShops(r.shops))
    } else {
      fetchShops()
    }
  }, [activeShopCategory])

  const fetchShops = async () => {
    setLoadingShops(true)
    try {
      const result = await takeoutApi.shops()
      setShops(result.shops)
    } catch (err) {
      console.error('获取店家列表失败:', err)
    } finally {
      setLoadingShops(false)
    }
  }

  const fetchShopCategories = async () => {
    try {
      const result = await takeoutApi.shopCategories()
      setShopCategories(result.categories)
    } catch (err) {
      console.error('获取品类失败:', err)
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

  /** 进入店家点餐页 */
  const enterShop = async (shop: TakeoutShopInfo) => {
    setLoadingMenu(true)
    try {
      const detail = await takeoutApi.shopDetail(shop.shop_name)
      setShopDetail(detail)
    } catch (err) {
      console.error('获取店家菜单失败:', err)
    } finally {
      setLoadingMenu(false)
    }
  }

  const exitShop = () => setShopDetail(null)

  const openCheckout = (dish: TakeoutDishInfo) => {
    setCheckoutDish(dish)
    setQuantity(1)
    setMealType('lunch')
    setIncludeInStats(true)
  }

  const closeCheckout = () => setCheckoutDish(null)

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

  // ─── 二级视图：店内点餐页 ───
  if (shopDetail) {
    return (
      <div className="takeout">
        {/* 店家门头 */}
        <div className="takeout-shop-header card">
          <button className="takeout-shop-header__back" onClick={exitShop} title="返回店家列表">
            <ChevronLeft size={18} />
            <span>返回</span>
          </button>
          <div className="takeout-shop-header__main">
            {shopDetail.logo_url ? (
              <img src={shopDetail.logo_url} alt={shopDetail.shop_name} className="takeout-shop-header__logo" />
            ) : (
              <div className="takeout-shop-header__logo takeout-shop-header__logo--placeholder">
                <Store size={22} />
              </div>
            )}
            <div className="takeout-shop-header__info">
              <h2 className="takeout-shop-header__name">{shopDetail.shop_name}</h2>
              <div className="takeout-shop-header__meta">
                <span className="takeout-shop-header__rating">
                  <Star size={12} /> {shopDetail.rating.toFixed(1)}
                </span>
                <span>月售 {shopDetail.monthly_sales}</span>
                <span>
                  <Clock size={12} /> 约{shopDetail.delivery_minutes}分钟送达
                </span>
                <span>
                  <Truck size={12} /> 起送¥{shopDetail.min_order_price} · 配送¥{shopDetail.delivery_fee}
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* 今日订单概览 */}
        <SummaryBar summary={summary} />

        {/* 店内菜单（按分类分组） */}
        {loadingMenu ? (
          <div className="takeout__loading card">
            <Loader2 size={24} className="spin" /> 正在加载店内菜单...
          </div>
        ) : (
          shopDetail.menu_groups.map((group) => (
            <div key={group.category} className="takeout-group">
              <h3 className="takeout-group__title">{group.category}</h3>
              <div className="takeout-group__grid">
                {group.dishes.map((dish) => (
                  <DishCard key={dish.id} dish={dish} onOrder={() => openCheckout(dish)} />
                ))}
              </div>
            </div>
          ))
        )}

        {/* 今日订单列表 */}
        {orders.length > 0 && (
          <div className="takeout__orders">
            <h3 className="takeout-orders__title">今日订单</h3>
            <div className="takeout-orders__list">
              {orders.map((order) => (
                <OrderRow key={order.id} order={order} onCancel={() => handleCancelOrder(order.id)} />
              ))}
            </div>
          </div>
        )}

        {/* 下单弹窗 */}
        {checkoutDish && (
          <CheckoutModal
            dish={checkoutDish}
            quantity={quantity}
            setQuantity={setQuantity}
            mealType={mealType}
            setMealType={setMealType}
            includeInStats={includeInStats}
            setIncludeInStats={setIncludeInStats}
            submitting={submitting}
            onClose={closeCheckout}
            onSubmit={handlePlaceOrder}
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

  // ─── 一级视图：店家列表（仿美团首页） ───
  return (
    <div className="takeout">
      <SummaryBar summary={summary} />

      {/* 品类筛选 */}
      <div className="takeout__tabs">
        <button
          className={`takeout-tab ${activeShopCategory === '' ? 'takeout-tab--active' : ''}`}
          onClick={() => setActiveShopCategory('')}
        >
          全部
        </button>
        {shopCategories.map((c) => (
          <button
            key={c}
            className={`takeout-tab ${activeShopCategory === c ? 'takeout-tab--active' : ''}`}
            onClick={() => setActiveShopCategory(c)}
          >
            {c}
          </button>
        ))}
      </div>

      {/* 店家列表 */}
      {loadingShops ? (
        <div className="takeout__loading card">
          <Loader2 size={24} className="spin" /> 正在加载店家...
        </div>
      ) : shops.length === 0 ? (
        <div className="takeout__empty card">暂无可选店家</div>
      ) : (
        <div className="takeout-shops">
          {shops.map((shop) => (
            <div key={shop.id} className="shop-card card" onClick={() => enterShop(shop)}>
              {shop.logo_url ? (
                <img src={shop.logo_url} alt={shop.shop_name} className="shop-card__logo" />
              ) : (
                <div className="shop-card__logo shop-card__logo--placeholder">
                  <Store size={24} />
                </div>
              )}
              <div className="shop-card__body">
                <div className="shop-card__title-row">
                  <span className="shop-card__name">{shop.shop_name}</span>
                  <span className="shop-card__rating">
                    <Star size={12} /> {shop.rating.toFixed(1)}
                  </span>
                </div>
                <div className="shop-card__meta">
                  <span>月售 {shop.monthly_sales}</span>
                  <span>约{shop.delivery_minutes}分钟</span>
                  <span>
                    起送¥{shop.min_order_price} · 配送¥{shop.delivery_fee}
                  </span>
                </div>
                <div className="shop-card__tags">
                  <span className="shop-card__tag">{shop.category}</span>
                </div>
              </div>
              <ChevronRightish />
            </div>
          ))}
        </div>
      )}

      {/* 今日订单列表 */}
      {orders.length > 0 && (
        <div className="takeout__orders">
          <h3 className="takeout-orders__title">今日订单</h3>
          <div className="takeout-orders__list">
            {orders.map((order) => (
              <OrderRow key={order.id} order={order} onCancel={() => handleCancelOrder(order.id)} />
            ))}
          </div>
        </div>
      )}

      {/* 下单弹窗 */}
      {checkoutDish && (
        <CheckoutModal
          dish={checkoutDish}
          quantity={quantity}
          setQuantity={setQuantity}
          mealType={mealType}
          setMealType={setMealType}
          includeInStats={includeInStats}
          setIncludeInStats={setIncludeInStats}
          submitting={submitting}
          onClose={closeCheckout}
          onSubmit={handlePlaceOrder}
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

/** 右侧箭头占位（店家卡片） */
function ChevronRightish() {
  return <span className="shop-card__arrow">›</span>
}

/** 今日汇总条 */
function SummaryBar({ summary }: { summary: TakeoutSummary | null }) {
  return (
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
  )
}

// ─── 子组件：下单弹窗 ───

function CheckoutModal({
  dish,
  quantity,
  setQuantity,
  mealType,
  setMealType,
  includeInStats,
  setIncludeInStats,
  submitting,
  onClose,
  onSubmit,
}: {
  dish: TakeoutDishInfo
  quantity: number
  setQuantity: (q: number) => void
  mealType: string
  setMealType: (m: string) => void
  includeInStats: boolean
  setIncludeInStats: (v: boolean) => void
  submitting: boolean
  onClose: () => void
  onSubmit: () => void
}) {
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal takeout-checkout" onClick={(e) => e.stopPropagation()}>
        <div className="modal__header">
          <h3 className="modal__title">确认下单</h3>
          <button className="modal__close" onClick={onClose}>
            <X size={18} />
          </button>
        </div>
        <div className="modal__body">
          <div className="takeout-checkout__dish">
            {dish.image_url ? (
              <img src={dish.image_url} alt={dish.dish_name} className="takeout-checkout__img" />
            ) : (
              <div className="takeout-checkout__img takeout-checkout__img--placeholder">
                <ImageOff size={20} />
              </div>
            )}
            <div className="takeout-checkout__info">
              <span className="takeout-checkout__shop">{dish.shop_name}</span>
              <span className="takeout-checkout__name">{dish.dish_name}</span>
              <span className="takeout-checkout__desc">{dish.description}</span>
              <div className="takeout-checkout__meta">
                <span><Flame size={12} /> {(dish.calories ?? 0).toFixed(0)} kcal</span>
                <span><Beef size={12} /> {(dish.protein_g ?? 0).toFixed(1)}g 蛋白</span>
                {dish.price > 0 && (
                  <span className="takeout-checkout__price">¥{dish.price}</span>
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
                onClick={() => setQuantity(Math.max(1, quantity - 1))}
                disabled={quantity <= 1}
              >
                <Minus size={14} />
              </button>
              <span className="takeout-qty-value">{quantity}</span>
              <button
                className="takeout-qty-btn"
                onClick={() => setQuantity(Math.min(9, quantity + 1))}
              >
                <Plus size={14} />
              </button>
            </div>
            <span className="takeout-checkout__total">
              合计 <Flame size={12} />
              {((dish.calories ?? 0) * quantity).toFixed(0)} kcal ·
              <Beef size={12} />
              {((dish.protein_g ?? 0) * quantity).toFixed(1)}g
            </span>
          </div>

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
            <button className="btn btn-ghost" onClick={onClose} disabled={submitting}>
              取消
            </button>
            <button className="btn btn-primary" onClick={onSubmit} disabled={submitting}>
              {submitting ? <Loader2 size={14} className="spin" /> : <ShoppingCart size={14} />}
              确认下单
            </button>
          </div>
        </div>
      </div>
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
          {order.shop_name && <span className="takeout-order-row__shop">{order.shop_name} · </span>}
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
