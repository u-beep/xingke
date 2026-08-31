import { useState, useEffect, useLayoutEffect, useRef, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  Refrigerator,
  Camera,
  Plus,
  Pencil,
  Trash2,
  Sparkles,
  Loader2,
  X,
  CheckCircle2,
  AlertTriangle,
  ImageOff,
  ChefHat,
  RefreshCw,
  Flame,
  Beef,
  Wheat,
  Droplet,
} from 'lucide-react'
import {
  fridgeApi,
  fileToBase64,
  type FridgeItemInfo,
  type FridgeRecipe,
  type FridgeRecognizedItem,
} from '../../services/api'
import { authedImageUrl } from '../../services/authStore'
import './Fridge.css'

const CATEGORIES = ['蔬菜', '肉蛋', '主食', '水果', '乳制品', '调味', '其他']

const UNITS = ['g', '个', '包', 'ml']

/** 快捷偏好下拉选项（与输入框互斥：选中选项后输入框置灰；输入框有内容后下拉框置灰） */
const PREF_CHIP_OPTIONS = ['快手菜', '凉菜', '减脂餐', '家常菜', '默认']

/** ISO分钟格式 → "YYYY-MM-DD HH:MM" */
function fmtMin(iso?: string | null): string {
  if (!iso) return ''
  const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/)
  return m ? `${m[1]}-${m[2]}-${m[3]} ${m[4]}:${m[5]}` : iso
}

/** 过期状态: none(无)/ok(正常)/soon(24h内)/over(已过期) */
function expireState(expiresAt?: string | null): 'none' | 'ok' | 'soon' | 'over' {
  if (!expiresAt) return 'none'
  const t = new Date(expiresAt).getTime()
  if (isNaN(t)) return 'none'
  const now = Date.now()
  if (t <= now) return 'over'
  if (t - now <= 24 * 3600 * 1000) return 'soon'
  return 'ok'
}

interface ItemForm {
  name: string
  category: string
  quantity_g: number
  unit: string
  calories: string
  protein_g: string
  carbs_g: string
  fat_g: string
  notes: string
  shelf_life_days: string
}

function defaultItemForm(): ItemForm {
  return {
    name: '',
    category: '蔬菜',
    quantity_g: 100,
    unit: 'g',
    calories: '',
    protein_g: '',
    carbs_g: '',
    fat_g: '',
    notes: '',
    shelf_life_days: '',
  }
}

