# Phase5-C 自然读出 runner：只读审查

2026-11-06。**本报告绑定版本的静态源码、CPU输入重建、已有batch接口证据与双GPU launcher审查通过，未发现剩余静态阻塞。** 这是新轮执行接口准入，不是新模型效果、CUDA/FP16数值保证或最终grader准入。本报告未运行模型、远程或GPU，未改runner/helper、数据、评分器或原始结果。

## 当前审查绑定

- `paired_readout.py` SHA256：`e08273ce10805173a693672484490b3821af6d34d987617a8055eb6647bf7ac5`
- `goal_evidence.py` SHA256：`9d86b95f423bcc4805574e4c1b1b91d0597b0fd14a1c4437b4c24460d28cd15f`
- `launch_pair.py` SHA256：`846bf5461dcc21bcad3de4e1b2d1e45d0a0427b5bb1c424404519e7441ed4be7`
- `CPU_BATCH_INTERFACE.json` SHA256：`c9846038f94e67d03b54838d9f245b09498125ac5328c55814c8e4e41b392791`
- `rendered_prelaunch.json` SHA256：`6b3abe1bc05810b52ca81b9433a790f97ef1d45203a8a5934449671456a5297d`
- helper的CPU契约46项通过；只归于合成CPU接口/出处/unknown控制，不是历史任务质量。

## 已独立核查

1. 完整读runner与helper。在线runner不读`bank_evaluation_only.jsonl`、Gold、旧correct或旧forced答案。独立调用纯CPU `prepare`，追踪`Path.read_text`只访问`bank_visible.jsonl`；生成的224个jobs与32个packet逐项等于保存产物。没有人工精读这32条历史正文或按结果改选择。
2. 32题均有7个方法；奇偶rank各112输出。`FullContractEvidence`与`ProjectedContractEvidence`的32对contract/packet hash全部一致，使用同一个渲染摘录。二者的差别是是否还保留完整历史，不能将额外候选信息独占给投影法。
3. `derive_contract`只看题干。无数值黑名单、无求得的终局映射；摘录全部`UNVERIFIED`，不同boxed文本表面不当真冲突，没有真值G或自动认证父边界。本32题只识别7个count提示、25个unknown；不得称全部终局语义已可靠提取，更不得称完整GC-PBP已经实现。
4. `ForcedBoxCue`实际与FullContinue共享相同system/user，只有额外assistant open-box前缀；其正常结束为EOS，而非旧代码boxed首次闭合。它只能叫历史式读出兼容对照，不能叫原历史执行精确复现。评分保留预填`\boxed{`，预填token属于prompt/控制输入，不冒充模型新生成。
5. batch2使用左padding与显式attention mask，交HF `generate`处理position/cache和逐样本EOS。每次`generate`未传前一批cache；序列在batch维度隔离，不互相读KV。保存原始生成token并按该行首EOS裁切，后续padding不混为逻辑生成。源码未用解析器、整数换行或boxed闭合提前停止。
6. hook按每次实际forward的`batch × sequence`记物理输入，包含padding和较早EOS行的后续批处理工作；逻辑生成长度分开。batch wall属于整批，不应除2当作单方法独立延迟，也不能把物理tokens、逻辑prompt/output再重复相加。
7. 模型资产manifest固定，真实worker要求TF4.55.2/Torch2.8.0、FP16/SDPA、指定UUID与空compute检查；32×7全部真实tokenizer输入在推理前重建并与冻结snapshot比较。已核对224个render与原jobs字段相符，prompt总595893、最大9528，384保护下均需主任务冻结model上下文准入。CUDA可见UUID由launcher分别固定为`GPU-ef01d441-985f-50b3-6e64-5d4c3e2def3a`与`GPU-a696ce9a-7137-cf6f-b4d3-deb992a72f28`，worker各自反查空compute。该检查不是调度器排他锁。
8. 批前写`in_progress`，完整批后写各条raw、batch ledger与progress；summary分别给planned/complete、完整7方法case、EOS/cap。预算停在半个case不能补成完整配对；硬kill可能只有上次完整批的ledger，未保存工作仍应以外层占用墙钟计入。结束后的`in_progress.json`可能只是最后一次已完成批的旧标记，不能据其存在认定worker仍运行。

## 成本与效力边界

`INPUT_PREPARATION.json`记录CPU准备0.14289秒，需单列在总处理成本，不因它在GPUworker前执行而免费。所有读出都重新编码已有历史文本，未生成新的原生长链；思考T是共同给定历史，原生成成本是共有前置成本。fresh-prefill的压缩/吞吐不能直接推断已有热KV状态的续接加速。

本轮能检验目标提示、摘录候选与去除完整历史的读出差别；不能以结果宣称已过滤自然假冲突、自动取到真父边界、全文无害压缩或端到端多数据集算法收益。32个唯一历史问题仍是旧开发池的非P1子集，不是正式从未使用过的独立测试。

七个方法名是七种读出条件/消融，不是七篇已有论文算法的忠实复现；也不能将六个subject说成六个数据集。

## CPU batch与launcher证据

已完整读`CPU_BATCH_INTERFACE_CHECK.py`与其49/49报告，报告绑定当前e082源码、TF4.55.2/Torch2.11.0+cpu的三层随机tiny SDPA。solo/batch、不同左padding长度、换另一行、交换行序、重复batch的逻辑token相同；HF生成的真实cache对象有6个且跨调用不同。16个无cache逐token argmax复核一致，最小top2间隔0.001806，不是刚好近似相等的空洞控制。

随机tiny初批没有EOS；**早/晚EOS、已结束行padding不评分、无EOS触cap及完整forced三元组覆盖来自单独确定性mock**，不冒称真实tiny/GPU都动态覆盖这些停止分支。独立重算每个report ledger中的physical输入和与保存汇总一致；mock混合EOS物理输入18、逻辑生成7，forced tuple的预填计入prompt、9个新token完整保留到EOS。CPU额外无cache验证forward不并入batch生成账本，也不拿CPU毫秒预测4B吞吐。

launcher为两个不重叠UUID各发一个独立worker，奇偶rank拆成各16题/112输出。worker软限850秒，GNU timeout880秒、kill-after5，Python等待timeout890秒；单次两worker名义上合计至多1780秒加少量调度/记录开销，计划上限1800单卡秒。实际预算还应以各worker外层elapsed相加核对，不能只报并行墙钟。源码拒绝覆盖已有launcher/results，也不自动重启失败worker。

`FINISHED`仅表示launcher线程已回收，需结合worker exit code、summary与raw判断COMPLETE/PARTIAL；任何ERROR/timeout都计费，不能把已保存完整批当全部实际工作。两worker并发、真实CUDA/FP16数值与显存故障仍需真实运行确认。

最终离线grader目前由主任务另行修订并做远程CPU复核；本审查未读取其实现或接受未完成的grader测试，不能代替那个独立准入项。只要runner/helper/launcher hash不变，本报告可加入新轮freeze；若这些源改变，先重新绑定对应CPU证据。
