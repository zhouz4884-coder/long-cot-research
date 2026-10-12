# 复现与归档说明

最终原始 GPU 数据、固定输入、代码、依赖版本、策略文件和文件哈希一并归档。主结果要求 1648 条实际在线记录；缺少任何预期模型、方法或题目时，最终统计程序必须退出，不能自动降为部分结果。

## 用最终原始结果重新计算

在归档根目录操作，使用 `requirements-experiment.txt` 中的版本。PyTorch 的 CUDA wheel 需要官方 cu128 索引；实际运行环境另保存在环境日志中。不要把在其他环境中重新生成的模型输出混入本轮结果。

```bash
python scripts/validate_study_artifacts.py
python scripts/audit_bank.py
python scripts/analyze_controls.py
python scripts/final_stats.py
python scripts/export_online_cases.py
python scripts/plot_research_results.py
python scripts/write_final_report.py
```

这是对保存的实际输出进行判分、统计和绘图的复现，不是重新执行 GPU 生成，也不能据此证明另一台服务器的延迟相同。统计以题目配对，主四方法为共同 300 题；额外控制与消融使用共同的前 50 题；第二模型为共同的 24 题。图不能把不同题目集合的总体均值当成同一条质量—成本曲线。

## 在两张 GPU 上重新生成

使用新实验目录，保留本轮冻结结果。必要模型文件按 `provenance/` 的 revision 和哈希取得；MATH-500 的源文件和 150/50/300 固定切分已在 `data/`。主模型、第二模型与采样、终止和评分设置必须分别记录。以下是本轮实际依赖顺序；日志与人工核验文件不可用虚假成功标记代替。

1. 获取固定上游代码到 `vendor/llm-think-stop`（commit `21efe411bcaf34de884c1120ab7fb0573c193a62`）；EAT 参考代码为 `93a46f7a8b3d401511389e8a10dc117aa7f9c287`。上游源码不改写。
2. 创建隔离 `.venv` 和 `logs/`。`run_pipeline.py`、`run_holdout_remainder.py`、`validate_cache_clone.py`、`repeat_branch_controls.py` 中的模型路径按实际存储位置配置；使用不同路径时记录差异，不复制旧的通过标记。
3. 验证模型必要文件和分层数据文件哈希；运行 CPU 单元检查。原版 P0 用以下参数，输出重定向到 `logs/original.log`，使结束标记可核查：

```bash
CUDA_VISIBLE_DEVICES=0 python -u scripts/run_original_baseline.py \
  --data data/math500_smoke.jsonl --model /path/to/Qwen3-4B \
  --n 24 --max_think 4096 --budgets 0,128,256,512,1024,2048 \
  --ans_tokens 192 --batch 1 --seed 20261008 > logs/original.log 2>&1
CUDA_VISIBLE_DEVICES=1 python scripts/validate_protocol.py --model /path/to/Qwen3-4B --n 24
CUDA_VISIBLE_DEVICES=1 python scripts/validate_cache_clone.py
```

4. `run_pipeline.py` 按顺序等待 P0、完成 24 题 pilot、等待真实的 50 答案人工审核，然后采集开发/工程银行。人工审核结果写入 `results/protocol/pilot_review.json`，不可直接沿用本轮已审样本来认证新生成。
5. 开发集训练与问题隔离的 CV 完成后，工程集校准。当前程序在首次测试生成前等待 `provenance/ABLATION_POLICY_FREEZE_20261012.json`：运行 `freeze_ablations.py`，保存策略哈希并确认已有测试记录数为零。选择必须独立于任何测试答案。若修正采集或判分，要保留旧银行/分数，重新完成依赖，而非覆盖失败证据。
6. 主管线完成前 50 题的全部方法和第二模型 24 题；另启动 `run_holdout_remainder.py`，它等待第二模型完成后才补齐主模型另外 250 题。`finalize_execution.py` 等待最终 300 题生成标记，再运行严格数据审计、统计、图表与报告。

```bash
python scripts/run_pipeline.py
# 独立后台进程；启动顺序不代替完成证明：
python scripts/run_holdout_remainder.py
python scripts/finalize_execution.py
```

这三个程序需要按等待依赖运行；持续监控实际进程句柄和结果，不能只读取 marker 后推断生成完成。续跑时保留完整记录，仅补未完成的 `(model, method, problem_id)`；观察超时不构成重启依据。当前 `run_pipeline.py` 自己并不启动另外两个程序。

## 证据范围

原版 BF16 greedy 与主实验 FP16 采样分别保留。模型输出与人工抽检、数学等价判分、问题隔离验证、真实在线成本、统计置信区间和文件哈希各自有独立用途；它们不能互相替代。严格 1pp 非劣要求仍取决于实际样本量与有害对风险，不由“复现程序无报错”证明。

本轮还保留旧评分、异常格式、不同数值精度的失败、断线期间的输出和原始重复控制。认证信息不进入归档。