export default function Fridge() {
  // 分类筛选同步 URL ?category=（刷新后保持）
  const [searchParams, setSearchParams] = useSearchParams()
  const [items, setItems] = useState<FridgeItemInfo[]>([])
  const [categories, setCategories] = useState<string[]>([])
  const [activeCategory, setActiveCategoryState] = useState<string>(() => searchParams.get('category') || '')
  const [loading, setLoading] = useState(true)

  // 拍照识别
  const [recognizing, setRecognizing] = useState(false)
  const [recognized, setRecognized] = useState<FridgeRecognizedItem[] | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // 新增/编辑弹窗
  const [editing, setEditing] = useState<FridgeItemInfo | null>(null)
  const [showItemModal, setShowItemModal] = useState(false)
  const [itemForm, setItemForm] = useState(() => defaultItemForm())
  const [savingItem, setSavingItem] = useState(false)

  // 菜谱推荐
const [recipes, setRecipes] = useState<FridgeRecipe[] | null>(null)
const [loadingRecipes, setLoadingRecipes] = useState(false)
// 推荐时返回的全量冰箱快照：用料“缺/有”判断以整个冰箱为准，不受左侧 tab 分类筛选影响
const [fridgeSnapshot, setFridgeSnapshot] = useState<FridgeItemInfo[]>([])
  const [confirming, setConfirming] = useState<string | null>(null) // recipe name
  const [preferences, setPreferences] = useState('')
// 当前选中的快捷偏好选项（'默认'=无偏好，不附加任何额外提示词；其余直接作为偏好传给后端）
const [prefChip, setPrefChip] = useState<string>('默认')

  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null)
  // 删除确认弹窗（替代原生 confirm）
  const [deleting, setDeleting] = useState<FridgeItemInfo | null>(null)
  const [deletingInProgress, setDeletingInProgress] = useState(false)
  // 左侧分类导航容器（高亮项自动滚动到可视区域）
  const catNavRef = useRef<HTMLDivElement>(null)
  // 右侧食材列表滚动容器（切换分类时滚回顶部）
  const itemsScrollRef = useRef<HTMLDivElement>(null)
  const pageRef = useRef<HTMLDivElement>(null)
  const pendingScrollRestore = useRef<{
    anchorId?: string
    fallbackAnchorId?: string
    anchorOffset: number
    scrollTop: number
  } | null>(null)

  useEffect(() => {
    fetchItems(true)
  }, [])

  useEffect(() => {
    // 过期筛选为纯前端过滤，请求全量数据即可
    const isExpiryFilter = activeCategory === '__expiring__' || activeCategory === '__expired__'
    fetchItems(false, isExpiryFilter ? undefined : activeCategory || undefined)
  }, [activeCategory])

  // 高亮分类变化时，自动滚动左侧导航使其保持在可视区域内（仅滚动导航自身）
  useEffect(() => {
    const nav = catNavRef.current
    const btn = nav?.querySelector<HTMLElement>('.fridge-cat--active')
    if (!nav || !btn) return
    const navRect = nav.getBoundingClientRect()
    const btnRect = btn.getBoundingClientRect()
    if (btnRect.top < navRect.top) {
      nav.scrollTop += btnRect.top - navRect.top - 4
    } else if (btnRect.bottom > navRect.bottom) {
      nav.scrollTop += btnRect.bottom - navRect.bottom + 4
    }
  }, [activeCategory])

  // DOM 已提交新食材列表后再恢复锚点，避免异步刷新产生视觉跳动。
  useLayoutEffect(() => {
    const restore = pendingScrollRestore.current
    const root = pageRef.current
    if (!restore || !root) return
    // 滚动发生在右侧食材列表区，而非整页
    const scrollContainer = root.querySelector<HTMLElement>('.fridge__items') ?? root

    pendingScrollRestore.current = null
    const nextAnchor = restore.anchorId
      ? scrollContainer.querySelector<HTMLElement>(`[data-fridge-item-id="${restore.anchorId}"]`)
        ?? (restore.fallbackAnchorId
          ? scrollContainer.querySelector<HTMLElement>(`[data-fridge-item-id="${restore.fallbackAnchorId}"]`)
          : null)
      : null
    if (nextAnchor) {
      const nextOffset = nextAnchor.getBoundingClientRect().top - scrollContainer.getBoundingClientRect().top
      scrollContainer.scrollTop += nextOffset - restore.anchorOffset
    } else {
      scrollContainer.scrollTop = Math.min(
        restore.scrollTop,
        Math.max(0, scrollContainer.scrollHeight - scrollContainer.clientHeight),
      )
    }
  }, [items, categories])

  /** 切换分类: 同步 URL（刷新后保持），并回到列表顶部 */
  const setActiveCategory = (c: string) => {
    setActiveCategoryState(c)
    // 切换后回到列表顶部：给出明确的视觉反馈，
    // 也让 fetchItems 的锚点恢复从顶部开始记录，避免停在旧位置
    itemsScrollRef.current?.scrollTo({ top: 0 })
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        if (c) next.set('category', c)
        else next.delete('category')
        return next
      },
      { replace: true },
    )
  }

  /**
   * 刷新食材时保持用户当前阅读位置。
   * 首次加载才显示整页 loading；后续增删改后的静默刷新不会清空列表，
   * 同时用当前可见的食材卡片作为锚点恢复偏移，避免列表重排造成跳动。
   */
