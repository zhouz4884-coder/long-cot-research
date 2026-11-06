# 配对批读出：CPU接口准入

2026-11-06。**49/49通过，未发现阻止一次已计划真实短试的接口问题。** 本报告没有运行GPU、读取32题bank/eval/Gold、改变`paired_readout.py`，也不判断新方法质量。

绑定被测源码`paired_readout.py` SHA256：

`e08273ce10805173a693672484490b3821af6d34d987617a8055eb6647bf7ac5`

复跑脚本：[CPU_BATCH_INTERFACE_CHECK.py](CPU_BATCH_INTERFACE_CHECK.py)；完整证据：[CPU_BATCH_INTERFACE.json](CPU_BATCH_INTERFACE.json)。脚本直接导入被测`generate_batch`与`compile_jobs`，不复制实现或另写替代解码器。

## 随机tiny模型实际覆盖

TF4.55.2、Torch2.11.0+cpu，固定seed20261106，3层hidden32的随机Qwen3、SDPA、合成ASCII tokenizer；CPU每条max8。不是Qwen3-4B权重或CUDA/FP16验收。

- 3-token与5-token两行形成真实左padding：mask分别为`00111`与`11111`，非pad语义位置从0开始。
- batch2和两次逐条greedy输出逐token相同。替换另一行、交换行顺序、重复整批都保持对应输出不变。
- 六次generate的首cache长度均0；实际观察到六个独立DynamicCache对象，无跨批复用。该检查非空集合通过。
- 独立uncached全前缀重放验证两行每步argmax；最小top2 margin为0.00180623，大于1e-5阈值，不是near-tie样本。
- 随机初始批两行都触8-token cap、没有EOS。该随机模型没有实际覆盖早/晚EOS；不能把下面mock覆盖归给它。
- 初始批物理prefill10 tokens、真实未padding prompt8 tokens、逻辑生成16 tokens、实际forward输入24 tokens。物理前向账与逻辑答案长度不能混用。

## 确定性mock单独覆盖

| 控制 | 结果 |
|---|---|
| 一行第2token EOS、另一行第5token EOS | 分别保留2与5token；已结束行的后续PAD不进入其答案 |
| 逐行EOS与物理执行计账 | 逻辑生成共7token；物理forward输入18token，含padding与结束后仍参与批执行的行 |
| 两行无EOS | 都保留完整8token并明确hit_cap |
| ForcedBoxCue完整有序三元组 | supplied `\boxed{` + generated `(2,3,4)}` + EOS，完整保留，不按第一分量/第一个数字截断 |

Forced tuple mock为了完整覆盖使用max16，区别于随机tiny的max8；mock不是模型质量试验。

## 强制prefix与缓存/成本边界

`compile_jobs`确实将`Final answer: \boxed{`追加到assistant输入，其token数计入prompt与prefill。`scoring_prefix=\boxed{`在生成后与文本拼接用于评分，不计作模型新生成token。完整元组测试只证实生成接口不主动截断，离线解析器能否正确评分属于另一组grader测试。

所有批调用不传先前请求cache。批物理输入包含左padding、以及某行EOS后直到整批结束的计算；逻辑token按各行EOS裁剪。batch wall是整批时间，不能直接作为两个独立的单请求延迟或重复累加。uncached margin检查的额外验证forward属于CPU验收，不混入被测函数保存的生成ledger。

真实4B/SDPA/FP16数值、长上下文显存与全队列完成率尚需实测。若`paired_readout.py`源码变动，此次SHA绑定不能直接沿用。
