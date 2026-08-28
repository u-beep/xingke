"""知识库管理 — 内置专业知识 + 文档管理接口。

内置知识库内容：中国居民膳食指南、运动解剖学基础、循证减脂指南、
常见运动损伤康复、体态矫正专业知识。
"""

import json
import logging
from pathlib import Path
from typing import Optional

from .vector_store import VectorStore
from .indexer import DocumentIndexer
from .retriever import KnowledgeRetriever
from ..config import KNOWLEDGE_DIR

logger = logging.getLogger(__name__)

# ─── 内置知识库 ───
BUILTIN_KNOWLEDGE = [
    {
        "title": "中国居民膳食指南 - 基本原则",
        "content": """中国居民膳食指南基本原则：
1. 食物多样，谷类为主：每天摄入12种以上食物，每周25种以上。
2. 吃动平衡，健康体重：每周至少5天中等强度身体活动，累计150分钟以上。
3. 多吃蔬果、奶类、大豆：餐餐有蔬菜，每天至少300-500g，深色蔬菜占一半。
4. 适量吃鱼、禽、蛋、瘦肉：每周吃鱼280-525g，畜禽肉280-525g，蛋类280-350g。
5. 少盐少油，控糖限酒：每天食盐不超过5g，烹调油25-30g，糖不超过50g。
6. 杜绝浪费，兴新食尚：按需备餐，分餐取食。
成人每日能量需要量：轻体力活动男性2250kcal，女性1800kcal。""",
        "source": "中国居民膳食指南(2022)",
        "category": "nutrition",
    },
    {
        "title": "基础代谢率(BMR)与热量计算",
        "content": """基础代谢率(BMR)是人体在安静状态下维持生命所需的最低能量。
Mifflin-St Jeor公式是目前最推荐的BMR计算公式：
男性: BMR = 10×体重 + 6.25×身高 - 5×年龄 + 5
女性: BMR = 10×体重 + 6.25×身高 - 5×年龄 - 161

TDEE(每日总能量消耗) = BMR × 活动系数：
- 久坐不动(办公室工作): 1.2
- 轻度活动(每周1-3次运动): 1.375
- 中度活动(每周3-5次运动): 1.55
- 高度活动(每周6-7次运动): 1.725
- 极高活动(体力劳动者/运动员): 1.9

健康减脂建议：每日热量缺口300-500kcal，每周减重0.5-1kg。
低于BMR的饮食会降低代谢率，不利于长期减脂。""",
        "source": "循证减脂指南",
        "category": "nutrition",
    },
    {
        "title": "宏量营养素配比原则",
        "content": """宏量营养素配比原则：
减脂期推荐配比：蛋白质30%，碳水化合物40%，脂肪30%。
增肌期推荐配比：蛋白质25%，碳水化合物50%，脂肪25%。

蛋白质：每公斤体重1.6-2.2g，4kcal/g。优质来源：鸡胸肉、鸡蛋、鱼肉、牛肉、豆腐。
碳水化合物：每公斤体重3-5g，4kcal/g。优先选择粗粮：燕麦、糙米、红薯。
脂肪：每公斤体重0.8-1g，9kcal/g。优质来源：坚果、牛油果、橄榄油、鱼油。

注意事项：
- 减脂期蛋白质摄入要充足，防止肌肉流失
- 碳水不宜完全断掉，大脑需要葡萄糖供能
- 脂肪摄入不宜过低，影响激素合成
- 1g酒精 = 7kcal，减脂期应限制饮酒""",
        "source": "运动营养学",
        "category": "nutrition",
    },
    {
        "title": "运动训练基本原则",
        "content": """运动训练基本原则：
1. 渐进超负荷：逐步增加训练量或强度，让身体持续适应。
2. 专项性：训练应与目标匹配（减脂以有氧+力量组合，增肌以力量为主）。
3. 恢复：肌肉在休息时生长，保证充分睡眠和休息日。
4. 周期化：安排训练周期，避免长期相同训练量导致适应。

力量训练基础：
- 初学者：每周2-3次，每次6-8个动作，每个动作3组×12-15次
- 中级者：每周3-4次，每个动作4组×8-12次
- 高级者：每周4-6次，可采用分化训练

有氧运动建议：
- 减脂：每周3-5次，每次30-60分钟，心率维持在最大心率的60-70%
- 最大心率估算：220 - 年龄
- HIIT(高强度间歇训练)效率高，但每周不超过2-3次""",
        "source": "运动解剖学基础",
        "category": "exercise",
    },
    {
        "title": "常见运动损伤预防与处理",
        "content": """常见运动损伤预防与处理：
1. 肌肉拉伤：运动前充分热身5-10分钟，逐步增加强度。发生拉伤后遵循RICE原则：休息、冰敷、加压、抬高。
2. 关节扭伤：加强关节周围肌肉力量训练，穿合适运动鞋。急性期冰敷48小时，之后热敷促进恢复。
3. 腰部损伤：核心力量训练是预防腰伤的关键。深蹲、硬拉时保持脊柱中立位。
4. 膝盖损伤：避免膝盖内扣，加强股四头肌和腘绳肌力量。下楼梯比上楼梯更伤膝盖。
5. 肩袖损伤：推举动作不要完全锁定，加强肩袖肌群训练。

出现以下情况应立即就医：
- 关节畸形或听到"咔嚓"声
- 持续剧烈疼痛或肿胀
- 关节不稳定感
- 麻木或刺痛感""",
        "source": "运动损伤康复指南",
        "category": "rehabilitation",
    },
    {
        "title": "体态矫正基础知识",
        "content": """常见体态问题及矫正方法：
1. 圆肩驼背：胸椎灵活性不足，胸部肌肉紧张。
   矫正：胸大肌拉伸、胸椎伸展练习、强化菱形肌和下斜方肌。
2. 头前伸：长期看手机/电脑导致。
   矫正：颈部深层屈肌训练、枕骨下肌肉放松、收下巴练习。
3. 骨盆前倾：核心弱、髂腰肌紧张。
   矫正：髂腰肌拉伸、核心稳定性训练、臀大肌强化。
4. 骨盆后倾：久坐、腘绳肌紧张。
   矫正：腘绳肌拉伸、髋屈肌强化、核心训练。
5. 假胯宽：股骨内旋、臀中肌弱。
   矫正：臀中肌强化(蚌式开合)、拉伸大腿内侧、纠正膝外翻。

体态矫正需要长期坚持，建议配合专业评估。
严重体态问题应咨询康复科医生或物理治疗师。""",
        "source": "体态矫正专业知识",
        "category": "posture",
    },
    {
        "title": "减脂平台期应对策略",
        "content": """减脂平台期是身体适应当前热量摄入和运动量后的正常现象。
平台期应对策略：
1. 重新计算TDEE：体重下降后TDEE也会下降，需要重新评估热量目标。
2. 热量循环：高碳水日和低碳水日交替，避免代谢适应。
3. 增加非运动性热量消耗(NEAT)：多走路、站立办公、做家务。
4. 调整训练计划：增加训练强度或改变训练方式，给身体新的刺激。
5. 检查隐形热量：调味酱、饮料、零食等容易被忽略的热量来源。
6. 保证充足睡眠：睡眠不足会增加饥饿激素，降低代谢。

注意事项：
- 平台期持续2-4周是正常的，不必焦虑
- 不要通过大幅减少饮食来突破平台期
- 如果平台期超过6周，建议检查是否有其他健康问题""",
        "source": "循证减脂指南",
        "category": "weight_management",
    },
    {
        "title": "特殊人群运动注意事项",
        "content": """特殊人群运动注意事项：
1. 孕妇：避免仰卧位运动和接触性运动，中低强度有氧和孕妇瑜伽为主。运动前咨询医生。
2. 老年人：以低冲击有氧(快走、游泳)和轻量力量训练为主，注意平衡训练预防跌倒。
3. 青少年：避免大重量力量训练，以自重训练和技能训练为主，保证充足营养。
4. 高血压患者：避免等长收缩和头部低于心脏的动作，以中等强度有氧为主。
5. 糖尿病患者：运动前监测血糖，随身携带糖果，避免空腹运动。
6. 关节炎患者：选择低冲击运动(游泳、骑车)，避免高冲击跑跳。

所有特殊人群在开始运动计划前都应咨询医生。
AI助手不提供医疗建议，只提供一般性健康指导。""",
        "source": "特殊人群运动指南",
        "category": "safety",
    },
]