const fetchItems = async (initial = false, category?: string) => {
const root = pageRef.current
// 滚动发生在右侧食材列表区，而非整页
const scrollContainer = root?.querySelector<HTMLElement>('.fridge__items') ?? root
    if (!initial && scrollContainer) {
      const containerTop = scrollContainer.getBoundingClientRect().top
      const cards = Array.from(scrollContainer.querySelectorAll<HTMLElement>('[data-fridge-item-id]'))
      const anchorIndex = cards.findIndex((card) => card.getBoundingClientRect().bottom > containerTop)
      const anchor = anchorIndex >= 0 ? cards[anchorIndex] : undefined
      // 删除当前锚点时，优先以它的下一项（末项则上一项）继续保持相对位置。
      const fallback = anchorIndex >= 0 ? cards[anchorIndex + 1] ?? cards[anchorIndex - 1] : undefined
      pendingScrollRestore.current = {
        anchorId: anchor?.dataset.fridgeItemId,
        fallbackAnchorId: fallback?.dataset.fridgeItemId,
        anchorOffset: anchor ? anchor.getBoundingClientRect().top - containerTop : 0,
        scrollTop: scrollContainer.scrollTop,
      }
    }

    if (initial) setLoading(true)
    try {
      const result = await fridgeApi.list(category)
      setItems(result.items)
      setCategories(result.categories)
    } catch (err) {
      pendingScrollRestore.current = null
      console.error('获取冰箱食材失败:', err)
    } finally {
      if (initial) setLoading(false)
    }
  }

  const showToast = (msg: string, ok: boolean) => {
    setToast({ msg, ok })
    setTimeout(() => setToast(null), 2800)
  }

  // ─── 拍照识别 ───
  const handlePhotoSelect = async (file?: File) => {
    if (!file) return
    setRecognizing(true)
    setRecognized(null)
    try {
      const b64 = await fileToBase64(file)
      const result = await fridgeApi.photoRecognize(b64)
      if (result.success) {
        setRecognized(result.recognized)
        showToast(`识别 ${result.recognized.length} 项，已入库 ${result.items.length} 项`, true)
        await fetchItems()
      } else {
        showToast(result.message || '未识别到食材', false)
      }
    } catch (err) {
      showToast('拍照识别失败：服务异常', false)
    } finally {
      setRecognizing(false)
    }
  }

  // ─── 新增/编辑 ───
  const openAdd = () => {
    setEditing(null)
    setItemForm(defaultItemForm())
    setShowItemModal(true)
  }

  const openEdit = (item: FridgeItemInfo) => {
    setEditing(item)
    setItemForm({
      name: item.name,
      category: item.category || '蔬菜',
      quantity_g: item.quantity_g,
      unit: item.unit || 'g',
      calories: item.calories?.toString() || '',
      protein_g: item.protein_g?.toString() || '',
      carbs_g: item.carbs_g?.toString() || '',
      fat_g: item.fat_g?.toString() || '',
      notes: item.notes || '',
      shelf_life_days: item.shelf_life_days?.toString() || '',
    })
    setShowItemModal(true)
  }

  const handleSaveItem = async () => {
    if (!itemForm.name.trim()) {
      showToast('请输入食材名称', false)
      return
    }
    const payload = {
      name: itemForm.name.trim(),
      category: itemForm.category,
      quantity_g: Number(itemForm.quantity_g) || 0,
      unit: itemForm.unit,
      calories: itemForm.calories ? Number(itemForm.calories) : undefined,
      protein_g: itemForm.protein_g ? Number(itemForm.protein_g) : undefined,
      carbs_g: itemForm.carbs_g ? Number(itemForm.carbs_g) : undefined,
      fat_g: itemForm.fat_g ? Number(itemForm.fat_g) : undefined,
      notes: itemForm.notes || undefined,
      shelf_life_days: itemForm.shelf_life_days ? Number(itemForm.shelf_life_days) : null,
    }
    setSavingItem(true)
    try {
      if (editing) {
        await fridgeApi.update(editing.id, payload)
        showToast('已更新食材', true)
      } else {
        await fridgeApi.add(payload)
        showToast('已添加食材', true)
      }
      setShowItemModal(false)
      await fetchItems()
    } catch (err) {
      showToast('保存失败：服务异常', false)
    } finally {
      setSavingItem(false)
    }
  }

/** 点击删除：弹出应用内确认弹窗（替代原生 confirm） */
const handleDelete = (item: FridgeItemInfo) => {
setDeleting(item)
}

/** 确认删除 */
const confirmDelete = async () => {
if (!deleting) return
setDeletingInProgress(true)
try {
await fridgeApi.remove(deleting.id)
showToast('已删除', true)
setDeleting(null)
await fetchItems()
} catch (err) {
showToast('删除失败：服务异常', false)
} finally {
setDeletingInProgress(false)
}
}

