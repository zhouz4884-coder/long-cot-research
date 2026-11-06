# Phase5 quality runner：只读独立源码与CPU证据审查

2026-11-06。**对下列绑定版本，静态输入/停止/计账审查通过，未发现阻止一次已计划短跑的剩余源码问题。** 这是执行接口准入，不是GPU质量结果、统计功效或VersionFrame收益证明。本审查没有改runner/adapter/原输入，没有运行GPU、远程、训练或重新执行torch模型。

## 1. 审查绑定

| 对象 | SHA256 / digest |
|---|---|
| `phase5_quality_runner.py` | `0eab8a3a62381db7f56c9cf9101647703cb8e1208d9f3c38e25eec59fafcd2f9` |
| `prepare_cpu_input_adapter.py` | `3556baa0920b344e87f22037c584f7d2bde77bbdede9808c4e360fc00200890f` |
| prepared dataset | `5260ad988fd9dfe97c186ad9fb7970c7a8cc91540de86f6be59c3de26c6b723b` |
| topology-v2原输入 | `93f39936cb5d1dbdbc1eb647d1c0f228be11cf49f23d14b7b2163b52d01902d1` |
| frozen P0 helper | `246219aee9774fae0966c7663c765daf3dba2f1df68bc054b539a4dd5d64331b` |
| frozen final-answer parser | `c2bc053b66778288f524d46f4353e825b1ee654d829027bd02b1cb3173255eed` |
| **真实运行要求**的Qwen3-4B model manifest | `37ff9857bb53edf35d5c80bfa0c078b1cdb8d5e5aa864115d153e237cb854511` |

接受的CPU证据目录为`tiny_quality_cpu_4552_final/`，其manifest与当前源码/3556 adapter/5260 dataset一致，`CPU_QUALITY_RUNNER_ACCEPTANCE.json`为19/19通过。另有旧/其他CPU目录；尤其名为`tiny_quality_cpu_4552_release/`的manifest记录不同runner SHA `d065...`，**未用作此0eab版本的验收证据**。后续若选择不同runner SHA，应重新对应该版本的证据，不能混合目录名称判断。

## 2. 模型输入与工具权限

已读取完整runner，并独立读取final目录的`rendered_jobs.json`、`prepared_dataset.json`及18份请求记录：

- 实际模型输入来自`adapter.render_prompt(item, method)["messages"]`，再经已记录的nonthinking chat template编码。每请求重新编译后与预先冻结的messages/IDs比较；没有将整个item、provenance或`hidden_evaluation`序列化给模型。
- 每个主请求实际重新调用`build_controller(item["visible"])`，核digest等于prepared controller并记CPU耗时。函数输入只有可见question/旧clauses/R，原题AST只求常量根x/r；记录的`derived_arithmetic_evaluations`均0。group/最终金标没有选择动作、方法或输出。
- 四方法同一case的`shared_evidence_sha256`一致。核验根值、原始规则、依赖图、旧记录和R共同可见；Compact/Stepwise可复用已认证根，不被强制重新计算它们。VersionFrame的额外内容是由这些事实构成的one-shot工作帧，不是额外数值答案或完整运行时checker。
- 所有旧派生y/z的认证状态仍为UNVERIFIED；无dirty不代表已认证。runner不根据模型自报给节点认证，也不确定性提交旧z；`grade`中的正确性只在生成结束后计算。
- 真实分支强制显式单GPU UUID，并由frozen helper检查唯一可见标识及启动时compute进程；所有路径要求Transformers4.55.2，真实Torch限定2.8.0/2.4.1、FP16/eager并核model manifest。该绑定不是调度器排他锁或持续NVML监控。

独立检查的18条CPU prompt中没有`required_final_value/hidden_evaluation/oracle_values/evaluator_only/independent_conclusion`字段；共享根值与原有旧clause中可能出现正确数值是预定输入事实，不能用“任一正确数字出现”替代字段/来源泄漏检查。

## 3. Basis与固定执行顺序

真实计划顺序是6个basis先行，再按`T1E,T2E,T1C,T2C,T1W,T2W`各运行4方法，共30输出。旧16未被此dataset加载/混入。

- Basis有2个唯一P-only、4个按**可见(P,R)完整字符串**去重的P-plus-R。T1/T2各E与C共享同一PR；W分别保留真实的错误R，并映射至另外两条PR。
- Basis只含P或P+实际R，不含G、B或VERIFIED_ROOT事实；不能称W的R为correct-R，也不能把basis当成与四方法同权限的算法胜负比较。
- `dedupe_map`、basis IDs和linked case IDs留在metadata，已核model prompt不含这些关联标签。没有按模型答对/答错再去重或重跑。
- CPU fixture只选T1E/C/W三个主case，每例4方法，加完整6个basis，共18输出；真实冻结选择仍为6个主case×4+6，而非把CPU fixture覆盖误写成30次真实模型验收。

