# D3.7 终局显式标量格式审计

本轮为冻结 F2 增加补充读出。它只在允许的 F2 弃权类型上工作，要求模型自然 EOS、思考已闭合、交付未被控制器扣留、目标已知为标量。显式终局段须有唯一完整装框，箱内只接受精确有理数字面。目标前缀和后缀使用公开题面允许的角色名称。存在冲突值、未解的早期交付、引语、代码、假设、模糊目标或局部目标时弃权。直接传递已有 F2 成功读出。规则保持数学认证范围与读出范围分开，输出来源字符区间。[实现](terminal_scalar_fallback.py) · [九项控制测试](terminal_tests.py)

## 新格式控制

独立于 D3.6 的模型输出编写了 36 条合成文本，18 条标注可接受显式标量，18 条标注应弃权。样例包含分数、负数、逗号千位、等值重复、目标别名、冲突、引语、局部极值、条件句、技术容量、扣留、思考未闭合与未知目标。实现与控制由同一审计员编写。先冻结控制及单独标签，首次抽取前报告输入哈希。香港时间 2026-11-10 04:08:54 冻结 36 条新控制和 48 条旧 E15 观察，04:09:07 才打开标签文件。两次读取以独立命令执行。[输入](terminal_challenge_inputs.json) · [标签](terminal_challenge_labels.json) · [冻结清单](terminal_challenge_freeze.json) · [盲观察](terminal_observations.json)

| 读出 | 正确接受 | 错误弃权 | 正确弃权 | 错误接受 | 接受错误值 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 冻结 F2 | 6 | 12 | 16 | 2 | 0 |
| F2 加补充读出 | 17 | 1 | 16 | 2 | 0 |

新增接受 11 条，均得到其明确承诺的精确值。A12 明确提交 `90`，参考值为 `91`。读出按标签返回 `90`，数学答案仍错。A02 的备选证明语汇使冻结 F2 记录 `uncertain_final_object`，该原因在补读范围之外，因此仍弃权。两条错误接受来自原 F2，分别是 N10 的暂时可行值和 N11 的条件性答案。新增规则保留既有 F2 成功决定，因此这两类误收仍存在。当前仅验证合成开发控制上的读出，不能估计自然题的误收概率或扩大控制器权限。[逐条混淆与原始原因](terminal_format_audit.json)

## 历史 E15 单独复核

以公开提交 `6e36e19` 和原取回清单校验 48 份 E15 原始模型结果，读出观察阶段不打开既有评分或参考答案。后验分列三条自然 EOS、正确末框且冻结 F2 弃权的已知案例。

| 旧记录 | 补读 |
| --- | --- |
| 后期原始 RNG 的 ProgressiveWitness | 从明确的 Final Result 和目标前缀读得 `10112369` |
| 后期种子 20261112 的 NumericWitness | 从 Conclusion 和明确目标后缀读得 `10112369` |
| 早期原始 RNG 的 NumericWitness | 弃权。原答复前段含 Markdown 题意引语，且前一个终局段的文本结构超出保守语法 |

一条真实扣留和一条容量截断仍未交付。D3.6 正式结果保留原值。作为单列诊断，NumericWitness 从 1/6 到 2/6，ProgressiveWitness 从 3/6 到 4/6，其余臂相同。这里读到的是最终标量，证明正确性未验证。

## 复核命令

在仓库根目录运行 `python -X utf8 -B -m unittest discover -s research/phase5d37_scoped_repair_20261110 -p terminal_tests.py -q`。全部九项通过。两阶段复算可将新证据写入临时目录，原归档文件使用独占写入保护。本次已实际复算，两份 JSON 排除时间字段与其联动哈希后内容一致。无需 GPU、模型或数学评分依赖。

```powershell
@'
import sys
from pathlib import Path
from tempfile import mkdtemp
sys.path.insert(0, str(Path("research/phase5d37_scoped_repair_20261110").resolve()))
import terminal_audit
out = Path(mkdtemp(prefix="d37-terminal-replay-"))
terminal_audit.OBSERVED = out / "terminal_observations.json"
terminal_audit.SCORED = out / "terminal_format_audit.json"
terminal_audit.observe()
terminal_audit.score(terminal_audit.sha(terminal_audit.OBSERVED.read_bytes()))
print(out)
'@ | python -X utf8 -B -
```
