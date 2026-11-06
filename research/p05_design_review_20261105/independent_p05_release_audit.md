# P0.5 真实 five-arm 结果独立审计

审计对象：`p05_five_arm_01`。本地 CPU/NumPy 独立复算，没有导入实验 runner 的指标函数，没有重新 forward 模型、GPU 或远程调用，也未补生成数据。

**通过已有产物的数值与绑定审计，运行状态必须保留为辅助诊断未完成。** 16 例的 80 个五臂主生成全部完成；辅助诊断只完成冻结顺序前 8 例，共 80 个 Y/Z probe，后 8 例没有做完诊断。这里的 partial 是预算退出，不是文件损坏或通过补题凑数。

## 数值与评分复核

- 160 个保存数组均为有限 `float32[151936]`：80 个 free、40 个 Z、40 个 Y。
- 对 JSON 已保存的全部 96 组全词表比较独立重算，384 个数值指标最大绝对差 **2.44×10^-13**，低于 1×10^-10 容差。另重算全部可用的 32 组同 family WholeLateOneLine/WholeEarlyOneLine 比较。
- 80 个 probe、220 个去重候选的完整 `logP=sum(token_logP)`、canonical 换行、角色别名、同值/同首 token 的 NA、缓存长度不变与额外 forward/token 账均核对通过。
- 首 token logP 由 NPZ 全词表重新计算，与原 float32 记录最大差 **1.60×10^-6**。后续 teacher-forcing 的逐位置全词表 logits 未保存，因此**没有声称独立重算了候选整段前向**；后续项只核对求和、索引/格式和记录一致性。

| 同 family Late/Early | 样本数 | 平均 TV | TV 范围 | 当前首 token argmax 改变 |
|---|---:|---:|---:|---:|
| free | 16 | 0.0001864 | 1.52×10^-10–0.002976 | 0 |
| forced Z | 8 | 0.29538 | 6.07×10^-7–0.98122 | 2 |
| forced Y | 8 | 0.01411 | 2.60×10^-17–0.11279 | 0 |

free 表只测读出后第一个 token，不代表完整续写无差异。Z/Y 又是独立的强制前缀条件，不是生成完 OneLine 后观测到的自然中间信念；不能跨两张表解释成阶段指针或污染强度。辅助诊断是时间顺序前 8 例，不外推至全部 16 例。

## 主分母、控制与成本

使用冻结 gold-blind extractor 重新提取全部 80 个 free 原文，逐例核对原 extraction、correct 标志及分组汇总，无需从候选分数选答案。主分母始终是 16 个完整五臂配对，未因辅助缺失或格式失败删题。

| 臂 | 冻结提取分数 | 可解析输出 |
|---|---:|---:|
| FullDirect | 8/16 | 16/16 |
| FullOneLine | 11/16 | 12/16 |
| WholeEarlyDirect | 0/16 | 16/16 |
| WholeEarlyOneLine | 12/16 | 14/16 |
| WholeLateOneLine | 8/16 | 11/16 |

这是本次固定评分协议的计数。未解析不等于已证明数学全错，不做 posthoc 补提取。表格通过审计也不等于策略具备统计或部署保证。

E01/C01/W01 三例完整控制共 27 项都通过，且本审计从保存的数值重新归约了通过条件；其余 13 例按预声明未运行完整控制，不能写成 16/16 全控制 PASS。

forward ledger 核对结果：**2961 次实际模型前向、16336 个前向输入 token、189.764 秒同步前向时间**，包括控制、probe 和候选评分。自由生成全部先于候选评分；Direct Z 复用零额外读出、其他 Y/Z 独立读出以及每个候选的输入 token 均与账本一致。保留 checkpoint 的内存实际计入运行，不宣称零开销。

worker 总 wall 为 **264.359 秒**，其中加载/模型哈希约 **29.978 秒**；主任务 launcher 记录为 **267.5468 秒（4.459 GPU-min）**，这是外层执行证据，不由 logits 反算。同步 forward 与总 wall 不相加，也不把嵌套 stage timing 重复累计。实际结束状态是 `P05_PRIMARY_RETAINED_DIAGNOSTICS_PARTIAL`；进程退出 0 不应改写为所有诊断完成。

## 预先冻结与实际输入绑定

独立核对了本地源码/病例/parser、manifest/逐例记录及模型文件 hash 列表：

| 对象 | SHA256 |
|---|---|
| runner | `91b6ed7c584bf7561073964f5dc08510ab10f7a92f35e9fa89d2efe669442742` |
| base | `246219aee9774fae0966c7663c765daf3dba2f1df68bc054b539a4dd5d64331b` |
| input | `6ffe069718396dc2543f85aa9270780f356e293cc9764afdaf2f06a083c5cc27` |
| extractor | `c2bc053b66778288f524d46f4353e825b1ee654d829027bd02b1cb3173255eed` |
| model manifest | `37ff9857bb53edf35d5c80bfa0c078b1cdb8d5e5aa864115d153e237cb854511` |
| prelaunch freeze | `a70ff643f4f513b90bb18b0943e5595ae6c0eb4b2a842dee9abb61bcfd5029df` |
| rendered inputs | `6ccef1ab340e99ae01172cf8e687892b9f94dd06147590f3ceb3a51e7ba6c973` |

16 个实际 core 与预冻结 core 深度相等；80 个实际 free 和 80 个已完成 probe 的文本、token IDs、原位置均逐项匹配冻结渲染。P/B/U/R 白名单、关闭 assistant、新 user、Direct/OneLine scaffold、同 family Late/Early 后缀均一致。未渲染 `independent_conclusion` 或评估字段。

本地核实的是文件/清单绑定和实际渲染；没有重新读取远程模型权重字节。预冻结发生于模型调用前的时间顺序依赖其 freeze 记录与主任务执行证据，本审计不把 hash 本身当作可信时间戳。

## 交付

[独立 CPU 审计脚本](D:/ACL/research/p05_design_review_20261105/independent_p05_release_audit.py) 与 [JSON 证据](D:/ACL/research/p05_design_review_20261105/independent_p05_release_audit.json) 保存错误列表（为空）、部分说明、37 个原始文件的本地 hash 快照、全部 free 文本、逐 case 控制状态、32 组 Late/Early 指标、成本及预冻结绑定。没有补齐后 8 例辅助分数，也没有把此次人工状态小试验升级为自然发生率、机制唯一识别或算法安全保证。
