# Phase5-D第一批实际状态

2026-11-06。**D0、必要CPU核验、D1和同调度定位控制完整完成；不是D2–D5或算法性能验证完成。**

- D0：256旧文本、1024固定选择；原thinking LastBox28/32，28项均匹配Gold，非Oracle上界；旧主分不改。
- CPU：提供示例5/5复跑；加固证据内核30单测＋600独立闭包对照；native接口58项通过。
- D1：8新GSM8K接口题、8cp、8自然EOS、0context cap；15035主生成tokens，1077–3498/题，无紧token上限。
- 原bulk-reprefill联合数值准入6/8，next-top1/32采样/主流未来均8/8；原数值失败保留。
- 同调度重放控制8/8记录logits差0、KV指纹和32token匹配；仅准入该正确性参考，未准入fast crop/旧后缀KV。
- 原生Continue最终响应8/8仅基线描述，**没有修复动作或算法准确率增益**。
- 合计18.897161单卡分钟，D0为零新增GPU；GPU全部退出。

首先阅读[完整收尾](STAGE1_CLOSEOUT_ZH.md)。方法/公平性见[规格](METHOD_SPEC_AND_INNOVATION_ZH.md)、[新题即时生成与大规模验证](FAIRNESS_AND_FRESH_VALIDATION_ZH.md)。下一步[先测自然覆盖再集成修复](NEXT_DECISION_ZH.md)。
