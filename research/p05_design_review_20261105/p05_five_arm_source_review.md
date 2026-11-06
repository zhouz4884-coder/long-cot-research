# P0.5 five-arm runner 独立快审

2026-11-05。只读审查 `p05_five_arm.py` 全部核心路径，并核对冻结科学草案、旧 base/parser SHA、16 例角色目录及 release CPU 产物；没有改源、启动 GPU 或远程任务。

**结论：release 版本未发现剩余源码阻塞，可以交由主任务按冻结版本和既定总预算执行。** 这只是源代码与 CPU 接口通过，不是 GPU 已通过、模型有效或 W 安全。

最后复核 SHA256：

`91b6ed7c584bf7561073964f5dc08510ab10f7a92f35e9fa89d2efe669442742`

## 核心路径检查

| 项目 | 结果 |
|---|---|
| 消息边界 | 旧 P/B/U/R 是一个 assistant continuation；明确追加 im_end 关闭，再拼完整新 user + nonthinking assistant 模板。新 suffix 不重复渲染旧题或 oracle 字段 |
| B mask 地址 | 关闭旧 assistant 只在末尾追加 token，旧 B 列地址不偏移；P/R/关闭标记/新 user/readout 均不被 B mask 覆盖 |
| Late/Fresh 同 suffix | FullOneLine、WholeLateOneLine、WholeEarlyOneLine 的 free readout ID 完全相同；FullDirect/WholeEarlyDirect 也相同。位置均接实际新 core 长度，无压缩 |
| Early/Late 时点 | Early 从完整 core prefill 起禁读 B；Late 正常编码 core，仅新 readout/续写禁读 B。旧 R 与关闭标记的缓存路径差异是明确的干预对象 |
| Free 与 gold 隔离 | 第一阶段先做全部可完成的五臂自由生成，第二阶段才构造候选角色并评分。base.greedy 深拷贝 readout cache；每个候选再次独立深拷贝 |
| Z 复用 | Direct free 与 Z forced prefix 逐 ID 相同才复用 checkpoint/logits；OneLine Z 与 Y 都另行从未生成的 prefix 分支前向 |
| Y/Z 位置 | 从 core 后各自 readout 的真实长度计算位置；Y 与 Z 的 readout 不混用，均标为强制前缀诊断，不是自然生成中的中间信念 |
| logP 偏移 | 首 token 用 readout 最后 logits；输入候选 ids[:-1] 从 readout 后第一位置起，逐位预测 ids[1:]；含换行、完整序列求和、无隐式长度归一化 |
| 去重/别名 | 相同 canonical token 序列只前向一次，保留角色 aliases；同首 token 的边际区分标 NA，完整候选相同的 margin 也 NA |
| 完成状态 | 五个 free 都完成才 primary_complete；十个 Y/Z probe 完成才 diagnostic_complete。辅助超时不会抹掉已完成 primary；完整分母只用完整五臂配对 |
| 控制失败 | 预定 E01/C01/W01；失败为全局 INTERFACE_NO_GO 并退出2，不应解释其 primary 表为有效性能 |
| 成本/预算 | 275 秒 watchdog 从导入/hash/load 前开始；forward ledger 包含所有 prefill、free、控制、probe、candidate。外层≤300秒总预算仍由主任务绑定 |
| 可审计输出 | 每臂 free/渲染/位置/提取/metadata 持续落盘；release 在常规 partial/failed-control 分支也写已完成的 free NPZ；每次前向检查 finite logits |

runtime 绑定 base SHA `246219...331b`、parser SHA `c2bc05...5eed`、病例 SHA `6ffe06...cc27`、真实模型 manifest `37ff98...4511`。不满足即失败，无静默换模型/解析器/版本。实际 GPU 要求 HF4.55.2 与 torch2.4.1/2.8.0；tiny CPU 证据使用 HF4.55.2 / torch2.11.0+cpu，不能冒充 GPU 数值验收。

## 独立核对的 release CPU 记录

读取 `tiny_cpu_p05_4552_release`：3 个完整 primary、3 个完整 diagnostic；27 个预声明控制检查通过，30 个 Y/Z probe 完成。独立检查：

- 三例中 OneLine Late/Early/Full 后缀 ID 一致；Direct 两臂 ID 一致。
- Direct Z 的额外 readout 前向为 0，其他独立 Y/Z 为 1；候选评分前后 checkpoint cache 长度不变。
- 独立 AST 计算全部 16 例四角色，与冻结 `fixed_candidate_roles.json`（SHA `84f1f15d...564c9b`）逐项一致。运行时角色由冻结源函数计算，角色文件不是另一个被动态选择的候选来源。
- forward ledger 最后一个 free-greedy 条目索引 143，首个 candidate-scoring 条目索引 153，确实没有候选评分先影响自由生成。

这批 tiny 输出没有数学性能含义，仅用于验证接口与成本记录。

## 非阻塞的解释/部分产物边界

1. OneLine 与 Direct 作为整个读出策略比较：Direct 固定 `最终答案：`，OneLine 不强制从 y 开始。它不是只改变一个“内部阶段变量”的纯干预。旧 P0 用不同 S，跨轮准确率差不能直接作为方法提升。
2. OneLine 的辅助 Z 前缀没有真实生成的一行推导；Y 前缀也不是模型自然到达的中间状态。两者只是另计成本的 conditional score probe。
3. prefix/checkpoint 留存会占用实际显存；绝不能把复用/缓存共享称作没有成本。源代码已记录绝对 postload allocated peak 和所有 forward。
4. 受控循环预算退出时保存 partial NPZ；若 watchdog 在下一个 arm 中途硬杀，当前 case 的 raw free JSON 仍保留，但尚未到循环末尾写入的 logit bank 可能缺失。此时按文件完整性标 partial，不宣称该 case 的完整诊断可复算；不要自动重试补齐。
5. `partial` 可以退出0，所以验收必须读 summary/status、primary/diagnostic计数、deadline/error文件，不能以进程0替代“全部完成”。正式控制只覆盖三例，其他13例不得标为完整控制 PASS。

本审查没有把独立 crop CPU 控制接入该 runner，也没有给它添加任何拒绝修订的安全门。裁尾正结果和 five-arm 干预的任务收益应继续分开报告。
