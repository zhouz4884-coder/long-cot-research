# Phase 3：P0状态恢复机制与真实16例首轮证据

状态：**CPU控制、真实短试和独立复核完成；目标mask未通过行为扩大门槛。** 更新：2026-11-06。

## 研究问题

在同一冻结前缀上，屏蔽旧段的直接读取与从prefill开始屏蔽并重算后续状态，是否等价？状态差异能否转成超出普通随机干预的实际答案收益？

## 输入与协议

CPU层使用带RoPE的随机因果Transformer，固定5个种子、float64、30组删除/重算比较。真实层使用重新核验的Qwen3-4B、单RTX3090、FP16/eager、固定16个人工teacher-forced状态：E8（旧错/真修订）、C4（无错）、W4（错误修订）。同token、原绝对位置与读出，五臂为full、target_late、target_early_reprefill、random_late、random_early_reprefill。

修订是外部人工共享输入，不是模型自然自纠错。原16例的y/z都是x后代，没有真正可保护的独立数值r；U不是可声称保留了正确中间数值的证据。mask保留全部KV槽位，不是缓存释放。随机对照仅匹配数量，并未充分匹配年龄/连续跨度。

## 实际动作

1. 验证CPU无删除/等价实现与位置控制，比较晚屏蔽、干净重算及位置压缩。
2. 完成16例×5臂真实模型短试、原始输出、候选/分布/KV读出和恒等/因果mask控制。
3. 保留原冻结严格解析；发现输出含标点/算式后，仅用原自由文本构建并冻结Gold-blind的**事后探索抽取**，没有GPU重跑。
4. 独立从原始文件复核指标、概率/数值与反例；未因某组效果较好而改变样本。

## 数据与结论

CPU的被禁读位置注意力为0，30/30组后续保留KV与干净重算不同，3/30下一token argmax改变；恒等控制最大误差约2.67×10⁻¹⁵以内。这只证明历史计算路径差异，不是自然推理错误率。

| 真实模型臂 | 原严格解析正确/16 | 事后探索抽取正确/16 | E/8 | C/4 | W/4 |
|---|---:|---:|---:|---:|---:|
| full | 0 | 7 | 1 | 4 | 2 |
| target_late | 0 | 3 | 1 | 2 | 0 |
| target_early_reprefill | 0 | 5 | 4 | 1 | 0 |
| random_late | 0 | 7 | 1 | 4 | 2 |
| random_early_reprefill | 0 | 5 | 1 | 3 | 1 |

原严格解析0/16不等于全部算术错误；事后7/3/5/7/5也不能改称预注册主结果。目标早重算在E有改善，但总体不胜full，并伤害C/W；随机重算也有变化，故不能直接提出有效语义KV修复算法。

外层执行137.76秒，保守计2.296单卡分钟；runner135.582秒，哈希/加载66.327秒，两者计时相互包含。实际前缀137–149 token、自由生成490 token，不能外推8k–16k自然长链或训练吞吐。V100未获GPU分配，不能计作已完成跨平台模型实验。

## 失败、限制与可证伪猜想

可能原因包括：删除本来有效的支持、修订真伪未核验、目标变量绑定/读出错误、上下文历史影响、算术能力或格式不匹配。候选数字与某表达式兼容，不足以定位内部“跳步/进度指针”或旧数来源。

E02等现象需要与普通组合计算、简短按序推导提示和原题重算区分；W组显示盲目接受修订/删段不安全。若普通文本读出已解决问题，就不能把增益归给KV；若同可见信息下Early与Late仍有增量，再讨论有界历史重编码作用。

## 下一门槛

预先冻结新解析/读出、同批基线和成本，对比OneLine与WholeEarly的主效应/交互；这一有限检查后来在[Phase 4](Phase4_理论审查与P05五臂短试_ZH.md)执行。自然P1语义事件、P-only/P+R基础能力与真正独立r控制仍不得由原16例代替。

## 证据路径

- [方向判断](../../research/direction_selection_20261105/RESEARCH_DECISION_ZH.md)、[该轮实际状态](../../research/direction_selection_20261105/RUN_STATUS_ZH.md)。
- [CPU源码](../../research/direction_selection_20261105/cpu_cache_consistency_control.py)、[CPU结果](../../research/direction_selection_20261105/cpu_cache_consistency_control.json)。
- [真实run summary](../../research/direction_selection_20261105/p0_qwen3_4b_fp16_01/summary.json)、[原始run manifest](../../research/direction_selection_20261105/p0_qwen3_4b_fp16_01/manifest.json)。
- [事后分析](../../research/direction_selection_20261105/REAL_P0_ANALYSIS_ZH.md)、[机器分析](../../research/direction_selection_20261105/REAL_P0_ANALYSIS.json)、[独立审计](../../research/direction_selection_20261105/independent_real_p0_audit.md)。
