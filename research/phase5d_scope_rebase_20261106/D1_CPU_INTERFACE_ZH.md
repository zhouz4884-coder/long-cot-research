# D1原生执行器CPU接口验收

2026-11-06。**58/58检查通过；仅准入真实GPU接口诊断，不是Qwen3-4B数学质量或SCOPE-Rebase收益。** 没有读取native_visible、native_eval或任何真实选样答案，没有远程/GPU操作，没有修改engine或原提供包。

## 绑定与复跑

- `native_engine.py`：`064f31fc1af93bd2d10a17244de30cd062a9bbd6ec8e188e7ee195c0440fd5c2`。
- `test_native_engine.py`：`92a4511b1b37dce36b8e8f1285f255101ce9d46af34648669a24ea1a7bb322a8`。
- 环境：本机Torch2.11.0+cpu，隔离runtime4552的Transformers4.55.2；随机3层tiny Qwen3、FP32/SDPA、96词表，结构fixture tokenizer，不是真实Qwen tokenizer。
- 机器证据：[D1_CPU_INTERFACE.json](D1_CPU_INTERFACE.json)。复跑：`python -X utf8 research/phase5d_scope_rebase_20261106/test_native_engine.py`。

## 实际覆盖

| 检查 | 实际结果与边界 |
|---|---|
| thinking真/假模板 | 两种ID不同，True允许assistant header后尚未产生open；模型实际生成`<think>`后才允许cp。忽略开关或预闭合的模拟模板被拒 |
| 同token前缀 | 310-token随机prefix的逐token/full logits最大差`5.96e-8`；chunk256/full为`2.98e-8`，top1一致；只属FP32 tiny |
| 采样策略 | 同prefix与同seed，手动0.6/.95/topk20/minp0的16 token与HF.generate逐项相同；没有用greedy充当质量 |
| RNG与分支 | local Generator恢复可重复，另一分支不改变原RNG/global RNG；复制分支不修改原KV指纹 |
| diagnose真实tiny | hot/cold采样相同，cold重复prefill差0，原cache未变；非真实4B/CUDA等价证据 |
| 在线cp与未来隔离 | 脚本mock首个已观察段尾在64token；prefix只含当时已观察IDs；改变未来不改变cp时间/前缀 |
| EOS/闭合 | mock覆盖正常EOS、早闭合、think未闭合到context cap、尚在think却EOS；未闭合thinking不冒充final response |
| 32token诊断窗 | mock原生继续74token正常EOS，证明32只是诊断窗；近context尾cp把requested32夹至actual2，正常返回技术cap而不越界 |
| strict与numeric判据 | 注入top1或采样不一致时，numeric项仍可通过，但strict replay必须失败，不隐藏分叉 |

随机tiny的采样/数值控制与脚本mock分开记录；mock只验证执行状态与分支，不模拟真实语言模型的数学能力。真实tokenizer结构、4B FP16/CUDA精度、实际context长度、采样稳定性及自然EOS需D1 GPU单列。

## 提供包的两项缺口与测试wrapper

原`append_in_thought_bridge`会接受`</think>`，可提前关闭思考；原continue示例用`pad_token_id or eos`，会把合法pad ID0替换为EOS。这两项在测试中被**明确演示为原样例缺口**，并不表示原示例安全通过。

本测试另设局部结构wrapper，拒绝think/角色/结束标签及其token IDs、要求完整步骤且当前think未闭合，保留原前缀ID不变。它只存在于测试中，不是生产bridge API，也不认证桥中数学内容。上游包按字节未改；当前engine本轮没有实现认证桥/回退算法。

## 代码审查促成的主任务修正

测试准备时向主任务指出：worker必须使用inference_mode；模板可能True时无预填open，不能硬要求已有open；strict PASS不能只看数值容差；诊断窗须按剩余context夹取。主任务在engine中完成对应修正，本报告绑定其最终版本。

若真实FP16同ID冷/热回放出现小数值差但cold/cold稳定，应记录top2 margin、采样分叉与容差，不能直接归为算法状态修复或用换seed刷PASS。strict replay与结构/数值准入分开，且本58项不代替任何GPU验证。
