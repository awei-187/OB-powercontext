# PowerContext 真实持久化 smoke test 记录

- 时间: 2026-11-02 05:50:57 -0700
- 主机: Windows Microsoft Windows [�汾 10.0.26200.9711]
(c) Microsoft Corporation����������Ȩ����

E:\Ocean Base\qoder-competition\qoder>
- Python: 3.11.17 D:\conda\envs\oceanbase\python.exe
- powercontext: 1.2.0
- 模型密钥: 未配置（InferenceConfig() 全 None）
- 数据目录: qoder/data/smoke/（测试前已删除，确保从零开始）

## 阶段 1 · 进程 A 写入后退出

```console
$ python scripts/smoke_persistence.py write
[write] PowerContext Server 已启动: http://127.0.0.1:60141
[write] SQLite 文件: E:\Ocean Base\qoder-competition\qoder\data\smoke\smoke.db
[write] capabilities.memory_extraction = False
[write] capabilities.search_modes      = [<MemorySearchMode.AUTO: 'auto'>, <MemorySearchMode.FTS: 'fts'>]
[write] scope_id = scp_3qwxhmv549mb3j8q0j0adb4snv (version=1)
[write] 已写入记忆 entry_id=mem_ent_6a820588293844d58d52e3a5eb0cce5b
[write]            entry_version_id=mem_ver_8a5af46692e0425a8a08b3e838a221cf
[write]            memory_ref={'family': 'memory', 'artifact_id': 'memory', 'revision': 1}
[write]            version=1 state=active
[write] 写后立即 FTS 检索 'Decimal': 1 命中, mode=fts
[write] 期望值已落盘: E:\Ocean Base\qoder-competition\qoder\data\smoke\smoke-state.json
[write] Server 已停止，进程即将退出。
exit=0
```

## 阶段 2 · 进程 B（全新 OS 进程）重开同一 SQLite 后读回

```console
$ python scripts/smoke_persistence.py read
[read] 新进程重开 PowerContext Server: http://127.0.0.1:57290
[read] 复用同一 SQLite: E:\Ocean Base\qoder-competition\qoder\data\smoke\smoke.db (exists=True)
[read] Scope 幂等复用: scp_3qwxhmv549mb3j8q0j0adb4snv == scp_3qwxhmv549mb3j8q0j0adb4snv -> True
[read] list_memory_entries 返回 1 条活跃记忆
[read] get_memory_entry(旧 citation) -> kind=decision version=1 state=active
[read]   文本一致   : True
[read]   类型一致   : True
[read]   版本一致   : True
[read] 重开后 FTS 检索 'Decimal': 1 命中, mode=fts -> True
[read] list_memory_changes 变更序列: [<EntryChangeOperation.ADD: 'add'>]
[read] 读回的正文:
[read]   | YX1
[read]   | title=金额一律用 Decimal 存储
[read]   | date=2026-11-02
[read]   | status=confirmed
[read]   | ---
[read]   | 禁止 float；跨会话必须能读回本条。
[read] 结论: 通过 —— 记忆跨进程真实持久化，读回内容与写入完全一致。
exit=0
```

## SQLite 文件真实落盘证据

```console
$ total 597
-rw-r--r-- 1 wjp 197121 610304 Nov  2 05:51 data/smoke/smoke.db
```

## 结论

写入进程完全退出后，新进程重开同一 SQLite 文件，Scope 幂等复用同一 scope_id，
记忆文本 / kind / entry_version_id 全部一致，FTS 检索命中数一致，变更历史含 add。
无 mock、无内存数据库、无 localStorage。
