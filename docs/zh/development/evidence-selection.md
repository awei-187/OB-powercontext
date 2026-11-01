# 按查询选择原文证据

`PrepareContextRequest(evidence_selection=True)` 在 `PreparedContextBuilder` 中开启
离线 Memory 片段选择。参数是严格布尔值，默认 `False`；省略或关闭时，普通 prepare
保持原有输出。此模式只使用传入的 Memory 候选，不读取额外文档或标注，不调用模型或服务。

`PreparedContextBuild.fragments` 返回 `EvidenceFragment` 元组。每项包含精确的
`MemoryEntryAddress`、半开 Python 字符坐标 `start`/`end` 和原文 `text`。
`text` 等于原 entry 的 `text[start:end]`。`origins` 按相同顺序返回地址；JSON 项包含
完整 scope、Memory revision、entry ID 和 version ID。可构造 `MemoryCitation`，通过
相应 scope 的 `memory.get(GetMemoryEntryRequest(...))` 回查原文版本。

算法按句切分，使用查询词频、逆句频、句子和文档覆盖率评分；英文采用轻量词形归一化，
中文采用双字词项。归一化仅参与评分，不改变输出文字或坐标。相同 entry 中重复句子去重，
同 scope 的重复候选按完整身份去重，不同 scope 的相同正文保留各自身份。
同一精确版本出现不同正文时抛出 `PreparedContextInvariantError`。

选择优先保留相关完整句子，用评分与新增字节成本权衡；同一 entry 的相邻片段合并并保留
中间空白。整句无法放入时可选择围绕查询词的原文窗口，不附加省略号或生成摘要。
没有可用词项匹配或预算不足时允许空结果。每次尝试都按最终 UTF-8 输出计费，包含原有
trust policy、envelope、JSON、citation、正文和区间数字。Unicode 行分隔符以 JSON 转义
保留，解码后仍为原字符。预算探测使用相同的选择路径。

Builder 的证据模式优先于文字 assembly 和 Code 渲染，只输出 Memory。Runtime 的召回、
授权与存储流程未改动；如果调用方的 assembly 排除了 Memory，可能没有可选择的候选。
选择本身不建立持久缓存。数据库重启后可从真实 Memory 重新选择，旧引用仍对应历史版本。

该算法是确定性词项启发式和贪心装包，不保证全局最优，也不能保证识别同义改写。
公开测试通过不代表正式 SciFact 的平均词项召回率 0.65 和完整覆盖率 40% 已通过。
测试包含 Unicode、JSON 转义、预算临界点、多片段、scope 身份、失败路径，以及五个独立
Python 进程中的 SQLite 写入、两次读取、修订/停用和历史引用回查。
