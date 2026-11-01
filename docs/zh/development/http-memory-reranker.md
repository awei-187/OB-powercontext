# HTTP Memory 重排

`HTTPMemoryReranker` 使用调用方提供的 `httpx.AsyncClient` 实现 `MemoryReranker`。
通过 `open_builtin_contexts` 或 `open_builtin_runtime` 的 `memory_reranker` 参数注入。
Memory 服务按选中 rank 返回原始候选，保留正文、Artifact 引用、entry ID、entry version ID 和原始检索分数。

```python
import httpx

from powercontext.builtin.artifacts.memory import HTTPMemoryReranker
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime import BuiltinConfig, open_builtin_contexts


async def open_application(endpoint: str) -> None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        reranker = HTTPMemoryReranker(endpoint, client=client, batch_size=32)
        async with open_builtin_contexts(
            BuiltinConfig(database=SQLiteConfig()), memory_reranker=reranker
        ) as contexts:
            context = await contexts.get("project")
            # 使用 context.artifacts.memory 写入和检索记忆。
```

示例需要安装 `powercontext[builtin]` 和 `httpx`。超时及传输配置由调用方设置；
适配器不会创建或关闭 HTTP 客户端。

认证通过客户端 `headers` 中预置的 `Authorization` 头（例如 Bearer token）提供。
每个评分 POST 显式设置 `auth=None`，禁用客户端的认证流程，包括 Basic、Digest 及自定义 token 刷新。
这样 401 challenge 不会隐式重发同批候选，而是在一次请求后抛出 `httpx.HTTPStatusError`。
不支持 Digest challenge-response 协商。客户端原有 headers 和 `auth` 配置不会被修改，其他调用方仍可使用。

POST JSON 包含 `query` 和 `candidates`，每个候选仅包含 `rank` 和 `text`。
rank 是完整输入中的一基整数序号，分批时不会重新编号。
响应必须恰好包含 `scores` 数组，每条记录恰好包含整数 `rank` 和有限数值 `score`。
不接受布尔值、数字字符串、NaN 或 Infinity。
响应顺序任意，但必须恰好覆盖本批每个 rank 一次。

```json
{"query":"calibration","candidates":[{"rank":1,"text":"Calibration record."}]}
```

```json
{"scores":[{"rank":1,"score":0.75}]}
```

适配器顺序请求各批，每批不超过 `batch_size` 个候选。所有批次验证后统一按分数降序、
同分按原始 rank 升序选取前 `limit` 项。排序时间为 O(n log n)，额外空间为 O(n)。
成功时 `decision.usage.requests` 为实际完成的评分请求数，即 `ceil(n / batch_size)`。
默认 `policy_id` 为 `http-cross-encoder-v1`，也可通过构造参数自定义并在搜索 trace 中观察。

空候选、非法 limit、非正整数 batch_size、非法 JSON、schema 或 rank 覆盖均抛出 `ValueError`。
非 2xx 状态（包括重定向）抛出 `httpx.HTTPStatusError`，网络异常原样传播。
适配器不重试、不返回部分结果，也不回退到原始排序。
为保持请求预算，调用方须使用未配置自动重试的 transport，且 hooks 不得自行发起额外请求。
服务分数只影响选中顺序，不覆盖原候选的检索分数。

以下测试使用本地回环 HTTP 服务和 SQLite，无需模型凭据：

```bash
python -m pytest -q tests/builtin/artifacts/memory/test_http_reranker.py
```
