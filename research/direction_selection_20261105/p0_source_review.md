# real_model_p0.py 独立静态审查

审查时间：2026-11-05。范围：读取脚本全部主路径，并对照 Transformers v4.55.2 官方 Qwen3/masking/cache 源码；未修改主脚本，未连接或运行 GPU。执行模型已由主任务选择为独占空闲 3090 上的只读 Qwen3-4B；这与此前候选 V100/1.7B 是不同平台/骨干，实际结果必须按 manifest 报告。

最后复核的脚本：733 行，SHA256 `246219aee9774fae0966c7663c765daf3dba2f1df68bc054b539a4dd5d64331b`。后续若脚本变化，应核对实际部署 hash。

## 结论

**未发现会使主比较立即失效的缓存串扰、gold prompt 泄漏、候选评分错位或 late/early 时点错误。** 当前 2D key mask 由固定版本的库叠加标准因果限制，方案正确；无需为了符合早先 4D 方案改成自制 4D mask。各臂保留同 token 槽位、同显式位置，late 从新 readout 开始才屏蔽，early 则在检查点 prefill 时屏蔽；这对应拟定机制对照。

审查中发现 early-prefill 禁读控制盲区后，实施者已补入 `prefill_attention_check` 及 target/random 两项前缀检查；本审查再次静态核对：它覆盖所有前缀 query，另检查幸存 query（含 U/R），并要求被屏蔽/未来列质量为零且 attention 有限。**这项源代码问题已修复，目标 GPU 上仍需实际通过。**

设备启动建议：本次以 **完整 GPU UUID** 同时设置 `CUDA_VISIBLE_DEVICES` 和 `--standalone-gpu`。主任务已确认采用 UUID 且该 UUID 的 compute-process 空列表已核验。数字 CUDA 枚举与 nvidia-smi index 可能因枚举顺序不同而不对应，此次启动不使用数字绑定。

## 已审通过的主路径

| 项目 | 源码检查 | 判断 |
|---|---|---|
| Gold/标签输入 | renderer 只取 question/old_branch/revision；不序列化 case；independent_conclusion 未渲染；group/oracle 字段只进入记录/评分 | 通过。revision 是共享的人为修订，不得对外描述成模型自己诊断 |
| 目标与随机预算 | target 为人工 B 段；random 从 B∪U 以稳定 case seed 抽相同 token 数；保护题目/修订/readout | 通过；random 粒度为 token，不能描述成所有语义粒度控制均已完成 |
| Late 时点 | base_cache 对 P/B/U/R 正常 prefill；readout 克隆后才把目标列设 0 | 通过；R 的旧状态保留是有意的待测历史影响 |
| Early 重算 | 用与原始完全相同的 ID/位置/shape，前缀 prefill 开始就屏蔽 key 列；现已加入 target/random 前缀 attention 控制 | 静态正确；GPU 首例须通过实际禁读观测 |
| Causal/位置 | 2D mask + 标准 eager causal 路径；position_ids 与 cache_position 显式从原始 start 增长；所有槽位保留 | 通过；对当前全形状方案没有 RoPE 重编号混杂 |
| 分臂 cache | readout 对输入 cache deepcopy；greedy 再 deepcopy readout cache；base 与 early_target_cache 未被 mutable append 修改 | 通过；动态 cache 的 clone 成本也在同步计时函数内 |
| 候选隔离 | 自由生成先完成；每个不同候选在 deepcopy(readout_cache) 上独立 teacher-force | 通过；候选中的 gold 不会反馈到自由生成 |
| 候选 logP 对齐 | 首 token 用 S 后的 initial logits；候选 ids[:-1] 的位置从 prefix+S 长度起；后续 logits 逐位评分 ids[1:]；包含固定换行且不做隐式长度归一化 | 通过；重合候选去重，对应 margin 记 None |
| 单步生成偏移 | 第一个生成 token 取 initial logits；随后输入该 token 的位置是 base+len(tokens)-1，mask 长度匹配缓存加新 token | 通过 |
| mask 真正禁读 | readout all-layer attention 汇总 masked/future mass；有限 ±8 的 V sentinel 对照 | 通过读出边界；不把 FP16 poison 设到溢出值 |
| 数值控制 | 同路径原始/early 重建、prefix-before-B、第一层幸存 KV、dense/cached shape 噪声分开记录 | 通过；不得把同路径 1e-3 门槛当作全部效果阈值 |
| 输出与预算 | 逐臂/逐状态原始记录；全词表 TV/JS/logit 差；分组行为计数；1800s watchdog，模型加载/哈希也计时 | 通过；1800s 比 1h 硬上限更紧，属于短跑 |

