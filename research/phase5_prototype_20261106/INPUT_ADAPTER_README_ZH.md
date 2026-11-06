# Phase5确定性CPU输入adapter

本轮仅准备输入；无模型、tokenizer、GPU、远程、训练或Gold模型评分。`cpu_adapter_checks.json`为209/209接口/权限边界检查通过，不是神经模型质量结果。

当前实际小轮选择新v2的6个before-fault状态，顺序固定：T1E、T2E、T1C、T2C、T1W、T2W。它们是2个程序的配对toy状态，不是6道独立自然问题。四方法共24主输出；另2个unique P-only、4个精确去重的(P,R)共6个basis，总计30输出。旧16只作独立开发/校验，不加入此轮。

## Runner接口

模块：`prepare_cpu_input_adapter.py`，纯标准库。

```python
data = adapter.prepare_dataset(path_to_P05_topology_cases_v2_json)
main_item = data["cases"][0]
request = adapter.render_prompt(main_item, "SharedGStepwise")
messages = request["messages"]  # 唯一发送给模型的内容

basis_request = adapter.render_prompt(data["basis"][0], None)
same_controller = adapter.build_controller(main_item["visible"])
assert same_controller == main_item["controller"]
```

`prepare_dataset`返回`cases/basis/dedupe_map/hash/source_sha256/adapter_source_sha256`及固定顺序/计数；主item含`case_id/visible/controller/shared_evidence/model_inputs/hidden_evaluation`。basis含`basis_id/kind/messages/provenance/hidden_evaluation`；`kind`为`P_only`或`P_plus_R`。`render_prompt`始终返回`dict{messages,provenance}`，不能把整个item或provenance/evaluation序列化给模型。

CPUfixture词表可汇集所有`render_prompt(...)["messages"][*]["content"]`字符。main的`visible`三类原字段是question、old_assignment_clauses、revision；不读取hidden_evaluation建立动作。

## 共享权限与能力边界

- 原题规则从可见question解析，AST仅对常量根x及独立r求值。新v2的隐藏definitions只做构建后的CPU一致性比较，不参与动作或prompt。
- G输出accepted/rejected/nochange/unknown，只看原题根约束、旧根字面值与R的最后明确x字面赋值。Wait、E/C/W、最终金标不控制动作。
- 每种方法收到相同question、旧clause、R、规则、graph、G及已核验父值；Compact与Stepwise可复用这些值，不被要求从头重算。Stepwise可自定合理子问题/复合计算。
- 旧y/z无论是否恰等于gold，均为UNVERIFIED，未记录的依赖版本为UNATTESTED；改变根后才额外dirty标记。C/W无dirty不等于旧z已认证，goal支持仍需处理。
- VersionFrame的版本/dirty/goal未认证支持/ready计划是由同一可见事实推导的one-shot工作帧。它没有运行时模型输出验收器、没有给新y/z数字、没有确定性提交旧z。独立r的算术认证不等于KV认证。
- Basis只有P或P+实际R，没有G、B、已核验根值；W的R按原文保留，不能称correct-R。E/C共享的(P,R)只运行一次，通过dedupe_map关联状态。

## 文件

`model_inputs_selected6_draft.json`是当前30请求设计的完整数据草稿；`normalized_cases_all28.json`用于schema/CPU审查。`model_inputs_development16_draft.json`仅开发；旧名`model_inputs_initial12_draft.json`已在内部标为`SUPERSEDED_SELECTION_DESIGN_POOL_ONLY`，仅保留完整v2设计池，不是此次选择。

质量优先draft为greedy、`max_new_tokens=512`和正常EOS，无强制y前缀/人工尾窗。字符数已记，真实token数/时间/输出尚未知。共享数学信息不等于prompt长度相同；成本/预算曲线是后续独立轮次，不能在此宣布省时或胜出。
