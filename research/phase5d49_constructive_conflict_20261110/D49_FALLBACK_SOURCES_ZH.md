# D4.9 结构化构造候选来源

本次只核对论文方法、作者仓库与公开数据元数据。未打开候选实例、参考构造、参考值或模型结果。NLCO 有可复核的数据版本及结构化见证规范，可以进入下一步题面盲筛。ConstraintBench 提供方法和强对照线索，第一方可下载的数据版本、机器可读约束及许可证尚未核实。 [NLCO 正式论文](https://aclanthology.org/2026.findings-acl.1529/) · [ConstraintBench 原文](https://arxiv.org/html/2602.22465v2)

## 来源和隔离边界

| 来源 | 第一方可见证据 | D4.9 使用边界 |
|---|---|---|
| NLCO | ACL Findings 2026 收录。作者数据卡报告 43 个任务、S/M/L 三档和 6,450 条记录。Hub 数据公开且不设门禁，数据卡标注 MIT。 | S/M/L 是尺度分档。数据卡同时列出原题输入和参考解列，投影时须物理分离。作者标签有精确求解与启发式之别。拟用三个任务在元数据中标为 `exact_solver_reference`，逐例最优性仍需独立求解状态和上下界凭据。 |
| ConstraintBench | 论文 §§4.1–4.3 定义 10 个运筹域。模型提交符合 Pydantic 域模式的 JSON 决策。作者验证器逐条核验，并从实际决策重算目标。论文报告用 Gurobi 证明后纳入 200 条。 | 论文写明将公开发布。当前作者站点的研究路径回到主页，作者公开材料里未核实可用的任务文件、Pydantic 实现或许可。论文的公司尺度是生成种子维度，不能直接当作已固定的任务规模。保留为方法参考。 |

NLCO 作者代码仓库的 HEAD 为 `79438eb01b3d14e23bc945fd6b31854048c1c6b4`。Hub 数据修订为 `6a7dff75171906e0054ba6c92aa1ef8015b47c36`。该修订任务元数据 SHA-256 为 `86b5d75354ddab71316303eaa58247af60227a0e7decab508f08173b1ba9d218`。MIT 标注出自 Hub 数据卡，代码仓库的独立许可证及各原始资产的再分发条款需按所选来源复核。公开阶段凭据只需要来源标识、哈希和独立核验结果。 [作者代码版本](https://github.com/jing12e/nlco/tree/79438eb01b3d14e23bc945fd6b31854048c1c6b4) · [固定数据卡](https://huggingface.co/datasets/summer142857jiang/NLCO/blob/6a7dff75171906e0054ba6c92aa1ef8015b47c36/README.md) · [任务元数据](https://huggingface.co/datasets/summer142857jiang/NLCO/blob/6a7dff75171906e0054ba6c92aa1ef8015b47c36/benchmark_task_specs.json)

题面筛选只投影 ID、规模、`prompt`、输入实例和标识映射。封存 `reference_solution_canonical_json`、`reference_solution_surface_json` 与 `reference_objective_value`，模型工作目录只放题面投影。冻结后逐条核对题面是否泄露所求目标值，区分原题给定限制、示例及需要推导的最优值。原始图、项目网络或装箱实例若被重采样、重命名或变换显示形式，按原题来源分组。公开 ID 可以定位发布记录，但不能单独证明独立性。若八道题的原始身份无法复核，缩小候选集合并记录缺口。 [数据卡的字段定义](https://huggingface.co/datasets/summer142857jiang/NLCO/blob/6a7dff75171906e0054ba6c92aa1ef8015b47c36/README.md) · [论文附录 C、D](https://aclanthology.org/2026.findings-acl.1529.pdf)

## 三个候选家族

| 任务与原生见证 | 尺度和来源 | 局部精确冲突 | 强普通完整求解 |
|---|---|---|---|
| `RCPSP`。JSON 活动记录数组，包含开始和结束时间。目标是项目工期。 | 4–10／11–15／16–21 项活动。论文从约束规划基准重采样并修改活动、资源和先后关系，作者用 CP-SAT。 | 两项已承诺活动违背先后关系，或一个资源及一个时点的已承诺活动子集超容。只需核对活动身份、持续时间、资源需求和该时点是否落在实际占用区间。 | 整数区间变量、先后不等式和每种资源的 `add_cumulative`。先算关键路径与资源下界，用普通串行调度构造上界，完整证明由 CP-SAT 给出。 |
| `2SP`。JSON 放置记录数组，字段包括 `item_type`、坐标、宽和高。目标是已用条带高度。 | 5–10／11–15／16–25 件。作者从 2DPackLib 抽取物品类型与需求量，调整宽度和高度限制后用 Gurobi。 | 两个已放置对象有正面积重叠，或一件物品越过边界。多件同型物品按数量核验，不能把重复类型当成重复 ID。 | 轴对齐区间与 `add_no_overlap_2d`，配合面积下界和普通货架装法上界。入组先冻结是否可旋转、边界相切、数量和原题高度限制，坐标网格未确认时不宣称整数 CP-SAT 已覆盖原域。 |
| `GCP`。JSON 颜色类数组。目标是使用的颜色数。 | 8–12／13–18／19–25 个顶点。公开元数据标明 DIMACS10 引用及合著图，作者用 Gurobi。 | 原图一条边的两端已被承诺同色，即可核验冲突。重复或不存在的顶点另记格式及身份。未出现的顶点在部分输出里保持未知。 | DSATUR 选择顺序的精确分支定界，配合团下界及贪心上界。贪心自身只提供可行着色。当前规模适合作为便宜完整求解的对照。 |

表中的见证格式和分档来自固定任务元数据。半开时间区间、条带边界及旋转都以经核对的原题为准。普通强对照可使用同一语义的 CP-SAT 模型，记录求解状态和界。仅有可行返回时只认可已核验的构造。 [任务元数据](https://huggingface.co/datasets/summer142857jiang/NLCO/blob/6a7dff75171906e0054ba6c92aa1ef8015b47c36/benchmark_task_specs.json) · [NLCO 附录 C](https://aclanthology.org/2026.findings-acl.1529.pdf) · [OR-Tools 约束语义](https://github.com/google/or-tools/blob/stable/ortools/sat/cp_model.proto) · [Brélaz 图着色原文](https://doi.org/10.1145/359094.359101)

`RCPSP` 和 `2SP` 优先做题面盲筛。前者可用先后关系和资源子集两种冲突，后者可用两件物品的相交区域。`GCP` 补充极小局部证书与短完整求解的校准。每个家族都先计入原题绑定、输入编码、求解、候选核验和失败尝试。若普通完整求解已廉价覆盖，则将该家族归为负结果。论文的渲染格式、初始实例规模或求解器名称本身不能证明代价差。 [2DPackLib 原始入口](https://site.unibo.it/operations-research/en/research/2dpacklib) · [DIMACS10 原始集合入口](https://sparse.tamu.edu/DIMACS10)
