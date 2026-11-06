# Phase 5-A 独立结果审计

审计状态：**PASS**；执行状态：**QUALITY_PARTIAL_TIME_BUDGET**。

结论：本轮只有3个四方法完整配对状态，来自2个算术程序。三个共享G基线各3/3，VersionFrame按预冻结解析器为1/3；未显示其独立正确率增量。两个未解析VersionFrame输出为自然EOS结束的JSON格式，不是512-token截断。本轮主比较没有W输出，不能给W安全性结论。

## 1. 完成范围：exit0不等于30个计划输出完成

计划30输出，实际19：basis 6，主请求13。主状态计划6、已开始4、四方法完整3。

完整配对：['T1_support_before_fault_E', 'T2_support_before_fault_E', 'T1_support_before_fault_C']

部分状态：['T2_support_before_fault_C']

未开始：['T1_support_before_fault_W', 'T2_support_before_fault_W']

T2-C只有SharedGDirect输出，虽已正确交付，但不并入四方法primary配对。两种W主状态均未运行。6个计划状态是2程序×E/C/W，不能视为6个独立题；当前3个完整状态也不是3个独立程序，不给小样本IID显著性或普适正确率保证。

## 2. 冻结primary重数

| 方法 | 完整配对正确/n | E | C | W | EOS | cap | 未解析 |
|---|---:|---:|---:|---|---:|---:|---:|
|SharedGDirect|3/3|2/2|1/1|未运行 / NA|3/3|0|0|
|SharedGCompact|3/3|2/2|1/1|未运行 / NA|3/3|0|0|
|SharedGStepwise|3/3|2/2|1/1|未运行 / NA|3/3|0|0|
|VersionFrame|1/3|1/2|0/1|未运行 / NA|3/3|0|2|

上述所有正确输出也均为EOS且正确；没有因未解析或cap删除完整配对中的状态。逐程序：T1有E/C两个相关完整状态，三个基线各2/2、VersionFrame0/2；T2仅E完整，四方法各1/1。不能把同一程序的多个状态或basis副本增加为独立样本。

冻结parser SHA256：`c2bc053b66778288f524d46f4353e825b1ee654d829027bd02b1cb3173255eed`。逐条raw重新应用parser后与保存extraction/correct一致；目标值由原始可见question中的四个整数定义独立求得T1=80、T2=63，未用Gold选择生成或补写答案。这里的生成后评分不等于生成后改解析器。

## 3. Basis单列及配对变化

P-only的2个唯一输入均正确且EOS；P+实际R的4个唯一输入均正确且EOS，均无cap/未解析。它们来自相同两个程序且有输入去重，不计入主比较分母，也不证明任意读出或自然修订能力。PR中的W记录含错误R，不称为正确修订；这不替代带B/G/工作帧的W主条件。

同期完整状态上，SharedGDirect/Compact/Stepwise彼此无修复/伤害；每个基线→VersionFrame均损失T1-E与T1-C，未获得修复。原因须结合原文区分交付格式与算术，不按1/3直接宣称模型有两次算术错误。

## 4. 原文解释：不改主分

- T1-E与T1-C的VersionFrame在EOS前完整输出JSON，含候选y=56、z=80及 `"final_answer":80`，但没有满足冻结解析器的终结答案格式。保留未解析/错误主分，不临时添加JSON救分；原文说明这两条不应被叙述为已证实算术不会。
- T2-E的VersionFrame先复述大量工作帧，再给候选y=81、z=63和可解析的最终答案，419新token后EOS。它没有触512 guard，但明显比精简基线长。
- 四方法共享的system均要求最终答案格式；VersionFrame用户消息中额外的JSON状态帧可能影响输出模仿，这是待检验的格式/提示猜想，当前没有隔离它的因果实验。不能用此猜想抹掉实际交付失败，也不能改称完整版本算法已失败。
- 当前共享G及明确原题规则已足以让这些简单同期基线答对，独立版本机制增量没有得到支持；只有两个程序且W未跑，不能据此推广其有用或无用范围。

## 5. 公平性、停止条件与manifest复核

取回清单33个文件的bytes/SHA256通过，审计前后均未改；全部30个计划render的messages/text/token IDs与调用前冻结一致，实际19个请求与对应render一致。prelaunch、launcher、runner、adapter、原始输入、prepared消息hash、冻结parser和model manifest绑定通过。这里只核对本地证据，不重新读取远端权重。