// ─── 菜谱推荐 ───
const handleRecommend = async () => {
  // 互斥取值：选中选项时优先用选项（“默认”传空），否则用输入内容
  const pref = prefChip && prefChip !== '默认' ? prefChip : preferences.trim()
  setLoadingRecipes(true)
  setRecipes(null)
  try {
const result = await fridgeApi.recommendRecipes(pref)
setRecipes(result.recipes)
setFridgeSnapshot(result.fridge_snapshot || [])
      if (result.recipes.length === 0) {
        showToast(result.message || (result.raw ? 'AI 返回无法解析，已展示原文' : '暂无可推荐菜谱'), false)
      }
    } catch (err) {
      showToast('菜谱推荐失败：服务异常', false)
    } finally {
      setLoadingRecipes(false)
    }
  }

  const handleConfirmRecipe = async (recipe: FridgeRecipe) => {
    setConfirming(recipe.name)
    try {
      const result = await fridgeApi.confirmRecipe(recipe)
      if (result.success) {
        const warns = [...result.insufficient, ...result.missing]
        showToast(
          warns.length
            ? `已记录到饮食记录并扣减库存（${warns.map((w) => w.name).join('、')} 不足/缺失）`
            : '已记录到饮食记录，库存扣减完成',
          warns.length ? false : true,
        )
        setRecipes(null)
        await fetchItems()
      } else {
        showToast(result.message || '扣减失败', false)
      }
    } catch (err) {
      showToast('扣减失败：服务异常', false)
    } finally {
      setConfirming(null)
    }
  }

  const fridgeNames = useMemo(() => new Set(fridgeSnapshot.map((i) => i.name)), [fridgeSnapshot])

const filteredItems = useMemo(() => {
if (activeCategory === '__expiring__') return items.filter((i) => expireState(i.expires_at) === 'soon')
if (activeCategory === '__expired__') return items.filter((i) => expireState(i.expires_at) === 'over')
if (activeCategory) return items.filter((i) => (i.category || '未分类') === activeCategory)
return items
}, [items, activeCategory])

const grouped = useMemo(() => {
const map = new Map<string, FridgeItemInfo[]>()
for (const it of filteredItems) {
const cat = it.category || '未分类'
if (!map.has(cat)) map.set(cat, [])
map.get(cat)!.push(it)
}
// 分组顺序与左侧分类导航保持一致，导航中不存在的分类排在最后
const order = new Map(categories.map((c, i) => [c, i]))
return Array.from(map.entries()).sort(
(a, b) => (order.get(a[0]) ?? Infinity) - (order.get(b[0]) ?? Infinity),
)
}, [filteredItems, categories])

