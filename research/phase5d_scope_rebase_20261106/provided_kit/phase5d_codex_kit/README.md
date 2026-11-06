# Long-CoT Phase5-D Codex Kit

本目录是**独立研究计划与CPU示例**；不会修改你现有GitHub仓库，也没有启动3090实验。

文件：
- `PHASE5D_CODEX_EXECUTION_PLAN_ZH.md`：详细Codex执行目标、数学约束、分阶段计划、实验与统计协议、接受/失败条件。
- `scope_rebase_core.py`：带适用范围的多重证明支持、证明撤销、bridge文本样例、受限整数运算检查的CPU参考。
- `native_prefix_reference.py`：同一Qwen3 thinking assistant token前缀的构造及独立prefill续写参考；不是完整原生checkpoint执行器。
- `tests/test_scope_rebase_core.py`：CPU机制测试。

可用命令（在该目录运行）：

```bash
PYTHONPATH=. python -m pytest -q tests/test_scope_rebase_core.py
```

已验证：本地5个CPU单元测试通过。未验证：模型文件/3090/CUDA/KV裁剪正确性、原生修复性能、算法准确率。
