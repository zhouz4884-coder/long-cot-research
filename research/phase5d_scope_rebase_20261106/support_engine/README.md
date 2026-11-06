# Phase5-D CPU支持内核

先读[实现审查与边界](IMPLEMENTATION_AUDIT_ZH.md)。

- [实现](scope_rebase_hardened.py)：scope/version、规则许可、可重放证书、AND/OR最小支持、两类挑战、文本退役与规范bridge。
- [通用测试](test_support_engine.py)、[最终CPU证据](CPU_SUPPORT_CHECKS.json)：30/30测试＋200图×3状态的600独立agenda比较通过。
- [原参考缺口复现](UPSTREAM_GAPS_REPRODUCED.json)、[复现源码](reproduce_upstream_gaps.py)：保留原zip不改。

`trust_given`/`trust_constraint`只能接调用方已认证的原题来源，不接LLM提案。算术相等若无规则许可也只是UNKNOWN；`check_arithmetic_invalidation`只否定具体坏论证，不自动否定其结论；`check_claim_refutation`有独立约束反证才是另一种操作。`issue_withdrawal`只模拟可信来源生命周期，不是自然核验器。

本模块CPU only。没有自然图提取、完整G、原生KV操作或模型质量成绩。证明/支持维护不是新发明，模型增量仍须后续真实实验验证。