const totalQuantity = items.reduce((s, i) => s + (i.quantity_g || 0), 0)
const lowItems = items.filter((i) => (i.quantity_g || 0) <= 0).length
const expiringCount = items.filter((i) => expireState(i.expires_at) === 'soon').length
const expiredCount = items.filter((i) => expireState(i.expires_at) === 'over').length

  return (
    <div className="fridge" ref={pageRef}>
      {/* 概览 */}
      <div className="fridge__summary card">
        <div className="fridge-summary__item">
          <Refrigerator size={20} className="fridge-summary__icon" />
          <div>
            <span className="fridge-summary__value">{items.length}</span>
            <span className="fridge-summary__label">食材种类</span>
          </div>
        </div>
        <div className="fridge-summary__item">
          <ChefHat size={20} className="fridge-summary__icon" />
          <div>
            <span className="fridge-summary__value">{categories.length}</span>
            <span className="fridge-summary__label">分类数</span>
          </div>
        </div>
        <div className="fridge-summary__item">
          <Sparkles size={20} className="fridge-summary__icon" />
          <div>
            <span className="fridge-summary__value">{totalQuantity.toFixed(0)}</span>
            <span className="fridge-summary__label">总库存量(g)</span>
          </div>
        </div>
<div className="fridge-summary__item">
<AlertTriangle size={20} className="fridge-summary__icon" />
<div>
<span className="fridge-summary__value fridge-summary__value--warn">{lowItems}</span>
<span className="fridge-summary__label">已用完</span>
</div>
</div>
<div className="fridge-summary__item">
<AlertTriangle size={20} className="fridge-summary__icon" />
<div>
<span className="fridge-summary__value fridge-summary__value--warn">{expiringCount}</span>
<span className="fridge-summary__label">预计过期</span>
</div>
</div>
<div className="fridge-summary__item">
<AlertTriangle size={20} className="fridge-summary__icon" />
<div>
<span className="fridge-summary__value fridge-summary__value--danger">{expiredCount}</span>
<span className="fridge-summary__label">已过期</span>
</div>
</div>
        <div className="fridge-summary__actions">
          <button className="btn btn-primary" onClick={() => fileInputRef.current?.click()} disabled={recognizing}>
            {recognizing ? <Loader2 size={14} className="spin" /> : <Camera size={14} />}
            拍照入库
          </button>
          <button className="btn btn-ghost" onClick={openAdd}>
            <Plus size={14} /> 手动添加
          </button>
        </div>
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          capture="environment"
          className="fridge__file-input"
          onChange={(e) => {
            const f = e.target.files?.[0]
            handlePhotoSelect(f)
            e.target.value = ''
          }}
        />
      </div>

      {/* 识别结果浮层 */}
      {recognizing && (
        <div className="fridge__recognizing card">
          <Loader2 size={18} className="spin" /> 正在用视觉模型识别食材...
        </div>
      )}
      {recognized && recognized.length > 0 && (
        <div className="fridge__recognition card">
          <div className="fridge-recognition__header">
            <span className="fridge-recognition__title">
              <CheckCircle2 size={14} /> 本次识别入库
            </span>
            <button className="fridge-recognition__close" onClick={() => setRecognized(null)}>
              <X size={16} />
            </button>
          </div>
          <div className="fridge-recognition__chips">
            {recognized.map((r, idx) => (
              <span key={idx} className="fridge-chip">
                {r.name} <em>{r.quantity_g?.toFixed(0) || 0}{r.unit || 'g'}</em>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* 分类导航 + 食材列表（铺满剩余高度，分类过多时用下拉框选择） */}
      <div className="fridge__body">
        {categories.length > 8 ? (
          <div className="fridge__cat-bar">
            <select
              className="fridge__cat-select"
              value={activeCategory}
              onChange={(e) => setActiveCategory(e.target.value)}
            >
              <option value="">全部</option>
              {categories.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
              <option value="__expiring__">预计过期</option>
              <option value="__expired__">已过期</option>
            </select>
          </div>
        ) : (
          <div className="fridge__cat-nav" ref={catNavRef}>
            <button
              className={`fridge-cat ${activeCategory === '' ? 'fridge-cat--active' : ''}`}
              onClick={() => setActiveCategory('')}
            >
              全部
            </button>
            {categories.map((c) => (
              <button
                key={c}
                className={`fridge-cat ${activeCategory === c ? 'fridge-cat--active' : ''}`}
                onClick={() => setActiveCategory(c)}
              >
                {c}
              </button>
            ))}
            <button
              className={`fridge-cat fridge-cat--expiring ${activeCategory === '__expiring__' ? 'fridge-cat--active' : ''}`}
              onClick={() => setActiveCategory('__expiring__')}
            >
              预计过期
            </button>
            <button
              className={`fridge-cat fridge-cat--expired ${activeCategory === '__expired__' ? 'fridge-cat--active' : ''}`}
              onClick={() => setActiveCategory('__expired__')}
            >
              已过期
            </button>
          </div>
        )}
        <div className="fridge__items" ref={itemsScrollRef}>
          {loading ? (
            <div className="fridge__loading card">
              <Loader2 size={24} className="spin" /> 正在加载冰箱...
            </div>
) : filteredItems.length === 0 ? (
<div className="fridge__empty card">
  {items.length === 0
    ? '冰箱空空如也，点击「拍照入库」或「手动添加」开始记录食材'
    : '没有符合条件的食材'}
</div>
) : (
grouped.map(([cat, list]) => (
<div key={cat} className="fridge-group" data-group-cat={cat}>
                <h3 className="fridge-group__title">{cat}</h3>
                <div className="fridge-group__list">
                  {list.map((item) => (
                    <FridgeItemCard
                      key={item.id}
                      item={item}
                      onEdit={() => openEdit(item)}
                      onDelete={() => handleDelete(item)}
                    />
                  ))}
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {/* 智能菜谱推荐（底部，内容过多时区块内滚动） */}
      <div className="fridge__recipes card">
        <div className="fridge-recipes__header">
          <span className="fridge-recipes__title">
            <Sparkles size={16} /> 智能菜谱推荐
          </span>
          <div className="fridge-recipes__controls">
            <select
              className="fridge-recipes__pref fridge-recipes__select"
              value={prefChip}
              onChange={(e) => {
                setPrefChip(e.target.value)
                // 选中具体偏好时自动清空菜名输入，二者互斥
                if (e.target.value !== '默认') setPreferences('')
              }}
            >
              {PREF_CHIP_OPTIONS.map((opt) => (
                <option key={opt} value={opt}>{opt}</option>
              ))}
            </select>
            <input
              className="fridge-recipes__pref"
              placeholder="输入菜名"
              value={preferences}
              onChange={(e) => {
                setPreferences(e.target.value)
                // 开始输入菜名时偏好自动切回"默认"，二者互斥
                if (e.target.value.trim() && prefChip !== '默认') setPrefChip('默认')
              }}
            />
            <button className="btn btn-primary" onClick={handleRecommend} disabled={loadingRecipes || items.length === 0}>
              {loadingRecipes ? <Loader2 size={14} className="spin" /> : <RefreshCw size={14} />}
              根据冰箱推荐
            </button>
          </div>
        </div>
        {loadingRecipes && (
          <div className="fridge-recipes__loading">
            <Loader2 size={16} className="spin" /> AI 正在根据现有食材生成菜谱...
          </div>
        )}
        {recipes && recipes.length === 0 && (
          <div className="fridge-recipes__empty">暂无可推荐菜谱，先添加更多食材</div>
        )}
        {recipes && recipes.length > 0 && (
          <div className="fridge-recipes__list">
            {recipes.map((recipe, idx) => (
              <RecipeCard
                key={idx}
                recipe={recipe}
                fridgeNames={fridgeNames}
                confirming={confirming === recipe.name}
                onConfirm={() => handleConfirmRecipe(recipe)}
              />
            ))}
          </div>
        )}
      </div>

{/* 删除确认弹窗 */}
{deleting && (
<div className="modal-overlay" onClick={() => !deletingInProgress && setDeleting(null)}>
<div className="modal modal--small" onClick={(e) => e.stopPropagation()}>
<div className="modal__header">
<h3 className="modal__title">删除食材</h3>
<button className="modal__close" onClick={() => setDeleting(null)}>
<X size={18} />
</button>
</div>
<div className="modal__body">
<div className="fridge-delete-confirm">
<AlertTriangle size={30} className="fridge-delete-confirm__icon" />
<p className="fridge-delete-confirm__text">
确定要删除「<strong>{deleting.name}</strong>」吗？
</p>
<p className="fridge-delete-confirm__subtext">删除后该食材的库存记录将不可恢复。</p>
<div className="fridge-delete-confirm__actions">
<button className="btn btn-ghost" onClick={() => setDeleting(null)} disabled={deletingInProgress}>
取消
</button>
<button
className="btn btn-primary fridge-delete-confirm__btn"
style={{ background: 'var(--color-danger)' }}
onClick={confirmDelete}
disabled={deletingInProgress}
>
{deletingInProgress ? <Loader2 size={14} className="spin" /> : <Trash2 size={14} />}
{deletingInProgress ? '删除中' : '确认删除'}
</button>
</div>
</div>
</div>
</div>
</div>
)}

{/* 新增/编辑弹窗 */}
{showItemModal && (
        <div className="modal-overlay" onClick={() => setShowItemModal(false)}>
          <div className="modal modal--small" onClick={(e) => e.stopPropagation()}>
            <div className="modal__header">
              <h3 className="modal__title">{editing ? '编辑食材' : '添加食材'}</h3>
              <button className="modal__close" onClick={() => setShowItemModal(false)}>
                <X size={18} />
              </button>
            </div>
            <div className="modal__body">
              <div className="fridge-form">
                <label className="fridge-form__row">
                  <span className="fridge-form__label">名称</span>
                  <input
                    className="fridge-form__input"
                    value={itemForm.name}
                    onChange={(e) => setItemForm({ ...itemForm, name: e.target.value })}
                    placeholder="如：鸡蛋"
                  />
                </label>
                <div className="fridge-form__line">
                  <label className="fridge-form__row fridge-form__row--inline">
                    <span className="fridge-form__label">分类</span>
                    <select
                      className="fridge-form__select"
                      value={itemForm.category}
                      onChange={(e) => setItemForm({ ...itemForm, category: e.target.value })}
                    >
                      {CATEGORIES.map((c) => (
                        <option key={c} value={c}>{c}</option>
                      ))}
                    </select>
                  </label>
                  <label className="fridge-form__row fridge-form__row--inline">
                    <span className="fridge-form__label">单位</span>
                    <select
                      className="fridge-form__select"
                      value={itemForm.unit}
                      onChange={(e) => setItemForm({ ...itemForm, unit: e.target.value })}
                    >
                      {UNITS.map((u) => (
                        <option key={u} value={u}>{u}</option>
                      ))}
                    </select>
                  </label>
                </div>
                <label className="fridge-form__row">
                  <span className="fridge-form__label">库存量</span>
                  <input
                    className="fridge-form__input"
                    type="number"
                    value={itemForm.quantity_g}
                    onChange={(e) => setItemForm({ ...itemForm, quantity_g: Number(e.target.value) })}
                  />
                </label>
                <details className="fridge-form__advanced">
                  <summary>营养参考（每100g，可选）</summary>
                  <div className="fridge-form__line">
                    <label className="fridge-form__row fridge-form__row--inline">
                      <span className="fridge-form__label">热量</span>
                      <input
                        className="fridge-form__input"
                        type="number"
                        value={itemForm.calories}
                        onChange={(e) => setItemForm({ ...itemForm, calories: e.target.value })}
                      />
                    </label>
                    <label className="fridge-form__row fridge-form__row--inline">
                      <span className="fridge-form__label">蛋白</span>
                      <input
                        className="fridge-form__input"
                        type="number"
                        value={itemForm.protein_g}
                        onChange={(e) => setItemForm({ ...itemForm, protein_g: e.target.value })}
                      />
                    </label>
                  </div>
                  <div className="fridge-form__line">
                    <label className="fridge-form__row fridge-form__row--inline">
                      <span className="fridge-form__label">碳水</span>
                      <input
                        className="fridge-form__input"
                        type="number"
                        value={itemForm.carbs_g}
                        onChange={(e) => setItemForm({ ...itemForm, carbs_g: e.target.value })}
                      />
                    </label>
                    <label className="fridge-form__row fridge-form__row--inline">
                      <span className="fridge-form__label">脂肪</span>
                      <input
                        className="fridge-form__input"
                        type="number"
                        value={itemForm.fat_g}
                        onChange={(e) => setItemForm({ ...itemForm, fat_g: e.target.value })}
                      />
                    </label>
                  </div>
                </details>
                <label className="fridge-form__row">
                  <span className="fridge-form__label">保质期(天)</span>
                  <input
                    className="fridge-form__input"
                    type="number"
                    step="0.5"
                    min="0"
                    value={itemForm.shelf_life_days}
                    onChange={(e) => setItemForm({ ...itemForm, shelf_life_days: e.target.value })}
                    placeholder="如 3 (留空=不设置)"
                  />
                </label>
                <label className="fridge-form__row">
                  <span className="fridge-form__label">备注</span>
                  <input
                    className="fridge-form__input"
                    value={itemForm.notes}
                    onChange={(e) => setItemForm({ ...itemForm, notes: e.target.value })}
                    placeholder="可选"
                  />
                </label>
                <div className="fridge-form__actions">
                  <button className="btn btn-ghost" onClick={() => setShowItemModal(false)} disabled={savingItem}>
                    取消
                  </button>
                  <button className="btn btn-primary" onClick={handleSaveItem} disabled={savingItem}>
                    {savingItem ? <Loader2 size={14} className="spin" /> : <CheckCircle2 size={14} />}
                    保存
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Toast */}
      {toast && (
        <div className={`fridge-toast ${toast.ok ? 'fridge-toast--ok' : 'fridge-toast--err'}`}>
          {toast.msg}
        </div>
      )}
    </div>
  )
}

// ─── 子组件：食材卡片 ───
function FridgeItemCard({
  item,
  onEdit,
  onDelete,
}: {
  item: FridgeItemInfo
  onEdit: () => void
  onDelete: () => void
}) {
  const empty = (item.quantity_g || 0) <= 0
  return (
    <div
      className={`fridge-card card ${empty ? 'fridge-card--empty' : ''}`}
      data-fridge-item-id={item.id}
    >
{authedImageUrl(item.image_url) ? (
<img src={authedImageUrl(item.image_url)!} alt={item.name} className="fridge-card__img" />
) : (
        <div className="fridge-card__img fridge-card__img--placeholder">
          <ImageOff size={20} />
        </div>
      )}
      <div className="fridge-card__body">
        <span className="fridge-card__name">{item.name}</span>
        <span className="fridge-card__qty">
          {empty ? '已用完' : `${item.quantity_g.toFixed(0)}${item.unit}`}
        </span>
        {item.calories != null && (
          <span className="fridge-card__meta">{item.calories.toFixed(0)} kcal/100g</span>
        )}
        {(item.stored_at || item.expires_at) && (
          <div className={`fridge-card__time fridge-card__time--${expireState(item.expires_at)}`}>
            {item.stored_at && <span>放入 {fmtMin(item.stored_at)}</span>}
            {item.expires_at && (
              <span>
                {expireState(item.expires_at) === 'over' ? '已过期' : '过期'} {fmtMin(item.expires_at)}
              </span>
            )}
          </div>
        )}
      </div>
      <div className="fridge-card__actions">
        <button className="btn btn-ghost fridge-card__btn" onClick={onEdit}>
          <Pencil size={12} /> 编辑
        </button>
        <button className="btn btn-ghost fridge-card__btn" onClick={onDelete}>
          <Trash2 size={12} /> 删除
        </button>
      </div>
    </div>
  )
}

// ─── 子组件：菜谱卡片 ───
function RecipeCard({
  recipe,
  fridgeNames,
  confirming,
  onConfirm,
}: {
  recipe: FridgeRecipe
  fridgeNames: Set<string>
  confirming: boolean
  onConfirm: () => void
}) {
  return (
    <div className="recipe-card">
      <div className="recipe-card__head">
        <span className="recipe-card__name">{recipe.name}</span>
        {recipe.description && <span className="recipe-card__desc">{recipe.description}</span>}
        <div className="recipe-card__nutrition" title="按菜谱用量与食材营养数据估算的整餐营养">
          <span className="recipe-card__cal">
            <Flame size={12} /> {Math.round(recipe.total_calories ?? 0)} kcal
          </span>
          <span><Beef size={12} /> 蛋白 {(recipe.total_protein_g ?? 0).toFixed(1)}g</span>
          <span><Wheat size={12} /> 碳水 {(recipe.total_carbs_g ?? 0).toFixed(1)}g</span>
          <span><Droplet size={12} /> 脂肪 {(recipe.total_fat_g ?? 0).toFixed(1)}g</span>
        </div>
      </div>
      <div className="recipe-card__ingredients">
        {recipe.ingredients.map((ing, idx) => {
          const has = Array.from(fridgeNames).some(
            (n) => n === ing.name || n.includes(ing.name) || ing.name.includes(n),
          )
          return (
            <span key={idx} className={`recipe-ing ${has ? 'recipe-ing--have' : 'recipe-ing--miss'}`}>
              {ing.name} {ing.amount_g.toFixed(0)}{ing.unit}
              <em>{has ? '冰箱有' : '缺'}</em>
            </span>
          )
        })}
      </div>
      {recipe.steps.length > 0 && (
        <ol className="recipe-card__steps">
          {recipe.steps.map((s, idx) => (
            <li key={idx}>{s}</li>
          ))}
        </ol>
      )}
      <div className="recipe-card__actions">
        <button className="btn btn-primary" onClick={onConfirm} disabled={confirming}>
          {confirming ? <Loader2 size={14} className="spin" /> : <CheckCircle2 size={14} />}
          确认烹饪、记录饮食并扣减库存
        </button>
      </div>
    </div>
  )
}
