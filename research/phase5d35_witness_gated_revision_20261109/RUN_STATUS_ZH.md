# Phase 5-D3.5 见证门控修订进度

本阶段检验在长思维链中，候选见证能否阻止错误交付，以及用同一条见证撤回错误前沿后能否改善最终答案。原题的完整约束支持精确认证时，可以交付证书值。可行反例只能撤回它实际反驳的声明。历史复核仍为 D3 正式 16/32，685 条结构表达式，正式修复准入 0。[实验协议](D35_PROTOCOL_ZH.md) · [继承审计](INHERITED_D3_AUDIT.json)

| 任务 | 已核验的进度 |
| --- | --- |
| 离线见证 | 五个选定历史窗口中，原题编译、自动检测和合法动作均为 5/5。29 项反向控制通过。固定模板匹配 D3 旧题 4/16。 |
| E12 终局保护 | 原生续推自然 EOS 并复现错误答案 45。门控拒绝实际草稿并交付 61。同证据提示、直接工具和同一原生思考的末尾整数装框均得到 61。两条模型生成自然 EOS。 |
| E15 见证回退 | 已启动。观察见证 1011235 只能反驳 303369 的最大性。待模型分支结束后，再审计输出、切点、工具和完整成本。 |

首次 E12 LastThoughtAnswer 读出因思考标签未分离而弃权，原始结果保留。随后用盲于参考答案的整数装框规则复核，读取同一条原生思考末尾，得到 61。该读出在共同检查点之后再支付 11 个模型输入。直接工具用原题完成认证，GPU 输入为零。当前证据来自选定历史轨迹，不能估计独立题准确率。[离线回放](OFFLINE_DEVELOPMENT_AUDIT.json) · [E12 原始产物](gpu_results/e12/) · [E12 审计](E12_GPU_AUDIT.json) · [E12 读出复核](E12_DELIVERY_BASELINES.json) · [工作日志](WORKLOG_ZH.md)

## 复核入口

从仓库根目录运行以下命令复核 E12 取回文件的 SHA-256、前向成本和最终答案。运行时取回清单与原始结果按字节保留。冻结包记录生成时的本机路径及设备身份。模型和依赖从原渠道获取，实验室专用远程启动脚本由本地维护。

```powershell
python -X utf8 -B research/phase5d35_witness_gated_revision_20261109/audit_gpu_development.py e12
```

复建开发输入可运行本目录的 `prepare_checkpoints.py`。实机入口为 `development_worker.py`。按相应 `*_runtime_freeze.json` 整理运行目录，`legacy/` 下文件使用基线提交 `4dfdb426aa63` 的同名源码，逐一核对清单哈希，再传入运行目录、案例、模型目录和设备。模型文件身份见 [E12 实机清单](gpu_results/e12/manifest.json)。复跑历史窗口抽取或含真实 tokenizer 的测试时，将该清单对应的 Qwen3-4B tokenizer 文件准备到 `outputs/d2_tokenizer_20261107/`，可用 [D2 取回脚本](../phase5d2_quarantined_rebase_20261107/fetch_coverage.py) 的对应逻辑生成 tokenizer 清单。
