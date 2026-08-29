import { useState, useEffect, useRef, useMemo } from 'react'
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
} from 'lucide-react'
import {
  fridgeApi,
  fileToBase64,
  type FridgeItemInfo,
  type FridgeRecipe,
  type FridgeRecognizedItem,
} from '../../services/api'
import './Fridge.css'

const CATEGORIES = ['蔬菜', '肉蛋', '主食', '水果', '乳制品', '调味', '其他']

const UNITS = ['g', '个', '包', 'ml']

/** ISO分钟格式 → "MM-DD HH:MM" */
function fmtMin(iso?: string | null): string {
  if (!iso) return ''
  const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/)
  return m ? `${m[2]}-${m[3]} ${m[4]}:${m[5]}` : iso
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
  const [items, setItems] = useState<FridgeItemInfo[]>([])
  const [categories, setCategories] = useState<string[]>([])
  const [activeCategory, setActiveCategory] = useState<string>('')
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
  const [confirming, setConfirming] = useState<string | null>(null) // recipe name
  const [preferences, setPreferences] = useState('')

  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null)

  useEffect(() => {
    fetchItems()
  }, [])

  useEffect(() => {
    if (activeCategory) {
      fridgeApi.list(activeCategory).then((r) => setItems(r.items))
    } else {
      fetchItems()
    }
  }, [activeCategory])

  const fetchItems = async () => {
    setLoading(true)
    try {
      const result = await fridgeApi.list()
      setItems(result.items)
      setCategories(result.categories)
    } catch (err) {
      console.error('获取冰箱食材失败:', err)
    } finally {
      setLoading(false)
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

  const handleDelete = async (item: FridgeItemInfo) => {
    if (!confirm(`确认删除「${item.name}」？`)) return
    try {
      await fridgeApi.remove(item.id)
      showToast('已删除', true)
      await fetchItems()
    } catch (err) {
      showToast('删除失败：服务异常', false)
    }
  }

  // ─── 菜谱推荐 ───
  const handleRecommend = async () => {
    setLoadingRecipes(true)
    setRecipes(null)
    try {
      const result = await fridgeApi.recommendRecipes(preferences)
      setRecipes(result.recipes)
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
            ? `已扣减库存（${warns.map((w) => w.name).join('、')} 不足/缺失）`
            : '库存扣减完成，用料充足',
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

  const fridgeNames = useMemo(() => new Set(items.map((i) => i.name)), [items])

  const grouped = useMemo(() => {
    const map = new Map<string, FridgeItemInfo[]>()
    for (const it of items) {
      const cat = it.category || '未分类'
      if (!map.has(cat)) map.set(cat, [])
      map.get(cat)!.push(it)
    }
    return Array.from(map.entries())
  }, [items])

  const totalQuantity = items.reduce((s, i) => s + (i.quantity_g || 0), 0)
  const lowItems = items.filter((i) => (i.quantity_g || 0) <= 0).length

  return (
    <div className="fridge">
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

      {/* 分类筛选 */}
      <div className="fridge__tabs">
        <button
          className={`fridge-tab ${activeCategory === '' ? 'fridge-tab--active' : ''}`}
          onClick={() => setActiveCategory('')}
        >
          全部
        </button>
        {categories.map((c) => (
          <button
            key={c}
            className={`fridge-tab ${activeCategory === c ? 'fridge-tab--active' : ''}`}
            onClick={() => setActiveCategory(c)}
          >
            {c}
          </button>
        ))}
      </div>

      {/* 食材列表 */}
      <div className="fridge__items">
        {loading ? (
          <div className="fridge__loading card">
            <Loader2 size={24} className="spin" /> 正在加载冰箱...
          </div>
        ) : items.length === 0 ? (
          <div className="fridge__empty card">
            冰箱空空如也，点击「拍照入库」或「手动添加」开始记录食材
          </div>
        ) : (
          grouped.map(([cat, list]) => (
            <div key={cat} className="fridge-group">
              <h3 className="fridge-group__title">{cat}</h3>
              <div className="fridge-group__grid">
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

      {/* 智能菜谱推荐 */}
      <div className="fridge__recipes card">
        <div className="fridge-recipes__header">
          <span className="fridge-recipes__title">
            <Sparkles size={16} /> 智能菜谱推荐
          </span>
          <div className="fridge-recipes__controls">
            <input
              className="fridge-recipes__pref"
              placeholder="偏好（如高蛋白/快手菜）"
              value={preferences}
              onChange={(e) => setPreferences(e.target.value)}
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
    <div className={`fridge-card card ${empty ? 'fridge-card--empty' : ''}`}>
      {item.image_url ? (
        <img src={item.image_url} alt={item.name} className="fridge-card__img" />
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
        <div className="fridge-card__footer">
          <button className="btn btn-ghost fridge-card__btn" onClick={onEdit}>
            <Pencil size={12} /> 编辑
          </button>
          <button className="btn btn-ghost fridge-card__btn" onClick={onDelete}>
            <Trash2 size={12} /> 删除
          </button>
        </div>
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
        {recipe.total_calories != null && recipe.total_calories > 0 && (
          <span className="recipe-card__cal" title="按用料估算的整道菜总热量">
            <Flame size={12} /> 约 {Math.round(recipe.total_calories)} kcal
          </span>
        )}
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
          确认烹饪并扣减库存
        </button>
      </div>
    </div>
  )
}