2D mask 的可用性依据是固定 v4.55.2 的实现，而不是本地 tiny check 使用的 Transformers 5.4。目标环境仍须完成现场控制。[固定 Qwen3 源码](https://github.com/huggingface/transformers/blob/v4.55.2/src/transformers/models/qwen3/modeling_qwen3.py)，[固定 masking 源码](https://github.com/huggingface/transformers/blob/v4.55.2/src/transformers/masking_utils.py)

## 已修复项与非阻塞边界

### 1. Early-prefill 控制：已补实现

初版 `run_controls` 中的 `attention_check_early` 来自 `runner.readout(early_repeat, target, attentions=True)`。如果 prefill 的 mask 因兼容性或以后改动被忽略、但 readout mask 正常，以下控制仍可能全部通过：early rebuild 可重复、prefix-before-B 相同、第一层幸存 KV 相同、S 看不到被删行。这样会把 early/late 的同质状态误当成没有残留效应的负结果。

实施者已补 target 与 random 的 `prefix forward(..., attentions=True)` 并纳入 `checks`。前缀不超过 512 token，函数只返回归约后的数值，不把全部 attention 写入记录；代码路径审查通过。GPU 通过后才能关闭这一接口验收项。

### 2. Random 控制的边界

主循环对控制状态五臂均保存 readout attention，最终 target late/early readout 检查之外，现已加入 target/random early-prefill 的实际禁读检查。随机集合来自 B∪U，且按 token 散点抽样，只匹配可见屏蔽数；它不匹配目标段的连续性、token 年龄/距离或语义完整性，也不是 Random Attention 作者算法的复现。即便目标干预胜过此随机池，也不能单凭它排除位置特异性或结构差异，更不能认证“逻辑证伪特异性”。这些限制属于本次短跑的解释边界，不阻止接口 P0。

### 3. 短前缀、明确修订与行为天花板

同路径 no-op 阈值是 FP16 工程门槛。结果分析应展示同路径最大噪声、cached/dense 分块噪声和实际 B/C 差，而不是只依据 passed=true。前缀短、运算仅 x→y→z、修订 x 显式给出、readout 再提示按原题定义核算，均可能让小题很容易；若所有臂正确，这是本任务的天花板/鲁棒性结果，不是自然长 CoT 无残留的定理。若仅有 KV/TV 差而答案不变，结论是状态机制差异；反之，仅 argmax 不同也不足以证明任务改善。C/W 组可暴露强制删段风险，不应由隐藏 oracle trigger 跳过。

## 首次启动与验收建议

1. 使用已核验空闲设备的完整 UUID，保持 model 路径只读、fresh output 目录；确认实际 PyTorch/Transformers 与 eager/FP16 参数进入 manifest。
2. E01 控制通过后按冻结顺序运行；若 mask、位置或 same-mask 重建失败，立即 `P0_INTERFACE_NO_GO`，不能继续解释后续性能。
3. 全部完成或达到既定时限后，立即按原始逐案例结果分析：目标 B/C 与随机 D/E 的分布差；E 的正确/旧错值承接；C/W 是否出现新伤害；全部实际成本。不得因看见阳性就延长预算或新增参数扫描。

本审查不把 CPU tiny fixture 的成功转化为真实模型或 GPU 成功；真实启动是否已完成、执行 commit/hash 和输出状态由主任务的运行日志确认。
