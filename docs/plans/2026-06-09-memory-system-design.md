# 长期记忆系统设计

> 设计日期: 2026-06-09
> 范围: user_preferences (长期用户画像) + memories (短期语义记忆)
> 项目状态: Phase 1.5 已冻结 Runtime 能力扩展, Memory 作为独立收尾点

## 核心洞察

长期记忆和短期记忆在读写频率、数据结构、检索方式上完全不同，不应共用一张表：

```
user_preferences  → 结构化全量加载 → system prompt (定 LLM 基调)
memories          → 向量语义检索    → 会话上下文/知识查询
```

user_preferences 本质是 **System Prompt Configuration**，不是 Memory。它的查询方式是 `SELECT * WHERE user_id = ?`，全量加载，不做向量检索。

memories 做向量检索 —— top_k=5 语义匹配，为当前任务提供相关上下文。

---

## 数据模型

### 新表: `user_preferences`

```sql
CREATE TABLE user_preferences (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- 核心字段: system prompt 构造用 key + content
    key VARCHAR(128) NOT NULL,          -- 归一化标签, e.g. 'language', 'answer_style'
    content TEXT NOT NULL,              -- 压缩后的精华, e.g. '用中文回复, 简洁优先'

    -- 辅助字段: 展示/管理用, 不参与核心逻辑
    category VARCHAR(20) NOT NULL,      -- 'PREFERENCE' | 'BEHAVIOR' | 'INSTRUCTION'
                                        -- 仅用于前端分组展示, 不参与 system prompt 构造
    source VARCHAR(20) NOT NULL,        -- 'EXPLICIT' | 'IMPLICIT'
                                        -- EXPLICIT: 用户明确说"记住:xxx"
                                        -- IMPLICIT: 系统从行为中推断

    confidence FLOAT DEFAULT 1.0,       -- 置信度 0-1, EXPLICIT=1.0, IMPLICIT<1.0
    mention_count INT DEFAULT 1,        -- 提及/确认次数, 每次确认 +1

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE(user_id, key)               -- 同 key upsert, 保证偏好不重复
);
```

### 新表: `preference_history` (审计)