## 4. 停止、缓存与Gold隔离

`natural_greedy`手动argmax解码，仅遇configured EOS或安全cap结束；真实cap512，CPU fixture cap8。未调用原base中带整数换行停机的`greedy`，未用parser/正确答案/候选概率提前停止，也无尾窗、强制y前缀、teacher-forced评分或辅助probe。总worker watchdog最多270s，开始新请求前还检查剩余时间；外层≤300s预算仍由主任务launcher落实。

独立mock控制与随机tiny结果明确分开：

| 控制 | 结果 |
|---|---|
| `123\n`后仍继续到EOS | token ID为`[7,8,9,10,4]`，5个输出token，4次续传，无整数换行早停 |
| EOS后不再forward | 记录次数与上述4次相符 |
| 无EOS时到安全cap | 3个输出token，`hit_safety_cap=true`、`eos_reached=false` |
| 原checkpoint不被append污染 | mock及random tiny均保持原cache长度；tiny首请求还逐tensor核对原cache最大差0 |

每请求重新完整prefill，无跨方法复用可变decode cache。续写对prefill cache深拷贝，显式位置连续，runner拒绝任意0 key mask。每个forward检查finite logits。模型生成内容从未进入后续方法输入；Gold只在结束后交给固定parser数值比较，不作在线checker或重试条件。

随机tiny本身18条均命中8-token cap、未EOS、未解析；它**没有动态覆盖EOS分支**，因此EOS/newline覆盖只归于单独的确定性mock。不能用这些随机输出判数学能力或方法收益。

## 5. 完成状态与计账的正确读法

源码在请求开始即保存IN_PROGRESS记录及case/summary；每32 token保存partial片段。完整四方法case才进入主比较分母，按all与E/C/W分别统计；完整case中的cap、unparsed或答错不再被过滤。已完成的独立方法/basis原始记录保留，即使该case整体未完成。

- `numeric_correct`是生成结束/安全cap后对固定parser结果的数值比较。
- `eos_and_correct`还要求EOS正常结束；不能用前者替换它，或把hit-cap当作正常EOS。
- 遇global deadline必须结合`deadline.json`、外层exit/timeout及单请求partial记录解释；旧summary可能只是最近一次已保存快照，`QUALITY_RUNNING`不表示完成。无法启动/未完成的方法不补齐、不替换简单case。
- 被中断的token片段每32 token保存一次，可能少于实际已做工作；ledger只含完成并同步过的forward。预算应以外层完整墙钟/单卡占用为保守总额，而非只数保存token或已完成case。

成本字段包含嵌套关系，不能相加重复收费或把未列分项漏掉：

| 字段 | 覆盖关系 |
|---|---|
| 全局elapsed/launcher墙钟 | 包含imports、一次shared preparation、hash/load、预编译、所有请求、控制、评分/记录开销；launcher覆盖进程完整生命周期 |
| `request_seconds_before_posthoc_grader` | 从每请求G开始到生成结束的内层耗时，已包含G、prompt编译/tokenize、prefill、decode；不应再加这些子项 |
| `G_cpu_seconds` / compile / prefill / generation | 请求的分项；用于拆解，不是请求外的新成本 |
| `actual_forward_cost`与ledger | 同步forward子集，处于prefill/decode/request内部；不是可另加一次的总额 |
| shared preparation / model hash-load | 全局启动分项；per-request G重算是真实额外执行，但也已进入各请求与全局时间 |

独立重数final CPU证据得到145次模型forward、4,287输入token，与summary一致；其中18条请求每条prefill+7次续传共144，另一次same-prompt replay。确定性EOS mock使用独立mock runner，不混入模型ledger。CPU inner-request合计约0.5816s、全局约5.4737s，不能把两者/其forward子项重复相加，也不能用CPU时间预测CUDA的30条512-token质量轮能全部完成。

## 6. 准入范围

本次确认源、输入、adapter与CPU验收一一对应；纯消息投影、root-only G、旧派生未认证、正常EOS策略、分支cache及统计分母均符合当前协议。静态检查加CPU smoke不覆盖真实GPU/FP16数值稳定性、整轮超时故障注入或模型质量；这些不能提前标PASS。

可以冻结**本报告绑定的0eab源码**后由主任务执行已授权的一次小轮；没有尾窗、没有多预算扫描。无论结果如何，交付全部raw输出、E/C/W、EOS/cap/unknown、完整/partial及总成本，不将与旧P0/P0.5的跨协议分数变化算作算法提升。
