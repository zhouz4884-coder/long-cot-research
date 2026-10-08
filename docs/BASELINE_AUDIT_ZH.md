# 原版 llm-think-stop 审核

冻结 commit：21efe411bcaf34de884c1120ab7fb0573c193a62。原文件不修改，实验中清晰区分原版复现与独立修正版。

1. `reason_budget_probe.py` 的 full 和 budget 分支都 `sample=False`，实际为 greedy；`--seed` 仅控制题目选择，没有设置 torch 采样种子。不能视为官方 Qwen3 Thinking 配置结果。
2. `batch_decode(..., skip_special_tokens=True)` 后再找 `</think>` 存在跨 tokenizer 的条件性风险。本次已用冻结 Qwen3-4B tokenizer 验证：该标记在 skip_special_tokens=True 时仍被保留，因此此项没有在本模型触发，不能写成已确认的本次代码 bug。
3. `extract_answer` 只提取第一个 `boxed`，正则遇嵌套花括号会截断 `\\frac{1}{2}`；无 boxed 时取末尾数字，对分数、集合、区间、根式不可靠。后续采用 Math-Verify，并单独保留解析失败。
4. 预算通过 decode→re-encode 构造前缀，不能保证与生成 token IDs 一致。新实验保留原 token IDs；显式记录 prefix_hash。
5. token 成本主要为 min(full_think_len,budget)，未计答案、探测、反复前缀 prefill、真实 wall-clock。原版 stability-stop 是事后选择结果，不能直接称在线延迟收益。
6. full 预算为 max_think+ans_tokens，没有严格保证思考 <=max_think；触顶轨迹也可能从推理文本抽取答案。修正版单独标记思考上限、答案上限与自然终止。
7. `prepare_reason.py` 输出没有 unique_id、subject、level；没有冻结远程数据 revision。独立数据层保留这些字段并冻结分层切分。

已核对 [Qwen3 官方说明](https://huggingface.co/Qwen/Qwen3-4B)：推荐 Thinking T=0.6/top_p=0.95/top_k=20，明确不建议 greedy。原版结果仅为该代码协议下的 smoke，不升级为研究结论。
