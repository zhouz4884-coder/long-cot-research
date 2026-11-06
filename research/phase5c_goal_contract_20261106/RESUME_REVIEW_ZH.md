# Phase5-C：用户延长时间后的只补缺失流程审查

2026-11-06。**静态审查与合成planner契约通过，无剩余静态阻塞。** 未运行远程/模型/GPU，未读取真实输出质量或Gold，未改原wave、原runner和原协议。

## 绑定

| 对象 | SHA256 |
|---|---|
| 原`paired_readout.py` | `e08273ce10805173a693672484490b3821af6d34d987617a8055eb6647bf7ac5` |
| `resume_planner.py` | `c42a8a467dc45d8ae5b8f39ebc84aaacc94ec228079cfd7357bafff25a7a17f3` |
| `resume_worker.py` | `4503da72e3778dfe5a5a0b09d976a2327af7b567093fc26516f380275e291b30` |
| `resume_launcher.py` | `a8ba228d0566549b11a7704fb22996661af6a3ea467cd008a93fe7b14542594b` |
| `CPU_RESUME_PLANNER.json` | `c967d8079175a8dd534e24fa058aa12132f4fdf0d8433bd9092827ca767c8fb4` |

## 核对结论

- 用户明确撤销原30GPUmin限制，旧protocol/freeze保留，新resume freeze与预算修订单列。原wave必须FINISHED才可继续，两张GPU仍按原UUID及rank奇偶划分；不覆盖已有目录/文件。7500秒timeout是续接进程保护，不是恢复旧30分钟停止线。
- planner只看存在性与字段，不看成绩。已存空答案EOS、触顶或答错结果均保留；拒重复/未知/另一worker以及ID、rank、方法、bank ID、prompt长度、合同/packet指纹和评分prefix不一致。33/33合成控制包括上述异常、输入不变与grade/Gold毒化不影响计划。
- 完整原pair跳过；部分pair仍按原pair全部输入重算，只写缺失行，已有行的新答案存`discarded_recomputations.json`而不取代旧答案。discard仍保留在完整batch ledger计费，不能作为第二次答题挑最好。
- worker直接调用原`compile_jobs`/`generate_batch`函数，不复制或修改生成算法；相同jobs/token IDs、seed20261106、384保护、FP16/SDPA与已冻结4B资产。没有因为旧输出好坏改提示、样本、核验或解码参数。
- 已补batch_id及summary前written唯一集合精确等于planned_missing断言；无缺失时直接结束，避免无意义模型加载。launcher最终必须看到224个唯一预期job且两resume exit0才写STUDY_STATUS=FINISHED，否则INCOMPLETE。

以上证明的是续接控制/接口路径与原生成函数一致，不保证GPU数值逐次相同或任务质量。真实完成后仍须核原始wave下载SHA、两wave合并去重、planned224/actual224、各批物理计数（包含discard）、EOS/cap及原+续两wave全部外层GPU秒。不得将新预算授权解释为旧协议早已完成，也不能以等待/启动当完整结果。
