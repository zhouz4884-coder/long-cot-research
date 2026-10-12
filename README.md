# 自然推理步骤的干预价值测量

本项目执行[分享聊天中的研究计划](https://chatgpt.com/share/6ac7ac26-c6a8-83ec-be63-d018140ce23e)。目标是测量继续一个自然推理步骤的净收益，随后检验其可预测性和真实在线价值。

**最终综合报告写入 `docs/REPORT_ZH.md`；执行过程记录见 `docs/WORKLOG_20261011.md` 和 `docs/WORKLOG_20261012.md`。代码存在、编译通过或 CPU 检查通过均不表示 GPU 实验完成。**

## 冻结输入

- 上游 llm-think-stop：`21efe411bcaf34de884c1120ab7fb0573c193a62`，不修改源码。
- EAT 参考实现：`93a46f7a8b3d401511389e8a10dc117aa7f9c287`。
- Qwen3-4B revision：`1cfa9a7208912126459214e8b04321603b3df60c`。
- MATH-500 revision：`6e4ed1a2a79af7d8630a6b768ec859cb5af4d3be`。
- 题目划分：150 development / 50 engineering / 300 test；见 `data/split_manifest.json`。

主实验计划使用 FP16、T=0.6、top_p=0.95、top_k=20。原版 BF16 greedy 复现独立记录。所有主方法共享短答案协议：强制结束思考后输出一个完整 boxed 答案。

## 执行入口

远程目录为 `/media/user/5bc0dc8d-c938-4b2a-af1b-94174fc511a9/projects/reason-transition-20261008`，隔离环境为该目录的 `.venv`。SSH 认证工具在本机被 gitignore 的 `.tools` 中，凭据不进入仓库。

```bash
python scripts/build_splits.py
python -m unittest discover -s tests -v
python scripts/validate_protocol.py --model /path/to/Qwen3-4B --n 24
python scripts/validate_cache_clone.py
# 正确性和原版 P0 完成后，按依赖执行；pilot review 由执行者实际检查 50 个答案。
python scripts/run_pipeline.py
# 以下是另外两个独立进程，按等待依赖运行；主管线不会自动启动它们。
python scripts/run_holdout_remainder.py
python scripts/finalize_execution.py
# 对已完整保存的原始结果重新统计：
python scripts/final_stats.py
```

`run_pipeline.py` 规划的顺序是 24 题分支 pilot、150 题开发、补齐 50 题工程集、Grouped CV、工程集校准、重复采样控制、50 题独立在线测试及第二模型 24 题检查。它必须实际部署和运行才会推进；不能把这个入口文件当成已执行的研究。

主模型四种方法的最终 300 题由 `run_holdout_remainder.py` 补齐；其余控制和消融各 50 题，第二模型两种方法各 24 题，共 1648 条在线记录。输入冻结、实际命令、人工核验和分析复现的详细依赖见 [复现说明](docs/REPRODUCIBILITY_ZH.md)。

主采集器是 `scripts/collect_bank.py`：同一真实父 KV 深拷贝到 STOP/STEP，FULL 为未干预的父轨迹；离线分支开销单独记录。早期 `generate_traces.py` 和 `branch_at_checkpoint.py` 是独立重放辅助代码，不是主采集路径，不应和主数据混跑。

`evaluate_online.py` 在生成期间执行策略，评分仅在结束后进行。统计以题目配对，既报告 bootstrap，也报告精确有害反转风险上界。50 题经验改善不能直接变成 1pp 非劣性声明。

详细协议、基线审计、数值诊断、答案协议和候选创新均在 `docs/`。当前没有已经证实的论文级性能或新颖性结论。
