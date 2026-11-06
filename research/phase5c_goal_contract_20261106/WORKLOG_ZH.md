# Phase5-C 判断、问题与执行日志

2026-11-06。用户要求先单模型做一定数量独立题测试，再扩多模型多数据集；同时要求逐条回应外部建议。

## 启动前判断

采纳真实长轨迹终局读出、目标提示/摘录投影、完整历史和廉价尾窗强对照；不采纳选后8例推总体、单点验整除、父变量数值黑名单和预言全部救回。Rank62目标是共轭对乘积倒数和，建议文本把它误写成模长和。

明确区分模型数/数据来源数/方法条件数。本轮1模型、1历史来源、32互异问题、7条件=224预定输出；不是7篇SOTA复现或6个subject=6datasets。原300剔除P1的100后按ID哈希抽32，不按历史对错/cap/Wait选择。

当前可实现的是目标提示与自动UNVERIFIED候选选段，不是真值G/认证父边界。只有7个count类型被规则提示，25类型unknown；原题各臂都保留。FullContractEvidence/Projected共用完全相同packet；没有人工正确中间量、终局映射或Gold进入推理。

## 接口与评分准备

助手控制标签统一转义后重编码原T，不能声称历史原seed/cache精确重放。ForcedBoxCue开放box后也按EOS停止，与旧boxed-close协议不同。HF4.55.2 FP16 SDPA批最多2，左padding带mask；逻辑输出与物理padding/已EOS行计费分开，batch秒不除2冒充方法延迟。

CPU候选模块46项、批接口49项通过；随机tiny实际没有EOS，早晚EOS/完整tuple由独立mock覆盖。新grader初版已有38提取+19数学检查；启动前进一步拒绝5 or7/未封装逗号多对象等歧义，最终48结构+22数学后台smoke通过。未读32题Gold调规则，不回填任何旧分数。

## 唯一模型轮计划

两张3090独立运行同一Qwen3-4B，rank奇偶各16题；每题四批生成七条件。384额外生成token为本读出探索保护顶，EOS自然结束，不追加尾窗/不以解析成功停止。各worker850秒软限、外层880+kill5，合计≤30单卡分钟；所有启动/失败计入。

source、模型资产、224tokenizer输入、数据/提取/评分器在第一条新模型输出前冻结。最大prompt9528tokens，累计595893输入tokens（未含batchpadding）。一次性CPU准备0.143秒单列。

按预声明32问题执行，不以中途效果换题或改提取；Projected只有超过同证据Full/廉价Tail等强基线才有继续价值。最终修复/伤害、unknown/触顶、224完成率和实际成本将在此追加。

## 用户明确调整时间要求

用户指出3090为实验室自有，要求先跑完整再比。撤销主任务自行设的30单卡分钟研究截止；不改原PROTOCOL/freeze，而以USER_TIME_EXTENSION.json记录用户覆盖。原限时器已启动，保留其checkpoint退出后由续接进程调用原generate_batch，只补缺失job；旧结果不可覆盖，输入/384token/方法/评分均不变。此决定只根据用户授权与进度，尚未查看真实评分，不是按效果追加试验。

## 生成齐全与离线评分准备故障

原125+续99=224全部唯一输出，无缺失/重复；32全7臂齐全。3086项独立重数通过，旧139文件全未变，128批无弃用重算，总51.486914单卡分钟。EOS115、384token cap109，必须公开长度限制，不能称无限长度质量。

首次离线评分启动因未上传NATURAL_BANK_MANIFEST.json而退出，尚未开始任何评分、无GPU消耗；补齐原字节冻结清单后仅重启评分，不改grader、不重跑模型，错误日志保留为scoring_attempt_01.log。

## 统一评分、独立解释与阶段关闭

224/224评分完整、unknown0；Forced27/32、Full15、Contract14、同packetFull18、Tail11、Projection13、Restart8。候选对同packet Full为2修复/7伤害，对最强Forced0修复/14伤害；预声明扩大门槛未过，当前版不扩大。

独立核查Projected19失分是18cap＋1严格终端解析（C006已算对boxed10但后有representatives词），不能说19次数学错，主分不回填。Force与FullContinue同messages仅open-box前缀不同，12修复0伤害，指向读出阶段/交付长度这一待区分因素，非内在stagepointer证明。

用户要求下轮解开紧token上限并做好收尾。已完成PHASE_CLOSEOUT_ZH.md与docs/phases/Phase5C主入口，按目的/方法/数据与对照/配置/结果/问题证据/成本/猜想/下一步组织；NEXT_PHASE_REQUIREMENTS明确下轮正常EOS、技术保护分列、完整矩阵优先、同阶段2x2和新解析契约。旧384数据原样保留，未新增模型试验。