主请求的共享证据逐项一致；G只认证原题常数根x/r，derived_arithmetic_evaluations=0，旧y/z均UNVERIFIED，deterministic final commit禁止。没有因C组直接提交旧z。该行为仍是一轮prompt/frame，非逐节点提案check/commit。

实际19条均正常EOS，末token属于配置EOS集合，无cap，input checkpoint长度未变；无parser停止、整数换行停止、强制尾提交或KV mask/crop的实现声明与冻结来源一致。结果只支持这些本地接口观察，不认证所有内部运行行为或自然场景。

## 6. 成本：请求已含G/compile/prefill/decode，不重复相加

launcher 263.007073秒 = 4.383451单卡分钟；worker 261.081115秒。加载/哈希62.295074秒已含于研究总时长。退出0表示正常停止，不改变PARTIAL范围。

| 方法：仅同一3状态 | prompt token合计 | 生成token合计 | 请求秒合计（已含各组件） |
|---|---:|---:|---:|
|SharedGDirect|2535|350|22.810133|
|SharedGCompact|2547|339|22.439483|
|SharedGStepwise|2667|906|58.395253|
|VersionFrame|3686|623|40.675203|

所有19输出共2994生成token、12950prompt token；2994次实际forward、15925累计输入token、同步forward 191.938147秒。逐请求forward/call与ledger、summary核对一致。

所有19请求的request_seconds合计194.924528秒，已经包含G 0.007242秒与compile 0.040691秒等；不能再次加G/compile/prefill/decode。basis、T2-C部分块和共享准备/加载都保留为研究成本；完整配对的每方法成本不冒充完整6状态平均或独立生产加速。

同步forward、request、worker、launcher是嵌套计时，不相加。peak为加载后观察的allocated阶段峰值，原始结束记录compute为空；本审计未连接远端重新观察。

## 7. 全部实际raw输出

下表仅列实际19条，未运行11条不生成假记录。原换行/标点保留为JSON字符串。

