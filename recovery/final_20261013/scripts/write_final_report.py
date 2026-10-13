"""Write a Chinese full-process report from completed, count-verified artifacts."""
import json
from pathlib import Path
from datetime import datetime,timezone

ROOT=Path(__file__).resolve().parents[1]
def read(name):return json.loads((ROOT/name).read_text(encoding='utf-8'))
stats=read('results/analysis/online_statistics.json');integrity=read('results/analysis/study_integrity.json')
assert integrity['passed'] and stats['expected_counts_verified'] and stats['total_online_records']==1648
cv=read('results/analysis/grouped_cv.json');repeat=read('results/analysis/repeat_control_analysis.json')
cal=read('results/analysis/policy_calibration.json');lineage=read('results/audit/bank_lineage.json')
trajectory=read('results/analysis/trajectory_consistency.json');assert trajectory['is_final']
primary=stats['models']['Qwen3-4B'];second=stats['models']['Qwen3-4B-Thinking-2507']
gain=primary['comparisons']['transition_vs_full'];strong=primary['comparisons']['transition_vs_eat']
names={'full':'FULL（8192 上限）','transition':'净收益控制器','learned_stop':'学习型正确率早停','eat':'EAT 共同协议适配',
 'conformal_thinking':'Conformal Thinking 双阈值适配','fixed0':'零思考','fixed1024':'固定 1024','random':'随机停止',
 'value_outcome':'动作边际正确率','value_frequency':'替换检测频率','value_cheap':'仅便宜特征','matched_stop':'同训练器正确率早停'}
def interval(row,key,scale=100):
 low,high=row['bootstrap_95ci'][key];return f'[{low*scale:.2f}, {high*scale:.2f}]'
def table(data,methods):
 lines=['| 方法 | n | 正确数/准确率 | 平均生成 token | 平均实际秒 | P95 秒 | 平均决策秒 | 触顶/解析非成功 |',
        '|---|---:|---:|---:|---:|---:|---:|---:|']
 for method in methods:
  r=data['methods'][method]
  lines.append(f"| {names[method]} | {r['n']} | {r['correct']}/{r['n']}；{100*r['accuracy']:.2f}% | {r['mean_tokens']:.1f} | {r['mean_wall_ms']/1000:.2f} | {r['p95_wall_ms']/1000:.2f} | {r['mean_detector_ms']/1000:.3f} | {r['length_censored']}/{r['parse_failed']} |")
 return '\n'.join(lines)
def comparison(data,keys):
 lines=['| 对照（控制器减对照） | 配对 n | 准确率差 pp（95% CI） | token 节省 %（95% CI） | 实际耗时节省 %（95% CI） | 修正/改错 |',
        '|---|---:|---:|---:|---:|---:|']
 for key in keys:
  r=data['comparisons'][key];baseline=key.removeprefix('transition_vs_')
  lines.append(f"| {names[baseline]} | {r['n']} | {100*r['accuracy_delta']:.2f} {interval(r,'accuracy_delta')} | {100*r['token_saving']:.2f} {interval(r,'token_saving')} | {100*r['wall_saving']:.2f} {interval(r,'wall_saving')} | {r['beneficial_pairs']}/{r['harmful_pairs']} |")
 return '\n'.join(lines)
trace_dev=lineage['splits']['development'];trans=cv['transitions']['all']
model_rows=['| 特征/训练器 | STEP 修正 AP | STEP 改错 AP | FULL 修正 AUC | 当前答案正确率 AUC | 一步净收益 Spearman（检查点） |',
            '|---|---:|---:|---:|---:|---:|']
for key,label in [('length_only','仅长度'),('all_cheap','便宜特征/线性'),('gbdt_cheap','便宜特征/GBDT'),('readout_linear','加入回答熵/线性'),('readout_tree','加入回答熵/GBDT')]:
 r=cv['models'][key];model_rows.append(f"| {label} | {r['step_fix']['pr_auc']:.4f} | {r['step_harm']['pr_auc']:.4f} | {r['full_fix']['roc_auc']:.4f} | {r['stop_correct']['roc_auc']:.4f} | {r['net_spearman']:.4f} |")
