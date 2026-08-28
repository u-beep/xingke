# 「我的冰箱」功能实现计划

## Context（背景与目标）

ShapeAI 当前已有完整的饮食/外卖/运动等身材管理链路，但缺少「食材库存」视角。用户要求新增「我的冰箱」：用相机拍照经视觉模型识别食材后入库，基于现有食材生成结构化菜谱推荐，确认使用某菜谱后自动扣减冰箱库存。当前视觉服务 `FoodRecognitionService` 仅为文本/规则匹配、未真正调用多模态模型；模型网关 `complete()` 也不支持图片输入。需新增 MinIO 图片存储、DeepSeek 视觉模型 `deepseek-v4-flash-vision-exp` 接入，以及前后端全链路。

用户已确认两项关键决策：
- 图片存储方式：**MinIO**（复用 docker-compose 已有 minio 服务，新建独立 bucket）
- 菜谱扣减结构：**结构化 JSON 用料**（LLM 返回 `ingredients[{name,amount_g,unit}]`，按用料精确+模糊匹配扣减）

## 数据表设计（PostgreSQL `fridge_items`）

```sql
CREATE TABLE IF NOT EXISTS fridge_items (
    id               BIGSERIAL PRIMARY KEY,
    user_id          VARCHAR(64) NOT NULL,
    name             VARCHAR(128) NOT NULL,        -- 食材名
    category         VARCHAR(64) DEFAULT '',        -- 蔬菜/肉蛋/主食/调味
    quantity_g       FLOAT NOT NULL DEFAULT 0,      -- 库存量(克)
    unit             VARCHAR(16) DEFAULT 'g',       -- g/个/包/ml
    calories         FLOAT, protein_g FLOAT, carbs_g FLOAT, fat_g FLOAT,  -- 每100g营养参考(可选)
    image_object_key VARCHAR(256),                  -- MinIO对象key(非base64/非URL)
    recognized_at    TIMESTAMPTZ,
    notes            TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_fridge_items_user_time ON fridge_items (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_fridge_items_user_name ON fridge_items (user_id, name);
CREATE INDEX IF NOT EXISTS idx_fridge_items_user_cat  ON fridge_items (user_id, category);
```
- 图片只存 MinIO key；同一张照片识别出的多个食材行共享同一 key。
- 前端取图通过 `to_dict()` 派生的 `image_url = "/api/v1/fridge/items/{id}/image"`（相对 URL，走 Vite 代理，无 CORS）。

## 文件改动清单

