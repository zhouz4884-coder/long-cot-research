# DynamicCache 尾裁剪与拒绝分支恢复审查

2026-11-05。本轮只做官方源码核对和本地 tiny Qwen3 CPU 控制；未运行训练模型、GPU、SSH 或新五臂实验。旧文件未改。补充建议只作为待审设计，不自动成为执行指令。

**正结论要保留：标准因果 DynamicCache 的纯尾部候选可以原位裁掉，未改变的前缀 KV 可以直接复用，不需要重算此前缀。** 本轮在精确 Transformers 4.55.2 上实际验证了这个结论。它不等于整个拒绝事务严格 O(1)、全程零拷贝/零计算，也不推出 W 组增量伤害普遍为零。

## 1. 版本与来源

没有用系统 Transformers 5.4.0 代替目标版本。在本新目录的 `runtime4552` 中隔离安装 Transformers 4.55.2、tokenizers 0.21.4、huggingface_hub 0.34.4，不改全局包；复用本机 PyTorch 2.11.0+cpu。tiny 模型随机初始化、3 层 full-attention eager、hidden=32、Q heads=4、KV heads=2、head_dim=8、FP32、CPU、eval、单线程、固定五个 seed。

五个关键安装源码与 GitHub 官方 `v4.55.2` tag 下载文件逐字 hash 相同；清单保存在 [official_sources/manifest.json](D:/ACL/research/p05_design_review_20261105/official_sources/manifest.json)。其中：

- cache_utils.py：`9be3034ffd59b0493bacbefe921dec337fec7c9ed5ef78cfcb59c1ce08fed44a`
- Qwen3 modeling：`2d4441e36b40799b05ab514d8774b12e15fd5412699d444509b0a610ce23c9b8`
- generation/utils.py：`6de1a0fbf0b26352cbd93a2f494fc5fca1856e6636d20947e81f7f83ace7dec5`

另核了 logits_process.py 和 stopping_criteria.py，全部安装/官方文件一致。公开源码/依赖获取不涉及远程计算服务器；CPU 控制脚本本身不联网。

## 2. 官方 crop 实际做了什么

