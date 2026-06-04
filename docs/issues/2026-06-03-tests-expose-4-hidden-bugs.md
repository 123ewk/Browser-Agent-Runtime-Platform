# 2026-06-03:写 logging 单测揪出 4 个隐藏 bug

> **TL;DR**:在写 `app/core/logging.py` 的 11 个单测时,测试一 import 就崩。沿着堆栈追下去,
> 揪出 `app/core/config.py` 3 个 bug + `app/core/logging.py` 1 个 bug。
> 这些 bug 在"直接 import 业务代码"之前都不会暴露,所以一直藏着。

---

## 1. 事故标题

**写测试不写测试 = 让代码在生产第一次被 import 时崩**。

## 2. 事故概述

写 `tests/core/test_logging.py` 时,执行 `pytest` 在 collection 阶段就报 `ImportError`。
随后 4 次连续 `pytest` 失败,每次暴露一个新的隐藏问题:

| 序号 | 隐藏 bug | 文件 | 报错信息 |
|---|---|---|---|
| 1 | `BaseSettings` / `Literal` import 路径错 | `app/core/config.py` | `PydanticImportError: BaseSettings has been moved to pydantic-settings` |
| 2 | `Literal` 在 pydantic 2.13 也不再导出 | `app/core/config.py` | `ImportError: cannot import name 'Literal' from 'pydantic'` |
| 3 | `Settings` 类没有实例化,`settings` 单例缺失 | `app/core/config.py` | `ImportError: cannot import name 'settings' from 'app.core.config'` |
| 4 | processor 链没注入 `module` 字段(排错定位缺失) | `app/core/logging.py` | 单测断言 `record["module"]` KeyError |

## 3. 时间线

| 时间 | 事件 |
|---|---|
| 14:30 | 写完 `test_logging.py` 11 个 case,跑 `pytest`,collection 阶段 ImportError |
| 14:32 | 修 #1:`BaseSettings` 改去 `pydantic_settings`,`Literal` 改回 `typing` |
| 14:35 | 跑 `pytest` → 又一个 ImportError:`Literal` 也不在 pydantic |
| 14:36 | 修 #2:`Literal` 改去 `typing` |
| 14:37 | 跑 `pytest` → ImportError:`cannot import name 'settings'` |
| 14:38 | 修 #3:`config.py` 末尾加 `settings = Settings()` |
| 14:40 | 跑 `pytest` → ValidationError:`LLM_PROVIDER=xiaomi` 不在 Literal 白名单 |
| 14:42 | 修环境:conftest 强制 `os.environ["LLM_PROVIDER"] = "mock"` |
| 14:44 | 跑 `pytest` → 11 个测试里 8 个失败:`capsys` 抓不到 stdout |
| 14:50 | 改方案:放弃 `monkeypatch.setattr(sys, "stdout", ...)`,换 pytest 内置 `capsys` |
| 14:55 | 跑 `pytest` → 10/11 通过,1 个失败:`KeyError: 'logger'`(processor 链没注入名字) |
| 15:00 | 尝试 `structlog.processors.add_logger_name` → `AttributeError`(25+ 移除了) |
| 15:05 | 查 structlog 源码:`CallsiteParameterAdder(MODULE)` 是正解 |
| 15:10 | 修 #4:processor 链加 `CallsiteParameterAdder([CallsiteParameter.MODULE])` |
| 15:12 | 测试改断言:`record["module"] == "test_logging"`(调用方文件 basename) |
| 15:15 | 跑 `pytest` → **11 passed in 0.16s** |

## 4. 根本原因(分类)

| Bug # | 根因分类 | 详细 |
|---|---|---|
| 1, 2 | **依赖升级没同步** | pydantic 2.13 把 `BaseSettings` 移走了,但 import 语句没改。pip 升级时不会自动改你的代码。 |
| 3 | **设计未落地** | 我之前在 `logging.py` 里写 `from app.core.config import settings`,但 `config.py` 根本没暴露 `settings` 单例。**写 import 不等于真有这个对象**。 |
| 4 | **可观测性盲区** | 写 `configure_logging()` 时只想着"能打印",没想"排错时怎么定位模块"。TDD 揪出来才补。 |
| capsys 问题 | **测试基础设施认知不足** | 我以为 `monkeypatch.setattr(sys, "stdout", buf)` 能让我的 StringIO 收到所有输出,实际上 pytest 已经接管了 `sys.stdout`,二次 monkeypatch 会被 pytest 的 capture 屏蔽。 |

## 5. 触发条件(为什么这些 bug 一直藏着)

- **没有 import 业务代码的入口**:`main.py` 还是 `print("Hello from backend!")`,根本没 `from app.core...` 任何东西。
- **没有 CI**:没有任何自动化机制在每次提交时跑 `import app.core`。
- **没有运行服务**:uvicorn 都没启动过,自然不会触发 `Settings()` 实例化。
- **写 logging.py 时直接复制 structlog 示例**:示例代码里没有 `CallsiteParameter`,我也跟着没写 —— **示例 ≠ 完整**。

