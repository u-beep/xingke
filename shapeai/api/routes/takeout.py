"""外卖选购下单 API 路由。

提供：
  GET    /takeout/shops             获取店家列表（可按品类过滤）
  GET    /takeout/shop-categories   获取店家品类列表
  GET    /takeout/shops/{shop_name} 获取店家详情+菜单（按店内分类分组）
  GET    /takeout/dishes            获取外卖菜品菜单（可按店家/分类过滤）
  GET    /takeout/dishes/{dish_id}  获取菜品详情
  GET    /takeout/categories        获取菜品分类
  POST   /takeout/orders            下单（带 include_in_stats 勾选）
  GET    /takeout/orders/today      获取今日订单
  GET    /takeout/orders/history    查询订单历史
  GET    /takeout/orders/summary    获取今日订单汇总
  DELETE /takeout/orders/{order_id} 取消订单

下单时会自动同步写入当日饮食记录（source='order'），由
``include_in_stats`` 字段决定是否计入当日热量/蛋白质统计。
"""

from fastapi import APIRouter, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Optional

from ...records import TakeoutStore
from ...records.takeout_store import SHOP_LOGO_FILES
from ..security import get_auth_user_id

router = APIRouter(prefix="/takeout", tags=["外卖选购"])


# ─── 公开图片接口（免登录: 品牌 logo, 无用户数据） ───

# 允许返回的图片 key 白名单（品牌 logo 文件名, 防 SSRF/任意对象读取）
# 与 takeout_store.SHOP_LOGO_FILES 保持同步
_ALLOWED_LOGO_KEYS = set(SHOP_LOGO_FILES.values())


@router.get("/images/{file_name}", summary="获取品牌 logo 图片")
async def get_brand_image(file_name: str):
    """从 MinIO 流式返回品牌 logo 图片（公开接口, 免登录）。"""
    # 白名单校验: 只允许已知 logo 文件名, 拒绝路径穿越/任意 key
    if file_name not in _ALLOWED_LOGO_KEYS:
        return Response(status_code=404)
    try:
        from ...storage import get_object_bytes
        from ...records.takeout_store import TAKEOUT_BUCKET
        data, ctype = get_object_bytes(f"takeout/logos/{file_name}", bucket=TAKEOUT_BUCKET)
        return Response(content=data, media_type=ctype)
    except Exception:
        return Response(status_code=404)


# ─── 请求模型 ───

class PlaceOrderRequest(BaseModel):
    """下单请求。"""
    dish_id: int = Field(..., description="外卖菜品ID")
    quantity: int = Field(1, description="下单数量", ge=1)
    meal_type: str = Field("lunch", description="餐次: breakfast/lunch/dinner/snack")
    include_in_stats: bool = Field(
        True,
        description="是否将这份外卖计入当日热量与蛋白质统计（用户自主勾选）",
    )
    notes: Optional[str] = Field(None, description="订单备注")


# ─── 店家接口 ───

@router.get("/shops", summary="获取店家列表")
async def list_shops(category: Optional[str] = None):
    """获取所有外卖店家（仿美团店列），可按品类过滤。"""
    store = TakeoutStore()
    shops = store.list_shops(category=category)
    return {
        "shops": [s.to_dict() for s in shops],
        "count": len(shops),
    }


@router.get("/shop-categories", summary="获取店家品类列表")
async def list_shop_categories():
    """获取店家品类标签（炸鸡汉堡/中式快餐/咖啡茶饮/...）。"""
    store = TakeoutStore()
    return {"categories": store.list_shop_categories()}


@router.get("/shops/{shop_name}", summary="获取店家详情与菜单")
async def get_shop_detail(shop_name: str):
    """获取单个店家详情 + 按店内分类分组的菜单。"""
    store = TakeoutStore()
    shop = store.get_shop(shop_name)
    if not shop:
        return {"success": False, "message": "店家不存在"}
    dishes = store.list_dishes(shop_name=shop_name, only_available=True)
    # 按店内分类分组（仿美团点餐页）
    groups: dict = {}
    for d in dishes:
        groups.setdefault(d.category or "其他", []).append(d.to_dict())
    return {
        **shop.to_dict(),
        "menu_groups": [
            {"category": cat, "dishes": items} for cat, items in groups.items()
        ],
    }