`Cache.crop` 遍历所有层；标准 `DynamicLayer.crop` 将 K/V 绑定为前缀切片。对固定层数，这个裁尾元数据操作不随前缀元素数增长；若把层数 L 作为变量，则逐层工作是 O(L)。不能把这个局部操作扩大为整个核验、回滚和续写协议的严格 O(1)。[官方 cache_utils.py v4.55.2](https://github.com/huggingface/transformers/blob/v4.55.2/src/transformers/cache_utils.py)

标准 dense DynamicLayer 的切片不复制 KV 数据，但保留原 backing storage 的引用，尾部的物理存储不因此立即释放。后续 `update` 采用拼接，原先写 R 和之后 append 都可能有新的分配/复制。这些成本属于整个路径，不能由 crop 的零数据拷贝隐藏。这里不外推到量化、滑窗、offload、其他 cache 子类或自定义原位写层。

## 3. 实际 CPU 同路径控制

每个 seed 都先编码 7 token 的可信前缀，保存其 next-token logits；主 cache 原位写入 3 token 的候选 R，再执行 `crop(7)`。独立对照从未写 R。两边随后输入相同的 2 token readout，位置均从 7 开始，mask 和算子路径相同。

| 检查 | 五个 seed 的结果 |
|---|---|
| crop 后 K/V 与 pre-R 控制逐元素最大差 | 0 |
| 相同 readout 后 logits 最大差 | 0 |
| 相同 readout 后所有层 K/V 最大差 | 0 |
| cache 对象原位保留 | 是 |
| 每次 crop 调用层数 | 3 |
| crop 后 K/V 与 post-R backing storage 相同 | 全部 30 张 K/V 都相同 |
| crop 是否缩小 backing allocation | 否 |

一个 K/V 的实际例子：形状从 `[1,2,10,8]` 裁为 `[1,2,7,8]`，逻辑大小 448 bytes，但 storage 仍为 640 bytes；裁剪后可能非连续，storage/data pointer 与裁前相同。测量在 inference_mode 中，autograd 的 `_base` 可为空，**不能拿 `_base is None` 当作发生数据复制的证据**；这里用 storage pointer/容量、内容相等和源码共同判断。

这些比较的完整 pointer、stride、shape、storage_offset、dtype、device、`position_ids`、`cache_position` 和 cache/layer 对象 ID 都在 JSON 中。测试中为了建立独立比较分支做了 deepcopy，明确属于测试夹具，不声称生产 crop 需要复制整个前缀。

这个正结果成立的原因是因果前缀不会读取后面的 R，而标准 append 没有改写既有前缀值。先前“中间删段后保留后继状态不等于干净重算”的负结果与此不矛盾：裁尾移除了**全部**受拒绝尾段及其后继；中间 mask 则保留了已经读过被删段的后继。

脚本还用同一 pinned tiny Qwen3 做了中间 mask 对照：同位置 Late/Early 的 readout logits 最大差约 0.0142–0.0417，幸存后继 KV 也不同。它再次说明两种操作不能混称为同一种恢复。

## 4. crop 不恢复 logits

crop 返回 None，不生成新的 hidden state 或 LM logits。若程序仍拿 post-R 的最后 logits 选 token，选择依据仍是拒绝分支的读出。五个 seed 中，pre-R 与 post-R logits 的最大差约 0.295–0.534，首 token argmax 均不同；这不是数学题准确率测试，而是实际不等价反例。

有两种合法做法：

- **保存 pre-R next-token logits**，拒绝后重新使用它；无需为了恢复此 logits 重算整个前缀。
- 没保存时，可以裁到 `t_preR-1`，把可信前缀最后一个 token 在原位置重做一次，恢复长度 `t_preR` 和 logits。实际控制只重做了一个 token；同刷新路径两边差 0。它与原先整段 prefill logits 有约 3–6×10^-8 的 FP32 shape 差，不能冒称逐位恢复原路径。直接把最后 token 再追加到已有长度 t_preR 的 cache 会重复一个 token。

如果下一步本来就是一个固定新 readout S，则裁完直接按正确位置输入 S，也可得到与“从没走 R”相同的读出；这次新 S 的前向是两条比较路径共同的后续计算，并非 crop 本身生成了 logits。

## 5. 位置、输入历史和停止状态不属于 crop

本夹具中，crop 后让 Qwen3 从当前 cache 长度自动推导 position 也与显式位置对照完全相等。但生成循环若保留了旧 `cache_position`/`position_ids`，crop 不会替它重写这些外部变量。[Qwen3 v4.55.2](https://github.com/huggingface/transformers/blob/v4.55.2/src/transformers/models/qwen3/modeling_qwen3.py)，[generation/utils.py v4.55.2](https://github.com/huggingface/transformers/blob/v4.55.2/src/transformers/generation/utils.py)

CPU 反例故意把新两 token 的位置仍设为 10/11，而实际 cache 已回到 7。5/5 出现输出变化，且第一个新 query 错误看到后一个新 token，未来 key attention mass 约 0.191–0.517；正确位置控制为 0。这个结果只针对显式传入过期位置，不意味着 crop 后省略位置必然错误。

实际输入 token 序列、mask、解码器输入游标也要匹配 checkpoint。不能用文本长度猜 cache 长度：某些生成循环在采出最后 token 后尚未将它 prefill，二者可能相差一个 token。应记录真实 `cache.get_seq_length()` 和哪些 ID 已被处理。

官方 repetition-penalty processor 根据 `input_ids` 历史工作；本测试裁 KV 后若仍传带 R 的 IDs，分数仍变。官方 EOS/MaxLength criteria 在本夹具上也从“未停止”变“停止”，因为它们看到的序列仍有候选 EOS/额外长度。crop 不会自动恢复 input_ids、unfinished_sequences、beam/grammar 状态或外部停止器。[logits processors](https://github.com/huggingface/transformers/blob/v4.55.2/src/transformers/generation/logits_process.py)，[stopping criteria](https://github.com/huggingface/transformers/blob/v4.55.2/src/transformers/generation/stopping_criteria.py)

## 6. RNG 和成本不能被裁尾“退回”

候选采样会推进 RNG；crop 只处理 cache。本 CPU 控制用实际 torch.multinomial：在相同可信 next-token 分布上，5/5 的“采过候选但未还原 RNG”下一采样与未走分支控制不同；恢复 RNG 后与控制一致。它证明路径耦合需要 RNG checkpoint，不证明哪个随机 token 在真实题目上更正确。

本测试候选 R 的 3 token 前向确实运行，成本为正；即使裁尾本身只有轻量 metadata 操作，候选生成、G 核验、日志和可能的一 token logits 刷新也不是零。物理时间已消耗，不能通过把 token counter/RNG 往回设就抹去。硬墙钟预算下，额外分支可能使剩余正式推理时间变少。

## 7. 可成立的零“输出扰动”命题及边界

可以写一个限定的**拒绝分支非干扰**命题：在相同标准因果模型、append-only dense cache、固定执行路径下，候选仅追加到尾部且不修改旧前缀；拒绝后恢复同一可信前缀 KV，并恢复用于后续解码的全部状态（IDs/mask/位置、next logits、RNG、processor/stop/beam 状态及相同后续指令），若共同后续未受到墙钟截止等外部变化影响，则恢复路径与从未走候选分支的对应后续输出可以相同。本轮贪婪同路径控制实际达到 KV/logit 差 0。

这不是普遍的“W 伤害绝对为零”：

- 它以 G 已正确拒绝为条件，不覆盖错误修订被误接受。
- 它以旧状态可信为条件，不把本来错误的旧答案变正确。
- 只裁 KV 而未恢复其他状态，不满足该命题；实际反例已给出。
- 相同输出不是质量保证；恢复的是 active prefix 的计算状态，不是任意题目的正确答案。
- 额外延迟/计算与硬预算影响仍然存在；同一理论随机分布也不能替代需要路径复现时的同 RNG 状态。

所以建议正式文字用：**“在已拒绝的纯尾部候选上，可复用未变的因果前缀；完整 checkpoint 恢复后，特定同路径控制未观察到输出差。其质量、核验错误率与额外成本分别评估。”**

## 8. 产物与下一步边界

- [CPU 源码](D:/ACL/research/p05_design_review_20261105/crop_tail_cpu_control.py)：固定五个 seed，精确 HF 4.55.2，运行时只用 CPU，不联网。
- [CPU JSON 证据](D:/ACL/research/p05_design_review_20261105/crop_tail_cpu_control.json)：所有检查、pointer/storage、位置、logits、RNG/processor/stop 反例及 source hash。
- [官方源码清单](D:/ACL/research/p05_design_review_20261105/official_sources/manifest.json)：五个文件 URL、SHA256、与安装文件逐字一致的结果。

这份 crop 控制独立于新 five-arm runner，不给后者自动赋予 W 安全保证。本轮已完成 CPU 证据；等待主任务通知是否需要审查新 runner，不自行启动 GPU 或进一步模型实验。
