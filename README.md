# Long-CoT Research

长思维链研究：以**最终回答正确率、同预算的算法增量和完整成本**为主线，探索局部修订后的有效计算复用与答案交付。

私有研究仓库：[zhouz4884-coder/long-cot-research](https://github.com/zhouz4884-coder/long-cot-research)。原工作目录为 `D:\ACL`。更新日期：2026-11-06。

## 从哪里开始

- [Phase 1–5 总索引](docs/phases/INDEX_ZH.md)
- [当前研究目标](docs/next_phase/CURRENT_RESEARCH_GOAL_20261105_ZH.md)
- [最新建议审查与下一轮公平对照](research/repository_phase_plan_20261106/ADVISOR_REVIEW_20261106_ZH.md)
- [最新实测：P0.5五臂短试](research/p05_design_review_20261105/RUN_STATUS_ZH.md)
- [文件发布范围与来源](docs/repository/PUBLISH_SCOPE_ZH.md)

## Phase 导航

| 阶段 | 内容 | 当前状态 |
|---|---|---|
| [Phase 1](docs/phases/Phase1_历史研究与早停_NO_GO_ZH.md) | 历史步骤干预/早停研究、负结果与冻结的后续路线 | 原研究归档；后续大队列冻结 |
| [Phase 2](docs/phases/Phase2_从零文献与方向选择_ZH.md) | 从零长思维链文献地图、模块拆解与方向选择 | 62项资料；不是62篇全部复现 |
| [Phase 3](docs/phases/Phase3_P0状态恢复机制与首轮证据_ZH.md) | CPU缓存机制与真实P0五臂 | 短试完成；原严格与后验评分分列 |
| [Phase 4](docs/phases/Phase4_理论审查与P05五臂短试_ZH.md) | 模型/数学审查、P0.5、裁尾复用、候选溯源 | 16题primary完成，8题诊断完成 |
| [Phase 5](docs/phases/Phase5_候选算法与公平基线_计划_ZH.md) | 版本一致的局部重推、预算内交付与强baseline | 计划/协议阶段，尚无新算法benchmark成绩 |

每个Phase统一记录：问题、输入与协议、实际动作、数据结论、失败与猜想、下一门槛、证据路径。后续工作继续新增Phase或阶段内子报告，不改写已冻结的结果。

## 当前实际结果

| 研究 | 实际结果 | 结论边界 |
|---|---|---|
| 历史主300题 | FULL269/300，旧控制器248/300；耗时节省44.89%伴随7pp损失 | 旧控制器NO-GO，历史数据保留 |
| P0人工16状态五臂 | 事后解析7/3/5/7/5；原严格各0/16 | 输出格式问题与数学结果分开；不作正式benchmark |
| P0.5同轮五臂 | 8/11/0/12/8；4.4591单卡分钟 | 80自由输出全完成，辅助诊断8题；联合净+1涉及预算/交付差异 |

P0与P0.5使用不同读出协议，不连成跨轮提升曲线。CPU随机模型、形式/代数控制、人工短状态、自然轨迹观察和正式benchmark各自标明，不互相替代。

## 研究定位与候选算法

定位可以随证据调整。目前不要求结果必须来自KV掩码，也不预设内部阶段指针已经存在。可研究的主线是：

```text
核验修订与旧状态依据
    → 维护变量/规则版本和依赖
    → 仅安排必要的待重推前沿
    → 显式绑定当前父值并验收结果
    → 在总预算内交付最终答案
```

这是候选方法；核心增量尚待实测。Phase 5会比较共享同一核验/工具权限的简单路由、紧凑OneLine、Self-Ask/普通步进及版本工作帧；尾窗提交策略单列，并对所有比较方法公平使用。不会把顾问给出的90%正确率/省50%token预测写成结果。

主要指标是逐数据集accuracy或声明采样协议的pass@1；pass@k另列。完整成本包括核验、解析、被拒候选、注入前缀、prefill、重构与最终输出。NLL、梯度、KV距离和机制标签仅用于诊断。

## 目录

```text
docs/phases/                 Phase1、Phase2、Phase3……总报告与索引
research/long_cot_landscape_20261105/  文献与模块地图
research/direction_selection_20261105/ P0、平台与方向选择
research/next_design_20261105/         下一轮协议、抽样与合流控制
research/algorithm_mechanism_20261105/  算法/模型/数学分析
research/p05_design_review_20261105/    冻结P0.5与独立审计
research/repository_phase_plan_20261106/ 本次整理与建议审查
scripts/ reason_transition/ tests/     原研究实现与检查
experiments/radar20261013/             后续历史路线，当前冻结
data/ results/ provenance/ recovery/   历史输入、输出和恢复证据
```

仓库保留可上传的研究代码、协议、资料索引、原始结果与审计。模型权重、认证材料、本地依赖环境和重复打包文件留在本地；具体范围及原始Git来源见[发布说明](docs/repository/PUBLISH_SCOPE_ZH.md)。冻结证据按字节保存，新增Phase文档使用可在GitHub浏览的相对链接。历史报告中原机器绝对路径作为来源记录保留，不代表云端可访问路径。

## 历史入口

- [整理前根README](README_LEGACY_20261106.md)
- [历史综合报告](docs/REPORT_ZH.md)
- [历史18周目标（不作当前执行指令）](docs/next_phase/RESEARCH_GOAL_V2_20261014_ZH.md)

当前没有对外发布的正式新算法benchmark收益、录用结论或通用正确性保证。研究目标是通过新机制、强基线、消融和独立验证获得可复现的正增量；必要时保留负结果并调整方向。