class KnowledgeBase:
    """知识库管理器。

    提供知识库的增删改查和检索接口。
    """

    def __init__(self, data_dir: str | Path | None = None):
        """初始化知识库。

        Args:
            data_dir: 知识库数据目录
        """
        self.data_dir = Path(data_dir) if data_dir else KNOWLEDGE_DIR
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.store = VectorStore()
        self.indexer = DocumentIndexer(self.store)
        self.retriever = KnowledgeRetriever(self.store)

        self._loaded = False

    def initialize(self, load_builtin: bool = True):
        """初始化知识库，加载内置知识。

        Args:
            load_builtin: 是否加载内置知识
        """
        if self._loaded:
            return

        if load_builtin:
            self._load_builtin_knowledge()

        self._load_user_documents()
        self._loaded = True
        logger.info("知识库初始化完成，共%d个文档块", self.store.document_count)

    def _load_builtin_knowledge(self):
        """加载内置知识库(按标题去重,避免每次启动重复插入导致 Milvus 数据膨胀)。"""
        existing = self.store.get_existing_titles(
            [doc["title"] for doc in BUILTIN_KNOWLEDGE]
        )
        count = 0
        for doc in BUILTIN_KNOWLEDGE:
            if doc["title"] in existing:
                continue
            count += self.indexer.index_document(
                title=doc["title"],
                content=doc["content"],
                source=doc["source"],
                category=doc["category"],
            )
        if count:
            logger.info("加载内置知识库：%d个文档块(跳过已存在 %d 个)",
                        count, len(existing))
        else:
            logger.info("内置知识库已存在(%d个文档块)，跳过重复插入", len(existing))

    def _load_user_documents(self):
        """从数据目录加载用户自定义文档。"""
        for path in self.data_dir.glob("*.json"):
            try:
                docs = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(docs, list):
                    self.indexer.index_batch(docs)
                elif isinstance(docs, dict):
                    self.indexer.index_document(
                        title=docs.get("title", path.stem),
                        content=docs.get("content", ""),
                        source=docs.get("source", path.name),
                        category=docs.get("category", "user"),
                    )
            except Exception as exc:
                logger.warning("加载文档失败 %s: %s", path, exc)

    def add_document(self, title: str, content: str, source: str = "", category: str = "user") -> int:
        """添加单篇文档。"""
        count = self.indexer.index_document(title, content, source, category)
        # 持久化到文件
        if count > 0:
            doc_data = {"title": title, "content": content, "source": source, "category": category}
            file_path = self.data_dir / f"{title[:20]}_{hash(title) % 10000}.json"
            file_path.write_text(json.dumps(doc_data, ensure_ascii=False, indent=2), encoding="utf-8")
        return count

    def add_documents_batch(self, documents: list[dict]) -> int:
        """批量添加文档。"""
        return self.indexer.index_batch(documents)

    def search(self, query: str, top_k: int = 5, category: str | None = None) -> list[dict]:
        """检索知识库。"""
        if not self._loaded:
            self.initialize()
        return self.retriever.retrieve(query, top_k=top_k, category=category)

    def retrieve(self, query: str, top_k: int = 5, category: str | None = None) -> list[dict]:
        """检索知识库（兼容 Agent 调用接口）。"""
        return self.search(query, top_k=top_k, category=category)

    def get_context(self, query: str, top_k: int = 3) -> str:
        """获取可注入 prompt 的知识上下文。"""
        if not self._loaded:
            self.initialize()
        return self.retriever.retrieve_with_context(query, top_k=top_k)

    def list_categories(self) -> list[str]:
        """列出所有知识分类。"""
        stats = self.store.get_stats()
        return list(stats.get("by_category", {}).keys())

    def get_stats(self) -> dict:
        """获取知识库统计信息。"""
        return self.store.get_stats()

    def clear(self):
        """清空知识库。"""
        self.indexer.clear()
        self._loaded = False