# ─── 菜品接口 ───

@router.get("/dishes", summary="获取外卖菜品菜单")
async def list_dishes(
    category: Optional[str] = None,
    shop_name: Optional[str] = None,
):
    """获取所有可用的外卖菜品，可按店家/店内分类过滤。"""
    store = TakeoutStore()
    dishes = store.list_dishes(category=category, only_available=True, shop_name=shop_name)
    return {
        "dishes": [d.to_dict() for d in dishes],
        "count": len(dishes),
    }


@router.get("/categories", summary="获取外卖菜品分类")
async def list_categories():
    """获取所有菜品分类列表。"""
    store = TakeoutStore()
    categories = store.list_categories()
    return {"categories": categories}


@router.get("/dishes/{dish_id}", summary="获取菜品详情")
async def get_dish(dish_id: int):
    """获取单个菜品详情。"""
    store = TakeoutStore()
    dish = store.get_dish(dish_id)
    if not dish:
        return {"success": False, "message": "菜品不存在"}
    return dish.to_dict()


# ─── 订单接口 ───

@router.post("/orders", summary="下单（确认外卖订单）")
async def place_order(request: PlaceOrderRequest, req: Request):
    """用户确认下单外卖。

    - 同步写入 ``takeout_orders`` 订单表
    - 同步写入 ``diet_records`` 当日饮食记录（source='order'）
    - 若 ``include_in_stats=False``，外卖仍写入饮食记录（保留可见），
      但不计入当日热量与蛋白质统计
    """
    user_id = get_auth_user_id(req)
    store = TakeoutStore()
    order_id = store.place_order(
        user_id=user_id,
        dish_id=request.dish_id,
        quantity=request.quantity,
        meal_type=request.meal_type,
        include_in_stats=request.include_in_stats,
        notes=request.notes,
    )

    if order_id is None:
        return {
            "success": False,
            "message": "下单失败：菜品不存在或系统异常",
        }

    # 返回下单后的订单详情 + 今日统计
    summary = store.get_today_summary(user_id)
    return {
        "success": True,
        "order_id": order_id,
        "include_in_stats": request.include_in_stats,
        "message": "下单成功，已同步至当日饮食记录",
        "today_summary": summary,
    }


@router.get("/orders/today", summary="获取今日外卖订单")
async def get_today_orders(req: Request):
    """获取用户今日所有外卖订单。"""
    user_id = get_auth_user_id(req)
    store = TakeoutStore()
    orders = store.get_today_orders(user_id)
    summary = store.get_today_summary(user_id)
    return {
        "orders": [o.to_dict() for o in orders],
        "count": len(orders),
        "summary": summary,
    }


@router.get("/orders/history", summary="查询外卖订单历史")
async def get_history_orders(req: Request, days: int = 30, limit: int = 200):
    """查询用户外卖订单历史。"""
    user_id = get_auth_user_id(req)
    store = TakeoutStore()
    orders = store.get_history_orders(user_id, days=days, limit=limit)
    return {
        "orders": [o.to_dict() for o in orders],
        "count": len(orders),
        "days": days,
    }


@router.get("/orders/summary", summary="今日外卖汇总")
async def get_orders_summary(req: Request):
    """获取用户今日外卖订单汇总（含计入统计 vs 总量）。"""
    user_id = get_auth_user_id(req)
    store = TakeoutStore()
    return store.get_today_summary(user_id)


@router.delete("/orders/{order_id}", summary="取消外卖订单")
async def cancel_order(order_id: int, req: Request):
    """取消外卖订单（同步删除关联饮食记录）。"""
    user_id = get_auth_user_id(req)
    store = TakeoutStore()
    cancelled = store.cancel_order(user_id, order_id)
    summary = store.get_today_summary(user_id) if cancelled else None
    return {
        "success": cancelled,
        "message": "订单已取消，关联饮食记录已删除" if cancelled else "取消失败：订单不存在或已取消",
        "today_summary": summary,
    }