```sql
CREATE TABLE preference_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    preference_id UUID NOT NULL REFERENCES user_preferences(id) ON DELETE CASCADE,
    old_content TEXT,                   -- NULL 表示新建
    new_content TEXT NOT NULL,          -- 变更后的值
    changed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

为什么需要:
- `UNIQUE(user_id, key)` 使更新自动覆盖旧值, 产品正确
- 但历史丢失不利于审计和回滚
- preference_history 记录变更链: 旧值 → 新值 → 时间

### 现有表: `memories` (保留, 加 metadata 字段)

```sql
ALTER TABLE memories ADD COLUMN metadata JSONB;
```

memories 字段:
| 字段 | 说明 |
|------|------|
| id | UUID PK |
| user_id | FK → users |
| session_id | 关联会话 |
| content | text, 记忆内容 |
| embedding | vector(1024), 语义向量 |
| metadata | JSONB, 来源/类型标签 e.g. `{"source": "task", "task_id": "..."}` |
| created_at | |

向量检索 (Phase 2+ 实现):
```sql
SELECT content, 1 - (embedding <=> query_vector) AS similarity
FROM memories WHERE user_id = ?
ORDER BY embedding <=> query_vector LIMIT 5;
```

---

## 存储内容分类

### user_preferences (长期记忆 — 注入 system prompt)

| category | 说明 | 示例 key | 示例 content |
|----------|------|----------|-------------|
| PREFERENCE | 风格偏好 | language | 回复使用中文 |
| PREFERENCE | 风格偏好 | answer_style | 回答简洁, 不要啰嗦 |
| PREFERENCE | 风格偏好 | code_preference | 优先给可运行代码, 再解释 |
| BEHAVIOR | 行为模式 | work_habit | 先写测试, 再写实现 |
| BEHAVIOR | 行为模式 | review_habit | push 前让 Claude review |
| INSTRUCTION | 显式指令 | career_focus | AI Agent 开发 |
| INSTRUCTION | 显式指令 | tech_stack | Python 3.12 + FastAPI + Postgres 16 |

### memories (短期记忆 — 向量检索)

- 项目知识: 架构信息、技术栈细节、文件位置
- 会话历史摘要: "上次修了一个 race condition bug"
- 执行结果: 成功/失败的策略记录
- 网页内容: 抓取的重要信息
- 用户上传文档: 嵌入后的文本块

---

## API 设计

### `GET /preferences`

全量返回当前用户的偏好，用于 system prompt 构造和前端展示。

Response:
```json
[
  {
    "id": "uuid",
    "key": "language",
    "content": "回复使用中文",
    "category": "PREFERENCE",
    "source": "EXPLICIT",
    "confidence": 1.0,
    "mention_count": 1,
    "created_at": "...",
    "updated_at": "..."
  }
]
```

鉴权: `Depends(get_current_user_id)` — 用户只能查自己的偏好。

### `POST /preferences`

创建偏好 (upsert on user_id + key)。

Request:
```json
{
  "key": "language",
  "content": "回复使用中文",
  "category": "PREFERENCE",
  "source": "EXPLICIT"
}
```

内部逻辑:
1. 按 `(user_id, key)` 查是否存在
2. 存在 → update content + insert preference_history (记录旧值)
3. 不存在 → insert + insert preference_history (old_content=NULL)
4. mention_count +1, confidence 刷新为 source 对应默认值

### `DELETE /preferences/{id}`

删除单条偏好 + 级联删除 preference_history。

### `POST /preferences/remember`

`/remember` 指令入口: 接收一句话, LLM 压缩提取后写入。

Request:
```json
{
  "content": "以后回答尽量简洁，优先给代码，用中文"
}
```

LLM 压缩流程 (详细见下一节):
1. 接收自然语言输入
2. LLM 提取结构化偏好 → 一条或多条 key/content/category
3. 逐条 upsert 到 user_preferences
4. 返回提取结果 (供用户确认/撤销)

Response:
```json
{
  "extracted": [
    {"key": "answer_style", "content": "回答简洁", "category": "PREFERENCE"},
    {"key": "code_preference", "content": "优先给代码", "category": "PREFERENCE"},
    {"key": "language", "content": "回复使用中文", "category": "PREFERENCE"}
  ]
}
```

---

## `/remember` LLM 压缩流程

这是整个系统的核心: 如何从自然语言中提取结构化的、归一化的偏好。

### 压缩 Prompt 设计

```
你是一个用户偏好提取器。从用户输入中提取结构化偏好。

规则:
1. key 必须是归一化的短标签, 使用 snake_case, 不超过 32 字符
2. content 是压缩后的精华, 去掉冗余, 保留核心含义, 不超过 200 字符
3. category 从以下选择: PREFERENCE / BEHAVIOR / INSTRUCTION
4. 如果一句话包含多个偏好, 拆成多条
5. 如果输入没有明确的偏好信息, 返回空数组

预定义 key 参考 (不限于此):
- language: 回复语言
- answer_style: 回答风格 (简洁/详细/幽默/正式)
- code_preference: 代码偏好 (先代码后解释/只解释/只代码)
- explanation_depth: 解释深度 (浅/中/深)
- tech_stack: 技术栈
- work_habit: 工作习惯
- review_habit: review 习惯
- career_focus: 职业方向

示例输入: "以后回答尽量简洁，优先给代码，用中文回复"
示例输出:
[
  {"key": "answer_style", "content": "回答简洁", "category": "PREFERENCE"},
  {"key": "code_preference", "content": "优先给代码", "category": "PREFERENCE"},
  {"key": "language", "content": "回复使用中文", "category": "PREFERENCE"}
]
```

### 关键约束

- **幂等**: 同一句话重复调用, 提取结果应一致; upsert on key 保证不产生重复行
- **容错**: 输入"今天天气不错" → 返回 `[]`, 不强行提取
- **下界**: 提取的 content 长度 >= 2 字符, 太短说明是噪音

### 调用链路

```
POST /preferences/remember
  → PreferencesService.remember(content)
    → LLM.chat(compression_prompt + content)
    → 解析 JSON 数组
    → 逐条 repo.upsert(key, content, ...)
    → 返回 extracted 列表
