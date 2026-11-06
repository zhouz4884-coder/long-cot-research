# 目标提示与候选摘录：CPU交付

2026-11-06。实现为 `goal_evidence.py`，检查脚本为 `check_goal_evidence.py`。最终纯CPU检查 **46/46通过**；没有读取历史bank、评估文件或Gold，没有运行模型、GPU或远程任务。

**这是可自动运行的启发式候选摘录原型，不是完整GC-PBP，不具备真值G或已认证自然父边界。** 名称不能作为创新证据；模型实测、类型识别覆盖及质量/成本由主任务另报。

## 稳定接口

```python
contract = derive_contract(question)
packet = build_evidence_packet(question, trace, max_chars=1800, max_spans=8)
cheap = last_tail_packet(trace, max_chars=1800)
contract_text = render_contract(contract)
same_evidence_text = render_evidence(packet)
```

输入只接受两个字符串。调用方必须只投影question/trace字段；把整个包含评价的字典传入会抛TypeError，模块不读文件、不接受Gold参数。默认字符/跨度预算不是模型token预算，应另用实际tokenizer计量。

## 实际作用与边界

- 目标提示只从question最后一个可识别请求子句取原文，并保留原始offset；图示Asymptote代码不被认作较晚目标。识别计数、有序对象、向量、概率，其余标unknown。答案类型是**软提示**，不证实终局映射；原题必须对所有方法共同可见。
- “有多少有序对”归计数，而非输出有序对；概率0/1合法，分数和等价小数均可，百分数按题意尺度。没有数值/父节点黑名单，也不求解目标。
- 证据由完整boxed表面、答案/结论词、等号和目标词重合评分；为早期和末期答案候选段预留优先级，再取高分段。保留精确原文、字符offset和选择理由，至多1800个引用字符、8段。长段只引用局部窗口，可能遗漏必需前提。
- boxed内支持嵌套大括号；不完整boxed不升级为完整候选。`1/2`与`0.5`等表面差异只记不同表面数量，**不宣称数学冲突，更不判谁正确**。所有引用状态均UNVERIFIED、`semantic_conflict_verdict=UNKNOWN`、`certified_parent_boundary=false`。
- 没有足够候选信号时返回 `UNKNOWN_NO_CANDIDATE_FALLBACK_TAIL`，显式回退到固定尾部窗口；空轨迹返回空证据，不凭空补支持。Wait本身不触发接受、拒绝或真值仲裁。
- `G_status=NOT_IMPLEMENTED_NO_TRUTH_ARBITRATION`。不能把自动选出的候选称为“已核验支持”，不能声称消灭W错误或完成自然DAG提取。

## 公平对照接法

FullHistory+Contract+SameEvidence 与 Projected+Contract+SameEvidence 必须复用**同一个packet**及同样的渲染，不各自重新挑摘要；两臂的信息权限差异只应来自是否保留完整历史。廉价LastTail+Contract使用同样字符预算，作为无需目标词/候选排序的强基线。

原题P应对全部相关臂可见；不能仅给Ours更准确目标、人工选对的候选或额外真实答案。候选选择、render和模型prefill/生成成本都要记账。历史`<think>`或chat控制标签如何转义由主runner统一冻结，不能只改投影臂。

## CPU检查覆盖

46项包括：计数与有序对区分、三元组arity、向量/概率/unknown；概率0/1与百分尺度；源目标span；Asymptote不篡位；字符/段数上限与精确quote offset；早/晚候选保留；不同表面仍unknown；无G认证；空/无信号/仅Wait回退；嵌套/不完整boxed；廉价尾窗预算；隐藏评价字段污染不变；拒绝字典输入；相同packet确定性复用及渲染未认证措辞。

准备过程中先发现独立`Answer: ...`的正则结尾边界会漏匹配，以及无冠词“Find number of ...”的类型边界，均在任何真实题模型输出前用通用合成例修正。最终报告绑定：

`goal_evidence.py` SHA256 `9d86b95f423bcc4805574e4c1b1b91d0597b0fd14a1c4437b4c24460d28cd15f`。

这些是接口/规则控制，不是语义质量、证据完备性或模型收益验收。