### 后端
| 文件 | 动作 | 说明 |
|---|---|---|
| `shapeai/config.py` | 改 | 新增 `VISION_MODEL/VISION_BASE_URL/VISION_API_KEY`（默认 `deepseek-v4-flash-vision-exp` / `https://api.deepseek.com` / 复用 DEEPSEEK_API_KEY）与 `MINIO_ENDPOINT/ACCESS_KEY/SECRET_KEY/SECURE/BUCKET`（默认 `localhost:9001` / `minioadmin`×2 / `fridge-images`）。沿用 `os.environ.get` 模式，并补进 `get_config()`。 |
| `shapeai/storage.py` | 新建 | MinIO 客户端封装。仿 `database.py` 惰性初始化 + 锁：`get_minio_client()`、`ensure_bucket()`、`upload_bytes(key,data,content_type)`、`get_object_bytes(key)->(bytes,ctype)`、`health_check()`。key 规则 `fridge/{user_id}/{uuid4hex}.jpg`。 |
| `shapeai/gateway/clients.py` | 改 | `OpenAICompatibleClient` 新增 `complete_with_image(prompt, image_base64, max_new_tokens, mime)`：复用现有 urllib+重试+解析，messages 用 `content:[{type:text},{type:image_url,image_url:{url:"data:{mime};base64,{b64}"}}]`；`ModelClient` 基类加抛 NotImplementedError 的同名方法做特性探测。 |
| `shapeai/gateway/gateway.py` | 改 | 新增 `self.vision = _build_vision()`（无 key 返回 None）、`complete_with_image(prompt,image_base64,user_id,scene,mime)`：配额检查→选 vision 客户端→调用→`_record_usage`→失败回退到 primary（若支持）。`get_stats`/`health_check` 加 vision 字段。 |
| `shapeai/vision/food_recognition.py` | 改 | `recognize()` 新增图片分支：有 `image_base64` 且 gateway 支持 `complete_with_image` 时，构造严格 JSON 提示词（要求返回食材数组 `{name,category,quantity_g,unit,confidence}`，给 `FOOD_DATABASE` key 做名称归一），调用后用新 `_parse_ingredient_response()` 解析；保留 description 分支与低置信度归集；返回结构兼容现有 `/vision/food-recognition` 调用方。 |
| `shapeai/records/fridge_store.py` | 新建 | 仿 `takeout_store.py`：`@dataclass FridgeItem`+`to_dict()`(派生 image_url)、`class FridgeStore`(`_ensure_tables`、`list_items`、`get_item`、`add_item`、`update_item`(动态SET白名单字段)、`delete_item`、`merge_or_add`(按 name+unit 合并或新建)、`deduct_ingredients`、`_row_to_item`)。 |
| `shapeai/api/routes/fridge.py` | 新建 | 仿 `takeout.py`：`router=APIRouter(prefix="/fridge",tags=["我的冰箱"])`，内联 Pydantic 模型，`user_id=req.headers.get("X-User-Id","anonymous")`，`store=FridgeStore()`。8 个端点见下表。 |
| `shapeai/api/routes/__init__.py` | 改 | 导出 `fridge_router` + 加入 `__all__`。 |
| `shapeai/records/__init__.py` | 改 | 导出 `FridgeStore, FridgeItem`。 |
| `shapeai/api/app.py` | 改 | import 加 `fridge_router`；`app.include_router(fridge_router, prefix="/api/v1")`。无需新 AppState 组件（store 即用即建，MinIO 惰性初始化，复用已注入的 `food_recognition`/`gateway`）。 |
| `shapeai/migrate.py` | 改 | `PG_SCHEMA_SQL` 末尾追加 `fridge_items` 建表+索引（与 store 自建保持一致）。 |
| `pyproject.toml` | 改 | dependencies 加 `"minio>=7.2.0"`。 |
| `.env.example` | 改 | 补 `SHAPEAI_VISION_MODEL/BASE_URL/API_KEY` 与 `SHAPEAI_MINIO_*` 注释示例（有默认值，非必需）。 |

### 前端（`xingke/`）
| 文件 | 动作 | 说明 |
|---|---|---|
| `src/services/api.ts` | 改 | 仿 `takeoutApi` 新增 `fridgeApi` + 接口 `FridgeItemInfo`/`FridgeRecipe`/`FridgeDeduction`。方法：`list/add/update/remove/photoRecognize/recommendRecipes/confirmRecipe`，共用 `request<T>`+`buildQuery`。 |
| `src/pages/Fridge/Fridge.tsx` + `Fridge.css` | 新建 | 仿 `Takeout.tsx`（汇总卡+分类tab+卡片grid+modal+toast）与 `DietRecord.tsx`（`<input type=file accept=image/* capture=environment>` + `fileToBase64`）。含：食材列表/缩略图(用 `item.image_url`)、拍照入库→识别结果可编辑→已合并入库、手动新增/编辑/删除、智能菜谱推荐(1-3 候选，标注「冰箱有/缺」)、确认烹饪→扣减并 toast 不充足项。`USER_ID='user_web_001'`。 |
| `src/App.tsx` | 改 | `<Route path="/fridge" element={<Fridge/>} />`。 |
| `src/components/Sidebar/Sidebar.tsx` | 改 | `navItems` 加 `{path:'/fridge',label:'我的冰箱',icon:Refrigerator}`（lucide-react 有此图标），置于外卖与运动之间。 |

## API 接口面（前缀 `/api/v1/fridge`）

