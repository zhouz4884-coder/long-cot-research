# D1原生worker启动前只读审查

2026-11-06。**未发现阻止本次8题原生接口诊断的剩余静态问题。** 这是源码/CPU准入，不是4B/CUDA续写等价、数学正确率或修复收益已经通过。

绑定：`native_worker.py` SHA `3f5b9644b86b49d429b33f0c89006ebc10eddae8c7b6235eb49853a66df23b82`；`native_engine.py` SHA `064f31fc1af93bd2d10a17244de30cd062a9bbd6ec8e188e7ee195c0440fd5c2`。CPU证据为[D1_CPU_INTERFACE.json](D1_CPU_INTERFACE.json)的58项，与该engine匹配。

- worker启动前核冻结文件、显式CUDA UUID/空compute进程、TF4.55.2/Torch2.8.0、模型资产`37ff9857…`、FP16/SDPA。只从visible取question，逐题重建thinking token IDs并与预渲染记录核对；已补两列表均8、ID唯一，防止zip静默截短。
- True模板可以只到assistant header，由模型先生成open；不能硬要求prompt已有`<think>`。engine核True/False不同及assistant未预闭合；cp必须在线已观察open、尚未close，并只取首次64token后可见段落边界。不是新User引用历史。
- 每题fresh Engine、`seed=20261106+index`的独立Generator，worker用inference_mode包run。采样是0.6/.95/topk20/minp0；CPU已与相同seed的HF采样helper对齐，不能替代真实GPU多种子质量评估。
- 主生成继续至实际EOS或模型context技术边界，不设384/512紧质量预算。32token只为检查点hot/cold诊断，按剩余context夹取实际长度，单列requested/actual，不截断主生成。
- diagnose复制cache/恢复独立RNG，保留原KV指纹，记录hot/cold/repeated logits、top1、top2 margin与采样差别。结构/数值PASS和strict replay PASS分开；strict还要求top1/采样续写匹配。数值容差内分叉仍应报告，不换seed挽救。
- 没有读取evaluation-only、没有Gold选择cp/动作、没有crop、bridge、作用域G、回退或修复。因此任何8题答案分数仅作native基线记录，不能声称SCOPE-Rebase有效。

本审查未运行远程、GPU或读取GSM8K选样答案，未修改worker/engine。真实tokenizer与native后续输出由主任务另行冻结/验收；CPU fixture只覆盖接口。提供包允许think闭合标签、pad0被`or`替换等缺口已在CPU说明披露，不把其参考API直接当安全生产接口。