## 6. 影响范围(prod 会怎样)

| Bug # | prod 影响 |
|---|---|
| 1, 2 | **P0**:`uvicorn main:app` 启动即崩,服务起不来 |
| 3 | **P0**:同上,任何 `from app.core.config import settings` 的代码都崩 |
| 4 | **P1**:服务能起,但线上出问题时无法定位"是哪个模块打的这条日志" |
| capsys | **无 prod 影响**,只影响测试 |

## 7. 检测手段(怎么抓到的)

**TDD 的真正威力在这里**:写测试不是为了"验证代码对",而是为了**强制让代码被 import、被实例化、被调用**。4 个 bug 全部在 `pytest collection` 阶段(甚至 import 阶段)就被抓到,而不是在生产第一次跑时。

```
pytest collection
  → import test_logging
    → import app.core.logging
      → import app.core.config
        → from pydantic import BaseSettings  ❌ Bug #1, #2
        → settings = Settings()  ❌ Bug #3
      → log.info(...)  ❌ Bug #4
```

## 8. 修复方案(实际怎么改的)

### Bug #1, #2:依赖升级
```python
# 改前
from pydantic import BaseSettings, SecretStr, Literal
from pydantic_settings import SettingsConfigDict

# 改后
from typing import Literal
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
```

### Bug #3:补单例
```python
# app/core/config.py 末尾追加
settings = Settings()  # 模块级单例,首次 import 时实例化
```

### Bug #4:processor 链补 module 字段
```python
structlog.processors.CallsiteParameterAdder(
    [structlog.processors.CallsiteParameter.MODULE],
),
```

### 测试基础设施:capsys 替代 monkeypatch
```python
def test_xxx(fake_settings, capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging()
    structlog.get_logger("t").info("evt")
    record = _parse_json_from(capsys.readouterr().out)  # 不用自己抓 sys.stdout
```

### conftest 注入测试用 secrets
```python
# tests/conftest.py 顶层(早于任何 import)
import os
os.environ.setdefault("POSTGRES_PASSWORD", "test-pg-password")
os.environ.setdefault("S3_ACCESS_KEY", "test-s3-key")
os.environ.setdefault("S3_SECRET_KEY", "test-s3-secret")
os.environ.setdefault("LLM_API_KEY", "test-llm-key")
os.environ["LLM_PROVIDER"] = "mock"  # 强制覆盖用户 shell 脏值
```

## 9. 预防措施(怎么防止下次)

| 措施 | 落地动作 |
|---|---|
| **每次 PR 跑 `pytest --collect-only`** | 加进 pre-commit / CI,确保 `import app.core` 不挂 |
| **`pytest` 必跑** | `uv run pytest` 加进 pre-commit hook |
| **依赖升级走 lock 文件** | `uv.lock` 已经锁定版本,但**升级时要写迁移测试** —— 这次 pydantic 2.12→2.13 没做 |
| **复杂 import 写 smoke test** | `tests/test_smoke_imports.py` 只做 `import app.main` 之类,确保 import 链不断 |
| **示例 ≠ 生产** | 写 `logging.py` 时明确"我比 structlog 官方示例多做了什么",不能 copy-paste |

## 10. 经验教训(给未来自己/学生的话)

1. **"代码能写出来"不等于"代码能跑起来"**。这次 4 个 bug,3 个是在 import 阶段就崩,不是运行时。**写完代码第一件事是 import 它**,不是继续写下一段。

2. **TDD 的反直觉之处:测试失败的次数越多,代码质量越好**。我跑了 5 次 `pytest`,前 4 次都失败,每次失败都暴露一个真实问题。**没让它失败过的测试,等于没写**。

3. **依赖升级是头等大事**。`uv lock --upgrade` 改的不只是版本号,可能是 import 路径、API 签名、行为变更。每次升级要跑全套测试 + 看 changelog。

4. **测试基础设施也是代码**。`monkeypatch.setattr(sys, "stdout", buf)` 看起来简单,但和 pytest 的 capture 打架。这种坑不踩一次不会知道,**踩了就要写进 conftest / docs**。

5. **单一职责的真正含义**。`config.py` 的 `Settings` 只该管"读环境变量",不该管"创建全局单例"。但 FastAPI 社区的惯例就是模块级单例,因为简单。我们跟着惯例走,但**要在 conftest 里承认这个耦合**,提前注入测试用值。

---

## Action Items

- [ ] `tests/test_smoke_imports.py`:只做 `import app.main` 之类的 smoke test,放 CI 第一阶段
- [ ] pre-commit hook:`uv run pytest tests/core/test_logging.py` 必跑
- [ ] 升级 pydantic 时:写 migration test 验证 `from app.core.config import settings` 仍 OK
- [ ] 在 `docs/architecture.md` 加一节"模块级单例 + 测试隔离",说清 `settings = Settings()` 的代价