| 方法 | 路径 | 请求 | 响应 |
|---|---|---|---|
| GET | `/items` | `?category=` | `{items, count, categories}` |
| POST | `/items` | `FridgeItemRequest` | `{success, item_id, item}` |
| PUT | `/items/{item_id}` | 部分 `FridgeItemRequest` | `{success, item}` |
| DELETE | `/items/{item_id}` | — | `{success, message}` |
| POST | `/photo-recognize` | `{image_base64}` | `{success, recognized[], image_object_key, items[]}` |
| GET | `/items/{item_id}/image` | — | 二进制图片(`Response`, media_type 取 MinIO) |
| POST | `/recipes/recommend` | `{preferences?}` | `{recipes[], fridge_snapshot[], raw?}` |
| POST | `/recipes/confirm` | `{recipe: FridgeRecipe}` | `{success, deducted[], insufficient[], missing[], items[]}` |

## 关键算法

**拍照入库流程**（`/photo-recognize`）：① `food_recognition.recognize(image_base64)` 得食材数组 → ② `base64.b64decode` → `storage.upload_bytes(key, raw, "image/jpeg")` → ③ 对每个识别项 `FridgeStore.merge_or_add(...)`（`SELECT...WHERE name=%s AND unit=%s`，命中则 `quantity_g += 新量`，否则插入；营养从 `FOOD_DATABASE` 命中时填充）。所有行共享同一 `image_object_key`。

**菜谱推荐**（`/recipes/recommend`）：读冰箱列表 → 拼食材清单 → `gateway.complete(prompt, route="complex")`，提示词要求严格输出 `{"recipes":[{"name","description","steps":[],"ingredients":[{"name","amount_g","unit"}]}]}`，优先消耗现有食材 → 鲁棒 JSON 解析（去 ```json 围栏→正则兜底），失败则 `{recipes:[], raw:text}` 前端兜底展示。

**扣减**（`FridgeStore.deduct_ingredients`）：逐项按 name+unit 精确→name 任意 unit→子串模糊匹配；`missing`(无)/`insufficient`(不足,扣尽可用)/`ok`(足额扣减)；`UPDATE quantity_g = GREATEST(0, quantity_g - deducted)`；不自动删除 0 量行（保留图片/历史，前端标「已用完」）。部分不足不阻断，仅 toast 提示。

## 依赖与 Docker

- `pyproject.toml` 加 `minio>=7.2.0`。
- 复用 `docker/docker-compose.yml` 已有 `minio` 服务（host 端口 9001，凭据 `minioadmin/minioadmin`），运行时 `storage.ensure_bucket()` 自动建 bucket `fridge-images`，与 Milvus 内部使用隔离，无需改 compose。

## 验证步骤

后端：
1. `pip install -e .`；`docker compose -f docker/docker-compose.yml up -d`；`python -m shapeai.migrate`（确认 `fridge_items` 建表）。
2. 启动 `python -m shapeai`（端口 8900），访问 `/health`。
3. httpie 端到端：新增→列表→拍照识别(传 base64，验 `recognized[]`+`items[]`+图片可访问 `/items/{id}/image`)→推荐→确认扣减→重新列表验 `quantity_g` 减少；MinIO 控制台 `localhost:9001` 可见 `fridge-images` bucket 下对象。

前端：
1. `cd xingke && npm install && npm run dev`（3000 端口，代理 `/api`→8900）。
2. 侧边栏见「我的冰箱」冰箱图标；进 `/fridge`：空态→拍照入库→识别弹窗→列表带缩略图→推荐菜谱→确认烹饪→库存扣减+不充足 toast。

## 风险点

- DeepSeek 视觉模型名/可用性：需确认 `deepseek-v4-flash-vision-exp` 可经 `https://api.deepseek.com/v1/chat/completions` 多模态调用；若账户内模型名不同，用 `SHAPEAI_VISION_MODEL` 覆盖。
- `image_url` 内容块须用 `data:image/jpeg;base64,...` 形式。
- 后端在宿主机运行，MinIO 走 `localhost:9001`（compose 已映射）。
