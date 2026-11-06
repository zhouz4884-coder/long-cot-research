# 下一轮设计与实际完成项

入口：[方法设计与决定](NEXT_METHOD_DESIGN_ZH.md)、[机器可读协议V1](RESEARCH_PROTOCOL_V1.json)。日期2026-11-05；本轮新增GPU消耗为0，没有新模型生成/LLM更新。

## 已实际完成

- [原16例/80输出的事实审计](claim_audit_P05_20261105.md)：U无旧数、y/z均为x后代、P保留所有定义；原16例不能测试保留“独立y/z”。
- [历史轨迹清点与P1测量设计](natural_P1_budget_and_measurement.md)：已冻结[100题清单](P1_sampling_manifest.json)，含15cap，尚未语义标注事件率。
- [文献、VCORE公式与作者代码审查](gradient_design_literature_audit.md)：one-backward按一个方向计；ECN不等于首次出现数字；答案锚定已有近邻。
- [CPU梯度数学控制](gradient_utility_sanity.json)：精确内积与方向差分吻合；共享参数效用不同于后位置activation梯度；独立一步不保证下降。
- [未来轮次的冻结解析器](frozen_answer_extractor.py)与[9项检查](answer_extractor_validation.json)。它不会追溯改变原P0事后评分性质。
- [12个新拓扑状态v2](P05_topology_cases_v2.json)与[独立审查](P05_case_design_review.md)：确有独立r，含前/后位置和E/C/W；CPU精确算术已通过。只有两个程序，不是12个独立自然问题。
- [问题、尝试、决策与猜想](WORKLOG_ZH.md)。

## 尚未执行

P1语义事件标注、真实tokenizer的P0.5 slot/位置冻结、新P0.5 GPU、G1真实模型梯度、G2临时一步均未执行。协议是本地版本化的设计，不是公开预注册，不是已验证新算法，也不自动授权/启动所有分支。先选一个有限轮次，不将全格相乘。

旧P0源、原始结果、80条抽取和旧证据包保留不变。新输入v1在模型运行前发现数值别名，保留 `P05_topology_cases.json` 与 `archive/build_P05_topology_cases_v1.py` 作为过程；实际后续只使用v2。

## CPU复核

```powershell
python -X utf8 D:\ACL\research\next_design_20261105\claim_audit_P05_20261105.py
python -X utf8 D:\ACL\research\next_design_20261105\gradient_utility_sanity.py --output D:\ACL\research\next_design_20261105\gradient_control_recheck_new.json
python -X utf8 D:\ACL\research\next_design_20261105\build_P05_topology_cases.py --output D:\ACL\research\next_design_20261105\topology_recheck_new.json
```

后两个命令要求新输出，保留已有冻结文件；随机模型控制没有预训练LLM成绩。清点/抽样脚本只读历史本地文件，不恢复旧GPU队列。
