# ASAG受控独立适配合同

依据 [正式论文](https://proceedings.mlr.press/v306/li26ev.html) 的方法与附录算法。当前公开入口核查未定位可靠可执行作者源码，因此只称独立适配；后续发现正式源码需再对照，不从搜索无结果推出“作者永远没有代码”。论文报告数字不作为本研究结果。

保留四动作：STOP、INJECT、JUMP、CONTINUE。默认confidence .95、相对entropy变化−.1、最多一次jump。第一次ATP可按confidence停止；后续比较始终针对首个ATP的entropy。严格不等式边界保留；首entropy为0的首次confidence条件仍有效，后续除零情形明确继续。

测量侧保留主SDPA。只在辅助scratch前向临时观察最后四层，重建RoPE/GQA后的QK概率，使用实际布尔/加性mask；无mask时显式因果屏蔽。entropy按query/head/layer求和并除log(key数)，不是query均值；trap比较每个thought action的每token平均attention，不能拿总质量替代。窗口为实际reader提示与同长度recent thought。复制并裁剪cache后重算recent tail；这不是历史incremental query或SDPA内部矩阵的逐bit还原。所有开销计入请求。

原文/伪代码未唯一确定的实施选择须显式声明：观察到的Wait放入parent prefix；normalized answer vector用所有实际probe步的全词表概率均值，按.95/.05混合，在下一ATP之前影响sampling；采用共同FP16/SDPA/随机采样/boxed reader，非作者BF16/greedy；jump提示改写；最多一次jump按正文maximum解释，不照附录jump_count≤s造成两次。logical thought上限包括强制jump token；probe生成及输入成本另记。STOP直接提交刚支付的同一candidate，不重新抽答案。没有Gold进入这四动作。

实际online入口每题另执行同worker/物理GPU/seed的FULL，ID哈希预定两方法顺序。只有首次INJECT/JUMP之前的思考prefix要求一致；干预后的差异是策略的一部分，不能错误要求整条轨迹一致。两个Gold都在决策完成后才评分。计算生成量仅包括模型抽样、全部probe及新增final，复用candidate不重复计费；delivered另包括强制jump。以上不是Serving测量。

当前证据：随机权重四层小Qwen3真实CPU前向三例（past/window=0/7、5/7、20/1），eager概率最大误差2.09e-7；监测前后SDPA logits、结果KV、parent KV完全相同，hook移除。9个CPU方程/四动作/tape控制通过。首次零prefix时lazy DynamicCache越界，已按空层情况修复并保留失败。不是正式4B GPU验收、任务正确率或作者复现。

下一依赖：native结束/GPU空闲后 `validate_asag_gpu.py` 检查同模型实际128/8192/16384前缀的scratch重复、父KV、显存与512-token集成；所有长度由保存pilot按长度选，不看正确率。通过后 main formal再独立ASAG freeze，完整选择集实测。未通过则保留失败，先定位测量/数值/实现；不得把CPU控制当GPU效果。最终测试须独立ASAG final freeze且所有测试仍未生成。
