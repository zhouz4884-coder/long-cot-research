# D1同前缀执行调度控制的只读审计

2026-11-06。**完整性审计PASS，178项通过。** 原D1的联合数值门槛6/8原样保留；原下一top1/采样32/实际未来均8/8一致，也未改写。

新控制覆盖原8个相同checkpoint：记录的hot-vs-调度匹配replay logits最大差均0，完整KV指纹比较flag均true；8份实际32-token列表与原hot及已生成的主流未来逐项相同。重放是原prompt同chunk后逐token teacher-force已观察前缀，再恢复原checkpoint RNG；不是重新采原整道题、不是改seed/阈值、不是新修复动作。

逐条prefixSHA/长度、原生ID拼接、控制源/协议冻结、原D1取回hash及控制取回hash均相符；8个checkpoint只算8道原题。控制worker summary与各个case文件一致，ledger精确对应1053次forward、1570输入tokens；新生成仅诊断256 tokens。控制2.224414单卡分钟，native＋control共18.897161，不把两卡并行的wall和单卡分钟混同。

## 证据必须分层

- **可独立重数/逐项比较：** 所有文件SHA、8个原prefix、32-token实际列表、teacher-forcing调度/位置与forward台账、worker分母及GPU秒相加。
- **绑定源码的执行记录：** 新控制没有保存完整replay logit数组或KV张量/after指纹，因此不能声称本审计再次做tensor相减得到0，或再次rehash全部KV。它核对的是源代码明确实施这些比较、固定源哈希、标量/布尔记录及原NPZ/指纹的引用关系。
- 原D1 bulk cold的两项超预注册数值阈值仍是失败；本新控制支持“bulk与stream调度有关”的解释，不把原门槛改成8/8，也不证明FP16是唯一因素。并未观察实际token分叉。

主任务独立CPU评分记录为**native Continue 8/8**；本审计只核总数与scope，未读Gold/重新判数学答案。8/8不是SCOPE-Rebase收益，因为根本没有执行repair、bridge、crop或G；诊断分支也不增加独立质量样本数。

控制prelaunch只显式绑定控制源/协议，未列尽前一D1的每个result/cp/NPZ；本次依据原取回hash重新核它们未变，并以prefix身份及源码读取关系绑定，不把事后核对夸成事前全部输入独立冻结。

证据：[D1_SCHEDULE_CONTROL_AUDIT.json](D1_SCHEDULE_CONTROL_AUDIT.json)、[原D1审计](D1_NATIVE_AUDIT_ZH.md)、`schedule_control/`、`SCHEDULE_RETRIEVAL_MANIFEST.json`、`schedule_control_freeze.json`。本报告无模型、GPU、远程或新数学评分运行。
