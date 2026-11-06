# 四补充核查、冻结协议与一次P0.5短试

日期2026-11-05。当前入口：[最终状态与判断](RUN_STATUS_ZH.md)、[四项补充如何采纳/修正](REVIEW_DECISIONS_ZH.md)。

**真实结果：16题×5臂的80自由回答全完成，辅助Y/Z诊断只完成固定前8题。** 新协议正确数8/11/0/12/8，包含模型加载和已完成诊断共4.4591单卡分钟。联合臂净多1题涉及截断/交付差异，不能宣布induction互补或新算法benchmark收益；剩余诊断没有加跑。

## 证据入口

- [全部80原文、220候选和独立主分析](PRIMARY_P05_ANALYSIS_ZH.md)、[机器可读分析](PRIMARY_P05_ANALYSIS.json)。
- [独立来源/渲染/数值/成本审计](independent_p05_release_audit.md)、[JSON](independent_p05_release_audit.json)。
- [实验前协议草案](P05_PROTOCOL_DRAFT_20261105.json)、[启动冻结](prelaunch_freeze_01.json)、[真实tokenizer预冻结输入](rendered_inputs_01.json)。
- [真实runner](p05_five_arm.py)、[有限启动器](launch_p05.py)、[独立源码审查](p05_five_arm_source_review.md)。
- [候选完整评分与induction假说审查](candidate_scoring_and_induction_audit.md)、[独立候选角色表](fixed_candidate_roles.json)。
- [裁尾前缀复用CPU控制](crop_tail_review.md)、[JSON](crop_tail_cpu_control.json)。
- [自然数值候选图审查](numeric_provenance_dependency_audit.md)、[候选统计](P1_heuristic_numeric_candidate_summary.json)。所有边仍待语义复核，不是自然事件率。
- [问题、尝试、效果与猜想](WORKLOG_ZH.md)。

`p05_five_arm_01/`保留原模型输出、NPZ、forward ledger、时间账、manifest与partial状态。主分解析器在新输出前冻结，不做事后改分；诊断缺失不补成16题。原P0与先前所有研究包保持不变。

## 范围与复现注意

原base、解析器和16例按字节复制在frozen_dependencies/供复核。实际GPU使用Torch2.8.0+cu128、Transformers4.55.2、Qwen3-4B FP16/eager；CPU tiny控制使用Torch2.11 CPU和隔离TF4.55.2，二者不可混作模型效果。

runtime4552/为本地隔离依赖，交付包不打包整套安装；官方源URL/hash及关键CPU控制保留。真实模型权重不打包，沿用此前重验的只读snapshot。GPU启动器要求新的输出路径并检查显式UUID，当前同名结果/launcher已存在，会拒绝重复运行。

单次新实验源、输入、模型、解析器和token映射均有SHA绑定。统计只覆盖人工短状态，不能当作自然MATH-500/AIME准确率或部署安全证明。固定100题的语义P1、基础能力单独对照、完整版本门控与后续训练均未在本轮执行。
