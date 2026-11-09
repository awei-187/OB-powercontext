# 依赖版本

## 已完成真实验收的版本

| 组件 | 版本 | 用途 |
|---|---:|---|
| Dify | 1.19.0 | 执行 `scenes` 与 `report` Workflow |
| Dify DSL | 0.7.0 | 从最终发布 Workflow 官方无密钥导出 |
| PowerContext | 1.5.0 | Scope、选择写入、Atomic Memory 与召回 |
| CPython | 3.11.18 | PowerContext 项目内独立运行环境 |
| Node.js | 24.22.1 | 实际验收环境 |
| Node.js 最低要求 | 22.18.0 | `package.json` 的 engines 下限 |
| OpenAI provider plugin | 1.1.0 | Dify LLM 节点依赖 |
| 模型绑定 | `langgenius/openai/openai` / `gpt-4o-mini` | 导出时绑定；迁移后可重新绑定兼容模型 |

Node 应用没有第三方 npm 运行依赖，`package-lock.json` 中只有根包。PowerContext 安装脚本使用 `uv` 安装固定的 `powercontext[cli,server]==1.5.0`，并在项目内创建独立虚拟环境。

迁移后需要接收方自行准备：

- Windows 10/11 与 PowerShell 7；
- Node.js 22.18.0 或更高版本；
- `uv` 及访问 Python 包源的网络；
- 可导入 DSL 的 Dify 1.19.0 环境；
- Dify 中可用的模型凭据和该应用专用 API Key。

模型凭据、Dify API Key 和 PowerContext 运行数据库不属于源码依赖，不进入交付包。
