# Phase5-B 工作与问题日志

2026-11-06。先完整阅读新意见、核查旧raw与100条历史元数据，再定义本轮；未改任何旧分数、原始run或冻结协议。

纠正：上一轮把表示原型当成主算法探索，短题/JSON复述/跑序降低了区分度。接受后台管账和前台边界的建议；拒绝把同工具基线说成泄漏，也拒绝把图切片直接宣称新Markov定理、格式100%或80%压缩。

历史诊断完整审阅8条记录答错正文；9条正确cap仅审固定5段；2条正确未cap控制全文。发现记号评分、forced读出丢分母/答案类型、错误复核W前缀、几何/坐标作用域与cap。没有已确认可自动取图的E-Reuse自然病例；不能推自然发生率。

准备故障：历史correct存整数0/1，初步identity False统计错0条，冻结前改bool后为8条；SymPy有理数和Python浮点比较失败，改Rational(1,8)后通过。没有GPU消耗。终端答案兼容中文/boxed/合法JSON及透明Markdown；重复键/冲突/截断拒绝。旧分不回填。

CPU最终684项通过（含600随机DAG投影=冷精确计算），独立SymPy核控制题，圆排列枚举720与自然符号见证。随机tiny最终目录cpu_interface_final_02，10输出完整、8token cap，仅接口测试；旧final/01是准备历史。自然EOS mock另验4项，不把随机CPU分数当能力。

新受控题1个20定义程序：12个独立支路算式+根+7个目标算式。核心先SharedGFull与BoundaryProjection按E/C/W配对，再Raw三态和1唯一RestartP，共10输出。投影后三态prompt相同，是控制器一致性/重复输入检查，不能变成3个独立问题。普通DAG切片器也产生同prompt，增量不能由命名获得。

在任何新模型输出前绑定source/core/data/jobs/协议、真实tokenizer10输入和CPU证据。单卡累计≤300秒，worker270/outer285+kill5；自然EOS、768为较长受控题保护顶。严格记未执行/超时/触顶，不能靠补跑或换题救分。

## 唯一真实GPU轮与结果

10/10全部完成，核心E/C/W均覆盖，174.407秒=2.90678单卡分钟，EOS10/10/cap0/unparsed0。Raw3/3、SharedGFull2/3、Projection3/3、RestartP唯一1/1。GFull-E仍用旧f275而非当前f267；Projection正确，但Raw/Restart同样正确，不能说最强基线质量提升。投影161对GFull430输入token减少62.56%，这是fresh-prefill的单程序条件结果。

全部19取回文件/预启动11文件绑定、10实际输入、684最终CPU检查、独立SymPy值420与ledger重数通过。GPU事后空闲。保留模块，不追加模型试跑；下一问题是自然目标/答案类型和证书范围，而不是再堆合成算术或宣称Markov新定理。详见RUN_STATUS_ZH.md。

## 汇报方式修正

用户进一步要求逐条回应方法建议，并明确在什么总目标/子问题/阶段下做了多少。已先在对话回应当前数据和采纳/修改/不采纳理由，随后将建议取舍表、当前进度与未完成边界写入docs/phases/Phase5B_自然诊断与父边界投影_ZH.md，并将后续汇报约定保存到docs/next_phase/RESEARCH_REPORTING_CONVENTION_ZH.md；不是新增计时任务，也未更新个人记忆库。
