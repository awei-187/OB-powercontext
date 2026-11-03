# 周报 · 【示例】高吞吐量 KV 存储的写放大治理

> 统计区间：起始不限 ~ 至今 ｜ 生成时间：2026-11-02 23:36
> 数据来源：PowerContext Scope `scp_0grac3gvbamavv84bm0xybemcj`（记忆条目为唯一真源）
> 时间口径：区间只过滤带日期的工作记录与已完成待办（按记录日期）；目标、决策、问题、下一步、资料出处为当前有效状态。研续不记录解决 / 完成的发生时间（PowerContext 变更日志不含时间戳），故不按区间推断。

## 一、研究目标

- 【示例】合成演示数据，全部数字均为虚构、非实测。演示目标：把 P99 写延迟从 12ms 降到 8ms 以内，且写放大因子不超过 6。 `mem_6069d06d@v1`

## 二、本期工作记录

### 基线复现：默认 leveled 合并

YCSB A 负载，1 亿条 1KB value，单副本。P99 写延迟 12.4ms，写放大因子 9.8。合并线程在 major compaction 期间抢占前台 IO，延迟毛刺集中在合并窗口。

来源：`mem_d035cca8@v1`
标签：实验、基线

## 三、已确认决策

| 决策 | 依据（PowerContext reason） | 来源 |
| --- | --- | --- |
| **合并策略改为 size-tiered + 每日凌晨 major compaction** — 前台只做 size-tiered 小合并，大合并移到业务低峰。预期写放大从 9.8 降到 6 以下，代价是空间放大上升到 1.4 倍。 | 空间放大可接受，写延迟是硬指标 | mem_dd6510c6@v1 |

## 四、未解决问题

_当前没有未解决的问题。_

### 已解决（当前有效状态，不按区间过滤）

- [x] **写入抖动是否完全来自 flush 抢占 IO** — 已确认：blktrace 抓到抖动现场 flush 与前台写共用同一 IO 队列，队列深度峰值 64。抖动根因就是转储抢占，不再是未知项。 `mem_b92d9f4c@v2`

_说明：研续不记录问题的解决时间，此节按当前状态列出，不代表发生在统计区间内。_

## 五、下一步计划

- [ ] **用 blktrace 抓一次抖动现场的 IO 队列深度** — 目标：确认 flush 与前台写是否在同一队列，以及队列深度峰值。如果确认，下一步再评估 io_uring 批量提交与独立队列隔离。 `mem_adf4ff83@v1`

## 六、待办

- [ ] **补齐 4KB / 16KB value 的对比矩阵** — 目前只有 1KB value 的数据，评审时被问到过大 value 场景。需要跑完 4KB 和 16KB 各三组，并记录空间放大。 `mem_9e9788b3@v1`

## 七、资料出处

1. **OceanBase LSM-Tree 合并策略设计说明**（<https://www.oceanbase.com/docs>） `mem_957636af@v1`
   - 相关性：官方文档中关于 minor / major compaction 触发条件与 size-tiered 策略适用场景的章节，是本项决策的主要依据。

## 八、上次工作交接

- 交接目标：【示例】合成演示数据，全部数字均为虚构、非实测。演示目标：把 P99 写延迟从 12ms 降到 8ms 以内，且写放大因子不超过 6。
- 交接判定：可继续
- 交接时已确认状态：
  - 合并策略改为 size-tiered + 每日凌晨 major compaction（引用：来源 yanxu-handoff-20261102-233508-069693、记忆 mem_ent_dd6510c6…@r10）
  - 基线复现：默认 leveled 合并（引用：来源 yanxu-handoff-20261102-233508-069693、记忆 mem_ent_d035cca8…@r10）
- 交接时下一步：用 blktrace 抓一次抖动现场的 IO 队列深度
- 交接时明确未覆盖：
  - 大 value（4KB/16KB）场景的实验矩阵未跑，本周报不包含该结论
  - 尚未评估 io_uring 批量提交对前台延迟的影响
- 交接工件：`handoff/handoff@r1`

## 附录 · 来源追溯表

_只列本报告正文真正引用到的记忆条目。_

| 引用 | 类型 | entry_id | entry_version_id | 条目版本 | 记忆工件版本 | 状态 | 变更序列 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| mem_6069d06d@v1 | 研究目标 | mem_ent_6069d06d4472495199ac2f72fc2fa119 | mem_ver_e74f446d15114ad288fa57837aa42b75 | 1 | 10 | active | add |
| mem_d035cca8@v1 | 工作记录 | mem_ent_d035cca81ef14cb08570800f21cc5536 | mem_ver_87851bd75b64463a8962eeb6de083c03 | 1 | 10 | active | add |
| mem_dd6510c6@v1 | 已确认决策 | mem_ent_dd6510c67f774b0e85825960a828582b | mem_ver_2069f9f2c4004232afa198b342e9bfb8 | 1 | 10 | active | add |
| mem_b92d9f4c@v2 | 未解决问题 | mem_ent_b92d9f4c96ba415a810db62ac371e034 | mem_ver_11185d221553412488c149d68509e8a1 | 2 | 10 | active | add → revise |
| mem_adf4ff83@v1 | 下一步 | mem_ent_adf4ff83bd5641c68e17ac031405a27e | mem_ver_8c43619d8a084918850f4d00d3c30879 | 1 | 10 | active | add |
| mem_9e9788b3@v1 | 待办 | mem_ent_9e9788b31e0a4820810b4ac8c009a62b | mem_ver_11d942a4835545df8f7e33faf9618900 | 1 | 10 | active | add |
| mem_957636af@v1 | 资料出处 | mem_ent_957636af10e04e8082412c5e96a93f82 | mem_ver_c51a2d1705a6450b942c921c0697a2b1 | 1 | 10 | active | add |

_本报告由「研续 Yanxu」基于 PowerContext 记忆自动生成，共引用 7 条记忆、1 条资料出处。_