| job | kind | 程序/组 | target | 抽取/正确 | EOS/cap | 新token | raw.text JSON |
|---|---|---|---:|---|---|---:|---|
|P_01|basis|T1/basis非独立组样本|80|80 / True|True/False|119|"我们按照题目给出的步骤依次计算：\n\n1. 计算 $ r = 6 \\times 4 = 24 $  \n2. 计算 $ x = 27 - 9 = 18 $  \n3. 计算 $ y = 3 \\times x + 2 = 3 \\times 18 + 2 = 54 + 2 = 56 $  \n4. 计算 $ z = y + r = 56 + 24 = 80 $\n\n最终答案：80"|
|P_02|basis|T2/basis非独立组样本|63|63 / True|True/False|151|"我们按照题目给出的步骤逐步计算：\n\n1. 计算 $ r = 13 + 5 $：  \n   $$\n   r = 18\n   $$\n\n2. 计算 $ x = 54 \\div 6 $（整数除法）：  \n   $$\n   x = 9\n   $$\n\n3. 计算 $ y = x \\times x $：  \n   $$\n   y = 9 \\times 9 = 81\n   $$\n\n4. 计算 $ z = y - r $：  \n   $$\n   z = 81 - 18 = 63\n   $$\n\n最终答案：63"|
|PR_01|basis|T1/basis非独立组样本|80|80 / True|True/False|118|"根据题目原始数学定义进行计算：\n\n1. 计算 $ r = 6 \\times 4 = 24 $  \n2. 计算 $ x = 27 - 9 = 18 $  \n3. 计算 $ y = 3 \\times x + 2 = 3 \\times 18 + 2 = 54 + 2 = 56 $  \n4. 计算 $ z = y + r = 56 + 24 = 80 $\n\n最终答案：80"|
|PR_02|basis|T2/basis非独立组样本|63|63 / True|True/False|85|"根据题目原始数学定义进行计算：\n\n1. $ r = 13 + 5 = 18 $\n2. $ x = 54 \\div 6 = 9 $\n3. $ y = x^2 = 9^2 = 81 $\n4. $ z = y - r = 81 - 18 = 63 $\n\n最终答案：63"|
|PR_03|basis|T1/basis非独立组样本|80|80 / True|True/False|118|"根据题目原始数学定义进行计算：\n\n1. 计算 $ r = 6 \\times 4 = 24 $  \n2. 计算 $ x = 27 - 9 = 18 $  \n3. 计算 $ y = 3 \\times x + 2 = 3 \\times 18 + 2 = 54 + 2 = 56 $  \n4. 计算 $ z = y + r = 56 + 24 = 80 $\n\n最终答案：80"|
|PR_04|basis|T2/basis非独立组样本|63|63 / True|True/False|91|"根据题目原始数学定义进行计算：\n\n1. $ r = 13 + 5 = 18 $\n2. $ x = 54 \\div 6 = 9 $（整数除法）\n3. $ y = x^2 = 9^2 = 81 $\n4. $ z = y - r = 81 - 18 = 63 $\n\n最终答案：63"|
|T1_support_before_fault_E__SharedGDirect|main|T1/E|80|80 / True|True/False|126|"根据题目规则和已核验的根值，依次计算：\n\n1. $ r = 6 \\times 4 = 24 $（已核验）  \n2. $ x = 27 - 9 = 18 $（复核记录确认为正确值）  \n3. $ y = 3 \\times x + 2 = 3 \\times 18 + 2 = 54 + 2 = 56 $  \n4. $ z = y + r = 56 + 24 = 80 $\n\n最终答案：80"|
|T1_support_before_fault_E__SharedGCompact|main|T1/E|80|80 / True|True/False|121|"根据题目规则和已认证的根值，依次计算：\n\n1. **r = 6 * 4 = 24**（已认证）\n2. **x = 27 - 9 = 18**（复核记录确认为正确值，已认证）\n3. **y = 3 * x + 2 = 3 * 18 + 2 = 54 + 2 = 56**\n4. **z = y + r = 56 + 24 = 80**\n\n最终答案：80"|
|T1_support_before_fault_E__SharedGStepwise|main|T1/E|80|80 / True|True/False|327|"根据题目要求，我们需要计算变量 \u0060z\u0060 的值。首先，我们明确目标变量 \u0060z\u0060 的定义和依赖关系：\n\n- \u0060z = y + r\u0060\n- \u0060y = 3*x + 2\u0060\n- \u0060r = 6*4\u0060\n- \u0060x = 27 - 9\u0060\n\n根据已知证据和复核记录，我们已经确认以下变量的值：\n\n- \u0060r = 24\u0060（已验证根值）\n- \u0060x = 18\u0060（复核记录中修正为 18，已验证根值）\n- \u0060y = 3*x + 2\u0060（依赖 \u0060x\u0060，但尚未验证）\n- \u0060z = y + r\u0060（依赖 \u0060y\u0060 和 \u0060r\u0060，但尚未验证）\n\n### 第一步：计算 \u0060y\u0060\n根据定义 \u0060y = 3*x + 2\u0060，我们已知 \u0060x = 18\u0060，因此：\n\n$$\ny = 3*18 + 2 = 54 + 2 = 56\n$$\n\n由于 \u0060x\u0060 已经被验证为 18，因此 \u0060y\u0060 的计算是有效的，可以复用已验证的 \u0060x\u0060 值。\n\n### 第二步：计算 \u0060z\u0060\n根据定义 \u0060z = y + r\u0060，我们已知 \u0060y = 56\u0060 和 \u0060r = 24\u0060，因此：\n\n$$\nz = 56 + 24 = 80\n$$\n\n### 最终答案：\n80"|
|T1_support_before_fault_E__VersionFrame|main|T1/E|80|None / False|True/False|102|"{\n  \"candidate_derivations\": [\n    {\n      \"variable\": \"y\",\n      \"expression\": \"3*18+2\",\n      \"value\": 56,\n      \"status\": \"CANDIDATE\"\n    },\n    {\n      \"variable\": \"z\",\n      \"expression\": \"56+24\",\n      \"value\": 80,\n      \"status\": \"CANDIDATE\"\n    }\n  ],\n  \"final_answer\": 80\n}"|
|T2_support_before_fault_E__SharedGDirect|main|T2/E|63|63 / True|True/False|108|"根据题目规则和已核验的根值，依次计算：\n\n1. **r = 13 + 5 = 18**（已核验）  \n2. **x = 54 // 6 = 9**（复核记录确认为正确值）  \n3. **y = x * x = 9 * 9 = 81**  \n4. **z = y - r = 81 - 18 = 63**\n\n最终答案：63"|
|T2_support_before_fault_E__SharedGCompact|main|T2/E|63|63 / True|True/False|106|"根据题目规则和已认证的根值进行计算：\n\n1. **r** 的值为 18（已认证）。\n2. **x** 的值为 9（根据复核记录，已认证）。\n3. **y** 的值为 $ x \\times x = 9 \\times 9 = 81 $。\n4. **z** 的值为 $ y - r = 81 - 18 = 63 $。\n\n最终答案：63"|
|T2_support_before_fault_E__SharedGStepwise|main|T2/E|63|63 / True|True/False|307|"根据题目要求，我们需要计算变量 \u0060z\u0060 的值。首先，我们明确变量之间的依赖关系和已知的认证值。\n\n### 步骤 1：确定目标变量 \u0060z\u0060 的依赖\n根据题目定义，\u0060z = y - r\u0060，因此我们需要先计算 \u0060y\u0060 和 \u0060r\u0060 的值。\n\n- \u0060r\u0060 的值已经认证为 18（来自 \u006013 + 5\u0060）。\n- \u0060y\u0060 的值依赖于 \u0060x\u0060，即 \u0060y = x * x\u0060，因此我们需要先计算 \u0060x\u0060 的值。\n\n### 步骤 2：确定 \u0060x\u0060 的值\n根据题目定义，\u0060x = 54 // 6\u0060。根据复核记录，\u0060x\u0060 的值应为 9，且该值已通过外部核验。因此，\u0060x\u0060 的值为 9。\n\n### 步骤 3：计算 \u0060y\u0060 的值\n根据 \u0060y = x * x\u0060，代入 \u0060x = 9\u0060，得到：\n$$\ny = 9 * 9 = 81\n$$\n\n### 步骤 4：计算 \u0060z\u0060 的值\n根据 \u0060z = y - r\u0060，代入 \u0060y = 81\u0060 和 \u0060r = 18\u0060，得到：\n$$\nz = 81 - 18 = 63\n$$\n\n### 最终答案：\n63"|
|T2_support_before_fault_E__VersionFrame|main|T2/E|63|63 / True|True/False|419|"{\n  \"current_roots\": {\n    \"r\": {\n      \"value\": 18,\n      \"version\": 0,\n      \"status\": \"VERIFIED_ROOT\",\n      \"expression\": \"13+5\",\n      \"old_literal\": 18,\n      \"old_literal_satisfies_definition\": true\n    },\n    \"x\": {\n      \"value\": 9,\n      \"version\": 1,\n      \"status\": \"VERIFIED_ROOT\",\n      \"expression\": \"54//6\",\n      \"old_literal\": 8,\n      \"old_literal_satisfies_definition\": false\n    }\n  },\n  \"dirty_descendants\": [\n    \"y\",\n    \"z\"\n  ],\n  \"goal_support_uncertified\": [\n    \"y\",\n    \"z\"\n  ],\n  \"ready_now\": [\n    \"y\"\n  ],\n  \"symbolic_ready_plan\": [\n    {\n      \"layer\": 0,\n      \"nodes\": [\n        {\n          \"variable\": \"y\",\n          \"rule\": \"x*x\",\n          \"parents\": [\n            \"x\"\n          ]\n        }\n      ]\n    },\n    {\n      \"layer\": 1,\n      \"nodes\": [\n        {\n          \"variable\": \"z\",\n          \"rule\": \"y-r\",\n          \"parents\": [\n            \"r\",\n            \"y\"\n          ]\n        }\n      ]\n    }\n  ],\n  \"old_derived_certification\": \"UNVERIFIED\"\n}\n{\n  \"candidate_derivations\": [\n    {\n      \"variable\": \"y\",\n      \"expression\": \"x*x\",\n      \"parents\": [\n        \"x\"\n      ],\n      \"value\": 81,\n      \"status\": \"CANDIDATE\"\n    },\n    {\n      \"variable\": \"z\",\n      \"expression\": \"y-r\",\n      \"parents\": [\n        \"r\",\n        \"y\"\n      ],\n      \"value\": 63,\n      \"status\": \"CANDIDATE\"\n    }\n  ]\n}\n最终答案：63"|
|T1_support_before_fault_C__SharedGDirect|main|T1/C|80|80 / True|True/False|116|"根据题目原始定义和已核验的根值，依次计算：\n\n- $ r = 6 \\times 4 = 24 $（已核验）\n- $ x = 27 - 9 = 18 $（已核验）\n- $ y = 3 \\times x + 2 = 3 \\times 18 + 2 = 54 + 2 = 56 $\n- $ z = y + r = 56 + 24 = 80 $\n\n最终答案：80"|
|T1_support_before_fault_C__SharedGCompact|main|T1/C|80|80 / True|True/False|112|"根据题目规则和已认证的根值，依次计算：\n\n- $ r = 6 \\times 4 = 24 $（已认证）\n- $ x = 27 - 9 = 18 $（已认证）\n- $ y = 3 \\times x + 2 = 3 \\times 18 + 2 = 54 + 2 = 56 $\n- $ z = y + r = 56 + 24 = 80 $\n\n最终答案：80"|
|T1_support_before_fault_C__SharedGStepwise|main|T1/C|80|80 / True|True/False|272|"根据题目要求，我们需要计算变量 \u0060z\u0060 的值。首先，我们明确目标变量 \u0060z\u0060 的定义和依赖关系：\n\n- \u0060z = y + r\u0060\n- \u0060y = 3*x + 2\u0060\n- \u0060x = 27 - 9\u0060\n- \u0060r = 6 * 4\u0060\n\n根据已知证据和规则，我们已经验证了 \u0060r\u0060 和 \u0060x\u0060 的值：\n\n- \u0060r = 24\u0060（已验证）\n- \u0060x = 18\u0060（已验证）\n\n接下来，我们需要计算 \u0060y\u0060 的值，因为 \u0060y\u0060 是 \u0060z\u0060 的依赖项之一。根据定义：\n\n- \u0060y = 3*x + 2\u0060\n\n将已验证的 \u0060x = 18\u0060 代入：\n\n- \u0060y = 3*18 + 2 = 54 + 2 = 56\u0060\n\n现在，我们已经计算出 \u0060y = 56\u0060，虽然它未被认证，但它是基于已验证的 \u0060x\u0060 计算得出的，因此可以视为有效中间值。\n\n接下来，计算 \u0060z\u0060 的值：\n\n- \u0060z = y + r = 56 + 24 = 80\u0060\n\n因此，最终答案是：\n\n最终答案：80"|
|T1_support_before_fault_C__VersionFrame|main|T1/C|80|None / False|True/False|102|"{\n  \"candidate_derivations\": [\n    {\n      \"variable\": \"y\",\n      \"expression\": \"3*18+2\",\n      \"value\": 56,\n      \"status\": \"CANDIDATE\"\n    },\n    {\n      \"variable\": \"z\",\n      \"expression\": \"56+24\",\n      \"value\": 80,\n      \"status\": \"CANDIDATE\"\n    }\n  ],\n  \"final_answer\": 80\n}"|
|T2_support_before_fault_C__SharedGDirect|main|T2/C|63|63 / True|True/False|94|"根据题目规则和已核验的根值：\n\n- $ r = 13 + 5 = 18 $（已验证）\n- $ x = 54 // 6 = 9 $（已验证）\n- $ y = x \\times x = 9 \\times 9 = 81 $\n- $ z = y - r = 81 - 18 = 63 $\n\n最终答案：63"|

## 8. 决策与下一门槛

本轮最窄结论是：在已完成的两程序/三个相关状态上，简单共享G基线自然结束且交付正确；更长的VersionFrame没有独立质量优势，并出现两个正常EOS的格式未交付。下一步若研究格式约束或更短工作帧，须新协议、同期基线和同信息条件，不补跑本轮、不重算旧分。W/C安全性、一般合流、多布局、自然依赖、完整运行时验证及正式多数据集收益仍未建立。

不跨P0.5作准确率提升叙事，不根据PARTIAL结果选更容易状态，不把当前两个程序变成统计功效结论。原始run未变；本独立复核无GPU、远程、训练或额外生成。

完整机器审计：[INDEPENDENT_RESULT_AUDIT.json](D:/ACL/research/phase5_prototype_20261106/INDEPENDENT_RESULT_AUDIT.json)；源码：[independent_quality_result_audit.py](D:/ACL/research/phase5_prototype_20261106/independent_quality_result_audit.py)。

完整性问题：[]
