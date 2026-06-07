# AgenticFlow Frontend

Browser Agent Runtime Platform 的前端 —— AI 编排控制台。

## 技术栈

| 类别 | 选型 |
| --- | --- |
| Framework | Next.js 15 (App Router) |
| Language | TypeScript (strict) |
| Styling | TailwindCSS 3 |
| State | Zustand (UI state) |
| Data | TanStack Query (server state) |
| HTTP | Axios |
| Test | Vitest + Testing Library + Playwright |
| Icons | lucide-react |
| Theme | next-themes |

## 目录分层

对应后端 `api → service → repository → model` 分层:

```
src/
├── app/                          # Next.js 路由(等同后端 api 层)
│   ├── (workspace)/              # 共享 Sidebar+TopBar 的路由分组
│   │   ├── dashboard/            # /dashboard —— 第一阶段
│   │   ├── agent/                # /agent —— 第二阶段
│   │   ├── tasks/                # /tasks, /tasks/[id] —— 第三/四阶段
│   │   └── settings/             # /settings —— 第五阶段
│   ├── layout.tsx                # Root layout + Providers
│   ├── providers.tsx             # QueryClient + Theme
│   └── page.tsx                  # 根路由 → /dashboard
├── components/
│   ├── shared/                   # 跨页面共享:Sidebar/TopBar/StatusBadge/Card
│   ├── dashboard/                # Dashboard 专属
│   └── (后续) agent/, tasks/
├── lib/
│   ├── api/                      # HTTP 客户端(对应后端 api 路由)
│   ├── query/                    # TanStack Query hooks + keys 工厂
│   ├── store/                    # Zustand(只放 UI 状态,不放数据)
│   ├── format/                   # 格式化工具:time / currency / number
│   ├── ws/                       # WebSocket 客户端(后续)
│   └── cn.ts                     # 唯一允许的"通用工具":className 合并
├── types/                        # TS 类型(镜像后端 Pydantic schema)
└── styles/
    └── globals.css               # DESIGN.md 配色 + 字体 CSS 变量
```

## 关键约束

- 注释:中文,写"为什么不"写"做了什么"
- 单文件 ≤ 50 行(超了拆)
- 不写万能 `lib/utils.ts`(`cn.ts` 是唯一例外)
- 不硬编码任何 URL / Token(走 `NEXT_PUBLIC_*` 环境变量)
- 数据状态走 TanStack Query;UI 状态走 Zustand(不放数据进 store)

## 本地开发

```bash
# 安装依赖
pnpm install

# 启动 dev server(默认 :3000)
pnpm dev

# 类型检查
pnpm typecheck

# 单测
pnpm test

# Lint
pnpm lint
```

需要后端在 `localhost:8000` 同时运行,前端通过 `NEXT_PUBLIC_API_BASE_URL` 接入。

## 环境变量

参考 `.env.example`。生产环境部署时:

- `NEXT_PUBLIC_API_BASE_URL` —— 后端 FastAPI 地址
- `NEXT_PUBLIC_WS_BASE_URL` —— WebSocket 地址(Agent 实时事件)
- `NEXT_PUBLIC_SITE_URL` —— 站点 URL(SEO/OG 标签用)

## 路线图

- [x] Phase 0:项目骨架 + Dashboard 骨架
- [ ] Phase 1:Agent Workspace(三栏 + 实时)
- [ ] Phase 2:Task Center(TanStack Table)
- [ ] Phase 3:Task Detail(Timeline + Recharts)
- [ ] Phase 4:Settings(模型/浏览器/运行时)
- [ ] Phase 5:WebSocket 实时事件
