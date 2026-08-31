"""活动模块测试数据种子脚本。

使用: python -m shapeai.seed_activities

构造多个锻炼活动:
  - 其中一个活动由 zhangxiyang 作为发起者（owner 管理员）
  - 其余活动由其他虚拟用户发起, zhangxiyang 以普通成员身份加入部分活动
  - 同时为各活动填充成员与群聊消息, 便于前端联调
"""

import logging
from datetime import datetime, timedelta

from .records.activity_store import ActivityStore, ActivityError

logger = logging.getLogger(__name__)

# 虚拟用户（user_id 即 username）
ADMIN_USER = "zhangxiyang"

OTHER_USERS = [
    ("liming", "李明"),
    ("wangfang", "王芳"),
    ("chenhao", "陈浩"),
    ("liuyang", "刘洋"),
    ("zhaojing", "赵静"),
    ("sunlei", "孙磊"),
    ("zhouqi", "周琪"),
    ("wuhan", "吴涵"),
]

# 活动定义: (creator, title, sport_type, city, district, location, days_after, hour, max, desc)
ACTIVITY_DEFS = [
    (ADMIN_USER, "周六朝阳公园篮球局", "篮球", "北京", "朝阳区",
     "朝阳公园篮球场", 3, 14, 10,
     "周末轻松局，3v3 半场为主，欢迎各水平球友参加，记得带水！"),

    ("liming", "奥森夜跑 5 公里", "跑步", "北京", "朝阳区",
     "奥林匹克森林公园南园", 1, 19, 20,
     "每周三晚例行夜跑，配速 600-700，跑完一起拉伸。"),

    ("wangfang", "周末羽毛球双打", "羽毛球", "北京", "海淀区",
     "中关村羽毛球馆 3 号场地", 5, 10, 8,
     "水平相近的双打局，AA 制场地费，拍子自备。"),

    ("chenhao", "环后海骑行", "骑行", "北京", "西城区",
     "后海银锭桥集合", 7, 9, 15,
     "城市休闲骑，环后海-什刹海-鼓楼路线，全程约 15 公里。"),

    ("liuyang", "游泳训练打卡", "游泳", "上海", "浦东新区",
     "源深体育中心游泳馆", 2, 20, 12,
     "自由泳技术练习，800 米起，欢迎能连续游 200 米的朋友。"),

    ("zhaojing", "佘山徒步", "徒步", "上海", "松江区",
     "佘山国家森林公园", 6, 8, 25,
     "轻松徒步路线，东佘山-西佘山，带好水和零食，慢节奏拍照局。"),

    ("sunlei", "周末瑜伽晨练", "瑜伽", "上海", "静安区",
     "静安体育中心瑜伽房", 4, 8, 10,
     "一小时流瑜伽，适合初学者，垫子馆里提供。"),

    ("zhouqi", "五道口乒乓球局", "乒乓球", "北京", "海淀区",
     "五道口乒乓球俱乐部", 2, 18, 6,
     "两小时畅打，轮流单打，水平不限，打完一起吃饭。"),
]

# 群聊消息模板: (sender_index 或 None 表示创建者, content)
def _build_messages(creator: str, title: str) -> list:
    return [
        (creator, f"欢迎大家加入「{title}」！具体时间地点看活动详情，有问题群里说～"),
        (0, "收到，准时到！"),
        (1, "想问下装备有什么要求吗？"),
        (creator, "普通运动装备就行，第一次来的朋友不用紧张～"),
        (2, "+1，一起加油！"),
    ]


def _existing_titles(store: ActivityStore) -> set:
    """已存在的活动标题（脚本可重复执行, 避免重复造数）。"""
    titles = set()
    for r in store.list_activities(limit=500):
        a = r.get("activity")
        if a:
            titles.add(a["title"])
    return titles


def seed():
    store = ActivityStore()
    now = datetime.now()
    existing = _existing_titles(store)
    created = 0

    for idx, (creator, title, sport, city, district, location,
              days_after, hour, max_p, desc) in enumerate(ACTIVITY_DEFS):
        if title in existing:
            print(f"[SKIP] 活动已存在: {title}")
            continue
        start_time = (now + timedelta(days=days_after)).replace(
            hour=hour, minute=0, second=0, microsecond=0)
        try:
            activity = store.create_activity(
                creator_id=creator,
                creator_nickname=creator,
                title=title,
                sport_type=sport,
                city=city,
                district=district,
                location=location,
                start_time=start_time,
                max_participants=max_p,
                description=desc,
            )
        except ActivityError as exc:
            logger.warning("跳过活动 %s: %s", title, exc)
            continue
        if not activity:
            logger.warning("活动创建失败: %s", title)
            continue
        created += 1

        # 普通成员加入（创建者已是 owner, 排除掉）
        members = [(u, n) for u, n in OTHER_USERS if u != creator][: (max_p - 1) // 2]
        for user_id, nickname in members:
            try:
                store.join_activity(activity.id, user_id, nickname=nickname)
            except ActivityError:
                pass  # 已满/已加入等情况忽略

        # 群聊消息
        if activity.group_id:
            for sender, content in _build_messages(creator, title):
                try:
                    store.send_message(activity.group_id, sender, content)
                except ActivityError:
                    pass

        print(f"[OK] 活动 #{activity.id}: {title} (发起者={creator}, 状态={activity.status})")

    # zhangxiyang 再以普通成员身份加入 2 个活动
    joined = 0
    my_acts = {r["activity"]["id"] for r in store.list_activities(only_mine=True, user_id=ADMIN_USER)
               if r.get("activity")}
    for creator, title, *_ in ACTIVITY_DEFS:
        if creator == ADMIN_USER or joined >= 2:
            continue
        for act in store.list_activities(limit=100):
            a = act.get("activity")
            if a and a["creator_id"] == creator and a["status"] == "open" and a["id"] not in my_acts:
                try:
                    store.join_activity(a["id"], ADMIN_USER, nickname="zhangxiyang")
                    joined += 1
                    print(f"[OK] zhangxiyang 以普通成员加入: {title} (活动 #{a['id']})")
                except ActivityError:
                    pass
                break

    print(f"\n完成: 共创建 {created} 个活动, zhangxiyang 管理员 1 个 + 普通成员加入 {joined} 个")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    seed()