spec=cal['selected_empirical']['transition']
repeat_table=['| 工程状态（题目与 prefix token） | STOP 正确/4 | STEP 正确/4 | 修正/改错次数 | 观测净差 |',
              '|---|---:|---:|---:|---:|']
for r in repeat['states']:
    parts=r['checkpoint_id'].split(':');counts=r['transition_counts']
    repeat_table.append(f"| {parts[0]}；{parts[2]} | {r['stop_correct']}/4 | {r['step_correct']}/4 | {counts.get('0->1',0)}/{counts.get('1->0',0)} | {r['mean_step_minus_stop']:.2f} |")
point_ok=gain['accuracy_delta']>=-.01 and gain['token_saving']>=.15 and gain['wall_saving']>0
learned=primary['comparisons']['transition_vs_learned_stop']
strong_ok=all(r['accuracy_delta']>=-.01 and r['token_saving']>0 and r['wall_saving']>0 for r in [strong,learned])
verdict=('取得有价值的经验性能信号，但论文结论需要继续诊断和独立扩展' if point_ok and strong_ok else
         '强基线比较尚未通过，当前方案 NO-GO' if point_ok else '本轮未达到质量与计算收益共同要求，当前方案 NO-GO')
text=f'''# 自然推理干预价值：完整实验总结

生成时间（UTC）：{datetime.now(timezone.utc).isoformat(timespec='seconds')}。执行从 2026-10-08 开始，2026-10-11 恢复服务器连接后连续推进。[原始研究讨论](https://chatgpt.com/share/6ac7ac26-c6a8-83ec-be63-d018140ce23e)的可读取正文已完整阅读，共 39,047 字符。按照原定 14 天工作的依赖顺序执行，未把 14 天日历等待当作研究条件。

## 结论与完成范围

**{verdict}。** 主模型最终 300 题上，控制器相对 FULL 的准确率差为 {100*gain['accuracy_delta']:.2f} pp，token 节省 {100*gain['token_saving']:.2f}%，真实 wall-clock 节省 {100*gain['wall_saving']:.2f}%。对应 95% 问题配对 bootstrap 区间分别为 {interval(gain,'accuracy_delta')} pp、{interval(gain,'token_saving')}%、{interval(gain,'wall_saving')}%。不能用点估计代替质量保证。

本轮完成原版 24 题 P0（168 次生成）、真实 KV 三分支 pilot、150 题开发、50 题工程校准、按题隔离的五折预测、事件重复控制、300 题主在线比较、50 题额外控制和消融，以及第二模型 24 题迁移检查。最终真实在线记录 **1648 条**，所有预期题目 ID、记录数、策略冻结哈希、实际成本字段通过审计。基础设施检查不计入任务正确率。

**原始“一步净收益可预测”的主张仍缺少支持。** STEP 的 beneficial fix/harmful flip 很少，问题隔离验证中净收益排序弱；加入回答侧信号主要改善当前正确率与较长继续的价值预测。即使控制器取得节省，也不能据此宣称发现了确定性的反思失效机制、最优停止规则，或已经具备高水平论文的充分新颖性。

## 1. 冻结的模型、数据和执行环境

主模型 Qwen3-4B revision `1cfa9a7208912126459214e8b04321603b3df60c`；第二模型 Qwen3-4B-Thinking-2507 revision `768f209d9ea81521153ed38c47d515654e938aea`，经 ModelScope 下载后与冻结官方文件身份核对。模型身份记录、服务器环境、原始生成和日志均保留。

MATH-500 revision `6e4ed1a2a79af7d8630a6b768ec859cb5af4d3be`，原始数据 SHA256 `35dc41080a3680858b27fa7e0533d2d547825316fc5dafe5d316f4ccc5a06132`。分层切分固定为开发 150、工程 50、测试 300，题目集合无交叉。P0 的 24 题属于工程集；模型可能见过公开数据的预训练污染未得到排除，因此本轮不等同于新鲜未知数学题的泛化证据。

服务器为两张 RTX 3090 24GB；使用 FP16、SDPA、Torch 2.8.0+cu128、Transformers 4.55.2、Math-Verify 0.9.0。Thinking 开启，T=0.6、top_p=0.95、top_k=20。主思考最多 8192 token，答案最多 192 token；所有触顶状态保留。这里的 FULL 是有界继续，不是无限预算答案 oracle。

## 2. P0 与测量修复

冻结原版 `llm-think-stop` commit `21efe411bcaf34de884c1120ab7fb0573c193a62`，先按其 BF16 greedy 协议运行 24 题×7 条生成。相同原始输出重评分后，预算 0/128/256/512/1024/2048/FULL 的正确数为 4/7/8/13/19/20/16；FULL 的 6 条轨迹未自然关闭。判分提升不是模型提升，也不能与后续 FP16 采样、共同短答案协议直接相减来报告算法收益。

初期仅添加思考结束标记会让模型在 192-token 答案窗口中重写推导。共同答案前缀改为 `Final answer: \\boxed{{`，首个完整外层 boxed 闭合即停止。控制前缀和答案生成 token 分别计数，缺失完整答案不能从中间数字猜最终解。多答案任务若模型只输出第一个分量，属于该共同 readout 协议下的实际错误；此限制仍需在未来扩展协议中检验。

数值诊断区分同路线重复和不同 prefill 路线：FP32 跨路线误差约 4e-5；BF16 在真实前缀的相对 L2 超过预设 1% 门槛，因此主实验改为 FP16。五个实际前缀的 FP16 检查通过（相对 L2 <0.21%，受控 16-token 续写相同）。这不是任意长序列、任意硬件都位级一致的保证。缓存子分支通过父 KV 不变和同输入续写检查；EAT 探针采用 append 后 crop，三个真实前缀全层 K/V 和受控续写保持一致。

本轮使用数学等价评分，允许未完全计算或化简的等价表达式，例如点积算式和最终数值被视为同一个答案。因此指标不证明模型已经执行每一步算术，也不单独认证“完全化简”等表述要求。该规则对所有方法一致；若未来增加规范答案形式或表达式复杂度指标，必须另报，不能事后只给某一方法更换评分标准。

另外修复了字面转义花括号影响语义边界、列向量与坐标元组表示不等价，以及数字括号隐式乘法/缺失反斜杠 log 的判分问题。向量按坐标顺序验证，交换坐标仍错误。后两项表面修复在测试生成前完成，完整银行统一重评；四个分支评分改变，原始分数另存。只抽取到文本的结果记 fallback_only，不冒充数学解析成功。重复控制中的原始分数不覆盖，另生成 v3 派生判分。

## 3. 分支采集与数据标签

检查点只依赖已生成 token：已完成、数学/花括号/代码块平衡的段落；反思触发要等词语实际出现。开发采样自然预算 256/1024/2048/4096 的下一合法边界及前两个反思点。STEP 继续一个自然段落，软目标 150 token、硬上限 214；超限保留并单列。STOP/STEP 的反事实分支从真实缓存复制，FULL 使用父轨迹的实际继续；离线分支成本不混进父 FULL 的成本。

开发集 {trace_dev['trace_n']} 条完整轨迹、699 个检查点，149 个题目有检查点；`test/prealgebra/2066.json` 在可用检查点前自然结束，仍计入完整数据。开发 FULL 正确 {trace_dev['trace_correct']}/150，触顶 {trace_dev['trace_censored']} 条。工程集完整 50 条轨迹、210 个检查点，FULL 正确 47/50。全部 909 个前缀 token ID/hash 与父轨迹吻合。

开发集 STEP 转移为 {trans['step_transition']}，硬 STEP 超限 {trans['step_overflow']} 条；这些检查点共享题目，不能当成 699 个独立统计样本。修正与改错的标签是在指定采样耦合及短答案协议下的观测结果，包含推理内容、答案抽取和采样变化，不等同于确定性的内部决策变化。

最终实际 token 序列另作共同前缀审计：所有观察到的思考前缀是否与配对 FULL 相同：{trajectory['all_observed_prefixes_match']}；相同完整答案上下文的受控输出是否相同：{trajectory['all_observed_same_context_answers_match']}；相同输出的判分是否一致：{trajectory['all_observed_identical_outputs_scored_consistently']}。逐方法检查数与任何异常题目 ID 完整保存于 `trajectory_consistency.json`。这直接检查保存的实际序列，而非只依赖三个前缀的缓存单元验收；异常仍需按代码、数值和模型机制分别分析。

## 4. 借鉴的方法与本轮实际尝试

借鉴 [EAT](https://arxiv.org/abs/2509.26522) 的结束思考后回答分布熵；沿用 [Conformal Thinking](https://arxiv.org/abs/2602.03814) 的上下阈值思路作为受控基线。EAT 代码固定 `93a46f7a8b3d401511389e8a10dc117aa7f9c287`。本轮为共同格式和同一决策网格下的独立实现：回答熵采用共同 boxed 前缀、自然对数和实际缓存前向；阈值重新在工程集选择。它不是作者完整原设置指标的逐项复现。

候选创新是分别预测 beneficial fix 与 harmful flip，比较其差值和动作边际正确率；以预计准确率收益减去条件计算代价选择 STOP/STEP/FULL，并将已有轨迹信号与回答侧信号融合。额外比较逐步再判断与自适应间隔。预测器为 StandardScaler+LogisticRegression 和浅 GBDT，成本为对数 token Ridge。所有折按题目隔离，训练没有使用工程或测试标签。

冻结主策略实际选择：训练器 `{spec.get('predictor_type')}`，模式 `{spec.get('prediction_mode')}`，控制方式 `{spec.get('control_mode','one_shot')}`，lambda={spec.get('cost_lambda')}，STOP margin={spec.get('margin')}。报告实际选中的模式，不把没有入选的自适应间隔宣称为最终贡献。工程集点估计为 94% 准确率、{spec['token_saving']*100:.2f}% token 节省；最终测试结果才是外部验收。

逐步再判断模式的实际执行是 STOP 或继续到后续合法检查点再评估；STEP/FULL 的预测价值参与停止判断，但不代表在线每次执行离线 STEP/FULL 的完整预算。若采用 sequential，两种继续选择使用相同最小检查间隔；只有 sequential_adaptive 区分两种间隔。因此不能将本轮最终策略包装成已经验证的复杂三动作预算调度器。

[ASAG](https://arxiv.org/abs/2606.15070) 已研究生成策略切换，[REFRAIN](https://arxiv.org/abs/2510.10103) 已研究反思冗余和自适应停止。多动作、反思词检测或回答熵本身不能作为原创贡献。条件收益测量若不能超越当前正确率模型，就需承认收益建模没有额外价值。

## 5. 问题隔离的预测结果

{chr(10).join(model_rows)}

这是开发集 OOF 诊断，不是在线准确率或加速。问题聚类的不确定性、AP 差值和问题均值相关系数保存于 `prediction_cluster_diagnostics.json`。稀有 STEP 事件使 AP 与相关性容易波动；便宜特征大多没有稳定一步价值信号。回答侧特征改善较长继续价值与当前正确率，但仍未使一步净收益可靠排序。

## 6. 最终 300 题真实在线主比较

{table(primary,['full','transition','learned_stop','eat'])}

{comparison(primary,['transition_vs_full','transition_vs_learned_stop','transition_vs_eat'])}

wall-clock 从实际 prompt prefill 到答案生成结束，包含决策和探针，GPU 同步后计时；判分在生成结束后执行，不计入推理延迟。token 包含思考和答案生成，不包含共同控制前缀与探针输入，后两者另记录且其实际成本进入 wall-clock。检测和特征 GPU 时间有重叠，不能把各字段简单相加。每题方法轮换顺序，GPU 并发和缓存热状态仍可能影响耗时；本轮不是通用吞吐或生产服务基准。

控制器相对 FULL 观察到 {gain['harmful_pairs']} 个有害对、{gain['beneficial_pairs']} 个有益对。有害对比例的精确单侧 95% 上界为 {100*gain['one_sided_95_harm_upper']:.2f}%。保守的 1pp 非劣保证是否成立：**{gain['conservative_one_pp_noninferiority_certified']}**。bootstrap 没观察到错误并不等于证明没有错误；300 题也不必然足够证明严格风险要求。

## 7. 额外 50 题控制与消融

{table(primary['cohorts']['diagnostic_50'],['full','transition','learned_stop','eat','conformal_thinking','fixed0','fixed1024','random','value_outcome','value_frequency','value_cheap','matched_stop'])}

{comparison(primary,['transition_vs_conformal_thinking','transition_vs_fixed0','transition_vs_fixed1024','transition_vs_random','transition_vs_value_outcome','transition_vs_value_frequency','transition_vs_value_cheap','transition_vs_matched_stop'])}

这些比较仅用同一批前 50 道测试题配对；不得直接用其 50 题总体准确率与上表 300 题总体准确率相减。所有参数在首次测试生成前冻结。如果同训练器正确率基线与主学习型早停恰好选中同一策略，该记录是同算法独立运行控制，不应算成另一个独立创新基线。Conformal Thinking 在 50 题校准和共同质量约束下选择不开启早退出；风险校正后的低容忍区间也不能认证早退出。不能把这种保守退化推广为原论文方法普遍无效。

该 Conformal 适配实现仍逐点探测，尽管冻结参数已不可能触发停止；其额外探针开销可以被实现优化消除。针对它的耗时差不能全部归因于新的算法优势，主要效率判断应依赖 FULL、实际早停的 EAT 和学习型正确率基线。

## 8. 重复种子与第二模型

保存 {repeat['state_n']} 个工程状态、每状态 4 个独立种子，共 {repeat['repeat_n']} 对 STOP/STEP。评分修复前后选点的并集全部保留，因此数量可能超过初始 8 状态；事件条件采样不能估计总体反转率。逐状态转移次数和输出保存在 `repeat_control_analysis.json`、`repeat_branches.jsonl`。稳定重复的例子支持现象存在，只有四次重复仍不足以证明确定性机制；随种子变化的事件应视为温度噪声和 readout 变化共同作用。

{chr(10).join(repeat_table)}

例如原始幂指数题 algebra/1265 出现一次改错，但四次重复包含一修正、一改错、两次都错误，观测净差为零；括号题 prealgebra/1733 的原始改错在四次重复中没有出现。两个计数题的 STEP 改错均出现四次。log 连乘题 intermediate_algebra/752 统一修复判分后四次都是 1→1，原始事件不能继续用来支持“多想一步纠错”。这些是固定工程前缀下的观测，不能据此给任意未见题目下的事件概率保证。

{table(second,['full','transition'])}

{comparison(second,['transition_vs_full'])}

第二模型使用另外 24 道测试题（test 顺序 50–73），直接迁移主模型策略，没有据第二模型测试结果调阈值。这是同 Qwen 系列两种 4B 模型的小规模迁移诊断，不是跨模型家族、跨任务的普遍结论。

## 9. 好坏结果的分析与原因边界

**已确认的测量原因：** 判分器的向量/乘法/log 表示问题会制造虚假 STEP 修正；结束格式失败会把 192-token 读出截断误当推理失败。统一修复能改变指标，但不是算法能力提升。长轨迹 censoring 与自然终止必须分开计数，不能将达到 8192 的 FULL 当无限预算真值。

**已观察的答案读出问题：** 部分 STEP 思考保留正确向量表达式却读出错误坐标；另一些把问题要求的指数 3/2 回答成值为 8 的 `4^(3/2)`，或只给答案集合的一个元素。这些都是任务输出错误。它们说明 STOP/STEP 反转不必来自“反思把内部答案改错”，还可能来自答案对象漂移、算术计算、采样和短答案格式。

**支持但未证明的解释：** 回答侧熵接近当前求解状态，因此比常规思考 token 熵更能区分是否已经有可读答案；长继续的纠错事件远多于一步事件，训练信号更强。一步段落长度和语义单位不统一、每题只有一个父轨迹、事件稀少与标签噪声，可能解释一步预测弱。需通过更多种子、重复读出、语义粒度和分层模型检验，而非仅凭相关性定因果。

**性能指标的解释原则：** token 少而准确率明显下降是预算截断，不是有效优化；wall-clock 没有同步改善时要检查探针频率和 Python/GPU 开销；超过 FULL 的正确率可能包括修复触顶或答案噪声，不能宣称模型知识新增。对 EAT 和同特征正确率基线的配对结果才决定是否有额外收益。

## 10. 面向高水平论文的判断与下一轮改进

本轮研究执行完成，论文成熟度仍需按证据判断。当前最合适的定位是实际测量与受控自适应计算研究，原始“一步净收益可可靠预测”的强叙事应收缩。是否继续当前控制器，取决于上面的质量区间、EAT/正确率对照和迁移结果，不能只凭工程集 48% 节省。

下一轮优先：① 在全新开发/校准题上为同一前缀多次读出、多个 STEP 种子，估计动作边际收益而非一次成败；② 引入 2/4 个步骤或任务语义单元，对可预测的中尺度价值建模；③ 将读出噪声和推理状态变化分解，联合不确定性、预计剩余成本与显式风险约束；④ 增加不同模型家族和更困难、更新的推理数据，排除只适应 MATH-500；⑤ 独立复现作者完整强基线与相同质量下整条 Pareto 曲线。所有改进使用新开发材料，已见的 300 题不能重新当作新测试集。

可创新之处应是经过消融证实的条件干预价值、风险/成本处理或噪声分解，而不是改名 EAT。需要更充分的数据和多任务证据后，才写投稿级主张；目前不伪称已经达到高水平论文录用标准。

## 11. 复现、失败记录和产物

执行入口为 `run_pipeline.py` 与 `run_holdout_remainder.py`；前者完成 admission、pilot、开发/工程、预测/校准、重复控制、50 题在线和第二模型，后者补齐主四方法的另外 250 题。`finalize_execution.py` 仅在全部生成完成后运行完整统计、审计和科学图。

分析复现和重新生成的依赖、模型路径、人工审核与冻结要求见 `docs/REPRODUCIBILITY_ZH.md`。主质量—成本图的四种方法共享完整 300 题，诊断图的全部方法共享前 50 题，迁移图的两种方法共享同一 24 题；不同题目集合的总体均值不混在同一条性能曲线上。

版本记录见 `CODE_MANIFEST.json`、数据 split manifest、模型核验、策略 freeze 与 `ONLINE_GENERATION_FILES_20261012.json`。原始 P0、被修正的旧评分和日志均在 recovery/远程快照中留档。保留 SSH 中断、BF16 admission 不通过、评分问题、诊断脚本错误与对应修复；没有删除失败题或补造缺失成本。

离线线性头融合等价误差约 8.3e-16、45.7 微秒 CPU 决策只是实现优化验证；七项 CPU 单元测试也不属于真实 GPU benchmark。最终 GPU 输出、题目配对 bootstrap、罕见有害上界和文件哈希各自提供不同层级证据，不相互替代。

主要文件：`results/analysis/online_statistics.json`、`results/analysis/grouped_cv.json`、`results/analysis/policy_calibration.json`、`results/analysis/repeat_control_analysis.json`、`results/analysis/study_integrity.json`、`results/audit/EVENTS_ZH.md`、`results/online/*.jsonl`、`figures/*.png/pdf/svg`。本报告不包含认证凭据。

全部在线修正与改错案例（含两方法最后的实际思考和控制器最后决策）见 `results/audit/ONLINE_CASES_ZH.md` 与 `online_reversals.json`，没有只选好看的成功例子。
'''
(ROOT/'docs/REPORT_ZH.md').write_text(text,encoding='utf-8')
print('WROTE_FINAL_REPORT',len(text),'characters')
