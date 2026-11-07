# D2自然覆盖审计

本次状态为 COMPLETE。完整性检查通过。

24问题、48种子轨迹的计划分母保留。已完成轨迹、事件、关系和可执行字面检查分列。

```json
{
  "planned_problems": 24,
  "planned_seeded_trajectories": 48,
  "completed_trajectories": 48,
  "missing_trajectories": 0,
  "observed_problem_ids": 24,
  "complete_steps": 5282,
  "event_steps": 3150,
  "trajectories_with_events": 48,
  "trajectories_with_parsed_relation": 23,
  "trajectories_with_literal_checkable_relation": 23,
  "trajectories_with_scope_bound_symbolic_relation": 0,
  "trajectories_with_decisive_relation": 23,
  "trajectories_with_live_decisive_relation": 23,
  "extracted_relations": 460,
  "literal_checkable_relations": 167,
  "scope_bound_symbolic_relations": 0,
  "decisive_relations": 167,
  "decisive_literal_relations": 167,
  "invalid_literal_relations": 9,
  "lexical_invalid_actionable_candidates": 9,
  "role_certified_actionable_errors": 0,
  "rebase_eligible_events": 0,
  "eligible_pair_candidates": 868,
  "selected_distinct_problem_ids": 4,
  "EOS": 48,
  "context_cap": 0,
  "generated_tokens": 248456,
  "forward_calls": 248456,
  "forward_input_tokens": 252224
}
```

字面关系的真/假不自动认证其在推导中的作用。所有role_certified保持false，正式修复需要两份独立前缀审查。

源码解码复核为 PASS。配对执行前需真实tokenizer验证完整段落。

收集未全部完成时只报部分覆盖，最终配对选择为空。选择完成后按冻结优先层和字典序，每问题最多一事件。

逐关系见COVERAGE_RELATIONS.jsonl，所有排除见COVERAGE_AUDIT.json，配对输入见PAIR_SELECTION.json。