```

---

## System Prompt 注入

在 PolicyEngine 构造 prompt 时, 全量加载 user_preferences 注入 system message:

```python
# policy_engine.py 或新增 system_prompt builder
prefs = await pref_repo.list_by_user(user_id)
if prefs:
    lines = ["## 用户偏好"]
    for p in prefs:
        lines.append(f"- {p.key}: {p.content}")
    system_prompt += "\n" + "\n".join(lines)
```

不依赖 category 做分组 —— category 只用于前端 UI 展示，不参与 prompt 逻辑。

生成的 system prompt 片段示例:
```
## 用户偏好
- language: 回复使用中文
- answer_style: 回答简洁, 不要啰嗦
- code_preference: 优先给可运行代码
- career_focus: AI Agent 开发
```

---

## 实现步骤

### Step 1: 数据层 (Alembic migration + ORM + Repository)

1. 创建 Alembic migration:
   - 新建 `user_preferences` 表
   - 新建 `preference_history` 表
   - `ALTER TABLE memories ADD COLUMN metadata JSONB`

2. ORM 模型:
   - `app/model/user_preference.py` — `UserPreference(Base, UUIDMixin)`
   - `app/model/preference_history.py` — `PreferenceHistory(Base, UUIDMixin)`
   - 更新 `app/model/__init__.py` 导出新模型
   - 更新 `app/model/user.py` 添加 relationship
   - 更新 `app/model/memory.py` 添加 metadata 字段

3. Repository:
   - `app/repository/user_preference.py` — `UserPreferenceRepository`
     - `list_by_user(user_id)` — 全量查询
     - `upsert(user_id, key, content, category, source)` — 插入或更新, 写入 history
     - `delete(pref_id)` — 级联删除
   - `app/repository/memory.py` — 补全 (Phase 2+ 才实现向量检索, V1 只补 CRUD 骨架)

### Step 2: API 层

新增 `app/api/preferences.py`:
- `GET /preferences` — 全量返回
- `POST /preferences` — 创建/更新
- `DELETE /preferences/{id}` — 删除
- `POST /preferences/remember` — LLM 压缩 + 写入

在 `app/main.py` 注册路由。

### Step 3: LLM 压缩

- `app/service/preference_extractor.py` — 封装压缩 prompt + LLM 调用 + 解析 + 批量 upsert
- 复用现有 `ChatLLM` (PolicyEngine 同一个 LLM)

### Step 4: System Prompt 注入

- 在 `PolicyEngine.decide()` 的 system prompt 构造中, 加载 user_preferences 注入
- 或在 `BrowserTaskRunner.start_task()` 时注入到 goal/context 中

### Step 5: 前端 (可选, 最小化)

- Settings 页面显示偏好列表 (读 GET /preferences)
- 简单的添加/删除 UI

---

## 明确不进范围

- **IMPLICIT 自动推断**: V1 只支持 `source=EXPLICIT` 的手动/remember 路径。IMPLICIT 需要多轮行为分析 + 阈值判断, 复杂度高, 留给未来。
- **memories 向量检索**: 表已建好, embedding 生成和相似度查询留给 Phase 3 或更后。V1 memories 表只加 metadata 列。
- **偏好冲突检测**: 例如同时存在 `language=中文` 和 `language=英文`, V1 不做冲突检测, upsert on key 保证只有最新值生效。
- **preference 影响范围控制**: V1 所有偏好全局生效。不做 "仅任务 xxx 生效" 的 scope 控制。

---

## 验证清单

- [ ] Alembic migration 创建 user_preferences + preference_history, memories 加 metadata
- [ ] ORM 模型通过 test_models.py 扩展测试
- [ ] `GET /preferences` 返回当前用户的偏好列表 (空列表也是合法响应)
- [ ] `POST /preferences` 创建新偏好成功, 重复 key 自动 upsert
- [ ] `DELETE /preferences/{id}` 删除成功, preference_history 级联清空
- [ ] `POST /preferences/remember` 输入中文一句话, 返回正确提取的 key/content
- [ ] `/remember` 输入无偏好信息的内容 → 返回空数组, 不报错
- [ ] `/remember` 幂等: 重复调用不产生重复行
- [ ] PolicyEngine.system_prompt 包含用户偏好片段
- [ ] 现有 80 测试仍全部通过
