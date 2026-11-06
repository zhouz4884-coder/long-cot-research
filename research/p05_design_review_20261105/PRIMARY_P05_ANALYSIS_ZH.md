# 本轮 P0.5 五臂独立 primary 分析

状态：INDEPENDENT_CPU_PRIMARY_AUDIT_PASS

只分析本轮新 user-turn / scaffold 协议。与旧 P0 分数的差异不能解释为方法提升；不自动判 induction、内部跳步或旧数字来源。

计划 16 题；实际 case 记录 16；五臂 primary 配对完整 16；完整诊断 8。
primary 不要求诊断完成；未解析输出在完整 primary 分母内记不正确，不按格式筛样。

## 1. Primary 全部配对与 E/C/W

| 臂 | 全部 正确/n（解析） | E | C | W |
|---|---|---|---|---|
|FullDirect|8/16（16）|0/8（8）|4/4（4）|4/4（4）|
|FullOneLine|11/16（12）|5/8（5）|3/4（3）|3/4（4）|
|WholeEarlyDirect|0/16（16）|0/8（8）|0/4（4）|0/4（4）|
|WholeEarlyOneLine|12/16（14）|6/8（6）|3/4（4）|3/4（4）|
|WholeLateOneLine|8/16（11）|4/8（4）|2/4（3）|2/4（4）|

### 逐条读原文后的解释约束（不改主分）

- 大正交互为9/16=56.25个百分点，但WholeEarlyDirect为0/16；联合臂12/16相对FullOneLine11/16仅净多1题。不能把该交互读成56.25个百分点的联合方法收益或独立机制互补。
- FullOneLine→WholeEarlyOneLine修复E07/C04，损害C03。E07与C04的FullOneLine已分别显示z=37、z=20，但64-token cap截在最终答案标签，冻结parser为null；Early更短地交付了最终标记。它们是本指标上的预算/格式完成差异，尚非已证实纠正错误算术或旧值复制。
- C03的FullOneLine交付最终30正确，而WholeEarlyOneLine交付56错误（均eos）。这是联合臂相对FullOneLine的真实已交付答案损害，不能被两项格式修复掩盖。
- E01三个OneLine都已经显示z=30，但截在最终答案标签；冻结primary仍不正确，不事后改分。E08没有完成82的RHS，不能补算后赋分。
- W04三个OneLine均在64-token cap结束于算式中的80；冻结parser提取80并记错。后续可能是否继续减1未知，不能称已证明永久算错，也不能假设它会自行完成79。
- WholeLateOneLine→WholeEarlyOneLine四项修复中，E04/E07/C04源于Late被cap且格式未解析；W03是已交付49→121。它支持这些冻结条件下的输出差异，不自动识别induction、隐状态进度指针或旧数来源。
- 多数OneLine可见文本从原题P的x定义重新展开，再写y/z；本轮不支持必然复制旧y的叙事。省写步骤或某个数字签名本身也不证明内部跳步。
- 诊断只完成固定顺序前8题（E01/C01/W01/E02/E03/C02/W02/E04）：E4/C2/W2，每臂Y和Z各8上下文；不能把这些条件probe外推为16题的自然中间信念。
- 完整控制bundle仅E01/C01/W01，其余13题没有被标成完整控制PASS。全部primary16题×5臂仍完整，diagnostic timeout不改变primary分母。
- 本轮有新的user-turn、Direct固定scaffold和OneLine读出协议，禁止借旧P0分数声称方法提升。所有数值比较限于本轮。

## 2. 本轮配对修复/伤害

未解析→正确可能包含格式修复，不能自动解读为数学机制修复。

| 对比 | 组 | n | 修复 ID | 伤害 ID | 净变化 |
|---|---|---:|---|---|---:|
|FullDirect__to__FullOneLine|all|16|E02,E03,E04,E05,E06|C04,W04|3|
|FullDirect__to__FullOneLine|E|8|E02,E03,E04,E05,E06|无|5|
|FullDirect__to__FullOneLine|C|4|无|C04|-1|
|FullDirect__to__FullOneLine|W|4|无|W04|-1|
|WholeEarlyDirect__to__WholeEarlyOneLine|all|16|C01,W01,E02,E03,C02,W02,E04,E05,W03,E06,E07,C04|无|12|
|WholeEarlyDirect__to__WholeEarlyOneLine|E|8|E02,E03,E04,E05,E06,E07|无|6|
|WholeEarlyDirect__to__WholeEarlyOneLine|C|4|C01,C02,C04|无|3|
|WholeEarlyDirect__to__WholeEarlyOneLine|W|4|W01,W02,W03|无|3|
|FullDirect__to__WholeEarlyDirect|all|16|无|C01,W01,C02,W02,C03,W03,C04,W04|-8|
|FullDirect__to__WholeEarlyDirect|E|8|无|无|0|
|FullDirect__to__WholeEarlyDirect|C|4|无|C01,C02,C03,C04|-4|
|FullDirect__to__WholeEarlyDirect|W|4|无|W01,W02,W03,W04|-4|
|FullOneLine__to__WholeEarlyOneLine|all|16|E07,C04|C03|1|
|FullOneLine__to__WholeEarlyOneLine|E|8|E07|无|1|
|FullOneLine__to__WholeEarlyOneLine|C|4|C04|C03|0|
|FullOneLine__to__WholeEarlyOneLine|W|4|无|无|0|
|FullOneLine__to__WholeLateOneLine|all|16|无|E04,C03,W03|-3|
|FullOneLine__to__WholeLateOneLine|E|8|无|E04|-1|
|FullOneLine__to__WholeLateOneLine|C|4|无|C03|-1|
|FullOneLine__to__WholeLateOneLine|W|4|无|W03|-1|
|WholeLateOneLine__to__WholeEarlyOneLine|all|16|E04,W03,E07,C04|无|4|
|WholeLateOneLine__to__WholeEarlyOneLine|E|8|E04,E07|无|2|
|WholeLateOneLine__to__WholeEarlyOneLine|C|4|C04|无|1|
|WholeLateOneLine__to__WholeEarlyOneLine|W|4|W03|无|1|

## 3. WholeEarly×OneLine 描述性交互

对比 = Acc(WholeEarlyOneLine)−Acc(WholeEarlyDirect)−Acc(FullOneLine)+Acc(FullDirect)。它是同一固定病例集上的策略交互，不证明错误来源正交、互补机制或 induction-head。

| 组 | n | 对比和 | 平均准确率对比 |
|---|---:|---:|---:|
|all|16|9|0.5625|
|E|8|1|0.125|
|C|4|4|1.0|
|W|4|4|1.0|

## 4. 原始自由输出：按实际完成量全部列出

共 80 条，不默认已有 80 条。JSON 字符串保留换行/标点；scaffold 单列，冻结 parser 仅接收 free.text。

| case | 组 | 臂 | 固定 scaffold | 原始 free.text（JSON） | 抽取值/方法 | 正确 |
|---|---|---|---|---|---|---|
|E01|E|FullDirect|"最终答案："|"33"|33 / single_integer_optional_terminal_period|False|
|E01|E|FullOneLine|""|"x = 18 - 7 = 11  \ny = 3 * x + 2 = 3 * 11 + 2 = 33 + 2 = 35  \nz = y - 5 = 35 - 5 = 30  \n\n最终答案"|None / unresolved|False|
|E01|E|WholeEarlyDirect|"最终答案："|"11"|11 / single_integer_optional_terminal_period|False|
|E01|E|WholeEarlyOneLine|""|"x = 18 - 7 = 11  \ny = 3 * x + 2 = 3 * 11 + 2 = 33 + 2 = 35  \nz = y - 5 = 35 - 5 = 30  \n\n最终答案"|None / unresolved|False|
|E01|E|WholeLateOneLine|""|"x = 18 - 7 = 11  \ny = 3 * x + 2 = 3 * 11 + 2 = 33 + 2 = 35  \nz = y - 5 = 35 - 5 = 30  \n\n最终答案"|None / unresolved|False|
|C01|C|FullDirect|"最终答案："|"31"|31 / single_integer_optional_terminal_period|True|
|C01|C|FullOneLine|""|"x = 16 - 9 = 7  \ny = 4 * x = 4 * 7 = 28  \nz = y + 3 = 28 + 3 = 31  \n\n最终答案：31"|31 / explicit_final_marker_terminal_integer|True|
|C01|C|WholeEarlyDirect|"最终答案："|"7"|7 / single_integer_optional_terminal_period|False|
|C01|C|WholeEarlyOneLine|""|"x = 16 - 9 = 7  \ny = 4 * x = 4 * 7 = 28  \nz = y + 3 = 28 + 3 = 31  \n\n最终答案：31"|31 / explicit_final_marker_terminal_integer|True|
|C01|C|WholeLateOneLine|""|"x = 16 - 9 = 7  \ny = 4 * x = 4 * 7 = 28  \nz = y + 3 = 28 + 3 = 31  \n\n最终答案：31"|31 / explicit_final_marker_terminal_integer|True|
|W01|W|FullDirect|"最终答案："|"28"|28 / single_integer_optional_terminal_period|True|
|W01|W|FullOneLine|""|"x = 15 - 6 = 9  \ny = 3 * x = 27  \nz = y + 1 = 28  \n\n最终答案：28"|28 / explicit_final_marker_terminal_integer|True|
|W01|W|WholeEarlyDirect|"最终答案："|"11"|11 / single_integer_optional_terminal_period|False|
|W01|W|WholeEarlyOneLine|""|"x = 15 - 6 = 9  \ny = 3 * x = 3 * 9 = 27  \nz = y + 1 = 27 + 1 = 28  \n\n最终答案：28"|28 / explicit_final_marker_terminal_integer|True|
|W01|W|WholeLateOneLine|""|"x = 15 - 6 = 9  \ny = 3 * x = 3 * 9 = 27  \nz = y + 1 = 27 + 1 = 28  \n\n最终答案：28"|28 / explicit_final_marker_terminal_integer|True|
|E02|E|FullDirect|"最终答案："|"30"|30 / single_integer_optional_terminal_period|False|
|E02|E|FullOneLine|""|"x = 7 * 4 = 28  \ny = x - 9 = 28 - 9 = 19  \nz = 2 * y = 2 * 19 = 38  \n\n最终答案：38"|38 / explicit_final_marker_terminal_integer|True|
|E02|E|WholeEarlyDirect|"最终答案："|"28"|28 / single_integer_optional_terminal_period|False|
|E02|E|WholeEarlyOneLine|""|"x = 7 * 4 = 28  \ny = x - 9 = 28 - 9 = 19  \nz = 2 * y = 2 * 19 = 38  \n\n最终答案：38"|38 / explicit_final_marker_terminal_integer|True|
|E02|E|WholeLateOneLine|""|"x = 7 * 4 = 28  \ny = x - 9 = 28 - 9 = 19  \nz = 2 * y = 2 * 19 = 38  \n\n最终答案：38"|38 / explicit_final_marker_terminal_integer|True|
|E03|E|FullDirect|"最终答案："|"70"|70 / single_integer_optional_terminal_period|False|
|E03|E|FullOneLine|""|"x = 45 // 5 = 9  \ny = x * x = 9 * 9 = 81  \nz = y + 6 = 81 + 6 = 87  \n\n最终答案：87"|87 / explicit_final_marker_terminal_integer|True|
|E03|E|WholeEarlyDirect|"最终答案："|"81"|81 / single_integer_optional_terminal_period|False|
|E03|E|WholeEarlyOneLine|""|"x = 45 // 5 = 9  \ny = x * x = 9 * 9 = 81  \nz = y + 6 = 81 + 6 = 87  \n\n最终答案：87"|87 / explicit_final_marker_terminal_integer|True|
|E03|E|WholeLateOneLine|""|"x = 45 // 5 = 9  \ny = x * x = 9 * 9 = 81  \nz = y + 6 = 81 + 6 = 87  \n\n最终答案：87"|87 / explicit_final_marker_terminal_integer|True|
|C02|C|FullDirect|"最终答案："|"16"|16 / single_integer_optional_terminal_period|True|
|C02|C|FullOneLine|""|"x = 8 * 3 = 24  \ny = 24 // 4 = 6  \nz = 3 * 6 - 2 = 16  \n\n最终答案：16"|16 / explicit_final_marker_terminal_integer|True|
|C02|C|WholeEarlyDirect|"最终答案："|"24"|24 / single_integer_optional_terminal_period|False|
|C02|C|WholeEarlyOneLine|""|"x = 8 * 3 = 24  \ny = 24 // 4 = 6  \nz = 3 * 6 - 2 = 16  \n\n最终答案：16"|16 / explicit_final_marker_terminal_integer|True|
|C02|C|WholeLateOneLine|""|"x = 8 * 3 = 24  \ny = 24 // 4 = 6  \nz = 3 * 6 - 2 = 16  \n\n最终答案：16"|16 / explicit_final_marker_terminal_integer|True|
|W02|W|FullDirect|"最终答案："|"21"|21 / single_integer_optional_terminal_period|True|
|W02|W|FullOneLine|""|"x = 9 * 4 = 36  \ny = 36 // 4 = 9  \nz = 2 * 9 + 3 = 21  \n\n最终答案：21"|21 / explicit_final_marker_terminal_integer|True|
|W02|W|WholeEarlyDirect|"最终答案："|"32"|32 / single_integer_optional_terminal_period|False|
|W02|W|WholeEarlyOneLine|""|"x = 9 * 4 = 36  \ny = 36 // 4 = 9  \nz = 2 * 9 + 3 = 21  \n\n最终答案：21"|21 / explicit_final_marker_terminal_integer|True|
|W02|W|WholeLateOneLine|""|"x = 9 * 4 = 36  \ny = 36 // 4 = 9  \nz = 2 * 9 + 3 = 21  \n\n最终答案：21"|21 / explicit_final_marker_terminal_integer|True|
|E04|E|FullDirect|"最终答案："|"41"|41 / single_integer_optional_terminal_period|False|
|E04|E|FullOneLine|""|"x = 13 + 8 = 21  \ny = 2 * 21 - 3 = 39  \nz = 39 + 4 = 43  \n\n最终答案：43"|43 / explicit_final_marker_terminal_integer|True|
|E04|E|WholeEarlyDirect|"最终答案："|"21"|21 / single_integer_optional_terminal_period|False|
|E04|E|WholeEarlyOneLine|""|"x = 13 + 8 = 21  \ny = 2 * 21 - 3 = 39  \nz = 39 + 4 = 43  \n\n最终答案：43"|43 / explicit_final_marker_terminal_integer|True|
|E04|E|WholeLateOneLine|""|"x = 13 + 8 = 21  \ny = 2 * x - 3 = 2 * 21 - 3 = 42 - 3 = 39  \nz = y + 4 = 39 + 4 = 43  \n\n最终答案"|None / unresolved|False|
|E05|E|FullDirect|"最终答案："|"23"|23 / single_integer_optional_terminal_period|False|
|E05|E|FullOneLine|""|"x = 6 * 6 = 36  \ny = 36 // 6 = 6  \nz = 5 * 6 - 2 = 28  \n\n最终答案：28"|28 / explicit_final_marker_terminal_integer|True|
|E05|E|WholeEarlyDirect|"最终答案："|"36"|36 / single_integer_optional_terminal_period|False|
|E05|E|WholeEarlyOneLine|""|"x = 6 * 6 = 36  \ny = 36 // 6 = 6  \nz = 5 * 6 - 2 = 28  \n\n最终答案：28"|28 / explicit_final_marker_terminal_integer|True|
|E05|E|WholeLateOneLine|""|"x = 6 * 6 = 36  \ny = 36 // 6 = 6  \nz = 5 * 6 - 2 = 28  \n\n最终答案：28"|28 / explicit_final_marker_terminal_integer|True|
|C03|C|FullDirect|"最终答案："|"30"|30 / single_integer_optional_terminal_period|True|
|C03|C|FullOneLine|""|"x = 35 // 5  \ny = x + 8  \nz = 2 * y  \n\n最终答案：30"|30 / explicit_final_marker_terminal_integer|True|
|C03|C|WholeEarlyDirect|"最终答案："|"70"|70 / single_integer_optional_terminal_period|False|
|C03|C|WholeEarlyOneLine|""|"x = 35 // 5  \ny = x + 8  \nz = 2 * y  \n\n最终答案：56"|56 / explicit_final_marker_terminal_integer|False|
|C03|C|WholeLateOneLine|""|"x = 35 // 5  \ny = x + 8  \nz = 2 * y  \n\n最终答案：76"|76 / explicit_final_marker_terminal_integer|False|
|W03|W|FullDirect|"最终答案："|"121"|121 / single_integer_optional_terminal_period|True|
|W03|W|FullOneLine|""|"x = 42 // 7 = 6  \ny = x + 5 = 6 + 5 = 11  \nz = y * y = 11 * 11 = 121  \n\n最终答案：121"|121 / explicit_final_marker_terminal_integer|True|
|W03|W|WholeEarlyDirect|"最终答案："|"49"|49 / single_integer_optional_terminal_period|False|
|W03|W|WholeEarlyOneLine|""|"x = 42 // 7 = 6  \ny = x + 5 = 6 + 5 = 11  \nz = y * y = 11 * 11 = 121  \n\n最终答案：121"|121 / explicit_final_marker_terminal_integer|True|
|W03|W|WholeLateOneLine|""|"x = 42 // 7  \ny = x + 5  \nz = y * y  \n\n最终答案：49"|49 / explicit_final_marker_terminal_integer|False|
|E06|E|FullDirect|"最终答案："|"116"|116 / single_integer_optional_terminal_period|False|
|E06|E|FullOneLine|""|"x = 50 - 17 = 33  \ny = x + 7 = 40  \nz = 3 * y - 1 = 119  \n\n最终答案：119"|119 / explicit_final_marker_terminal_integer|True|
|E06|E|WholeEarlyDirect|"最终答案："|"33"|33 / single_integer_optional_terminal_period|False|
|E06|E|WholeEarlyOneLine|""|"x = 50 - 17 = 33  \ny = x + 7 = 33 + 7 = 40  \nz = 3 * y - 1 = 3 * 40 - 1 = 120 - 1 = 119"|119 / last_line_complete_equation_chain_terminal_integer|True|
|E06|E|WholeLateOneLine|""|"x = 50 - 17 = 33  \ny = x + 7 = 33 + 7 = 40  \nz = 3 * y - 1 = 3 * 40 - 1 = 120 - 1 = 119"|119 / last_line_complete_equation_chain_terminal_integer|True|
|E07|E|FullDirect|"最终答案："|"33"|33 / single_integer_optional_terminal_period|False|
|E07|E|FullOneLine|""|"x = (9 + 3) * 2 = 12 * 2 = 24  \ny = 2 * x = 2 * 24 = 48  \nz = y - 11 = 48 - 11 = 37  \n\n最终答案："|None / unresolved|False|
|E07|E|WholeEarlyDirect|"最终答案："|"24"|24 / single_integer_optional_terminal_period|False|
|E07|E|WholeEarlyOneLine|""|"x = (9 + 3) * 2 = 24  \ny = 2 * x = 48  \nz = y - 11 = 37  \n\n最终答案：37"|37 / explicit_final_marker_terminal_integer|True|
|E07|E|WholeLateOneLine|""|"x = (9 + 3) * 2 = 12 * 2 = 24  \ny = 2 * x = 2 * 24 = 48  \nz = y - 11 = 48 - 11 = 37  \n\n最终答案："|None / unresolved|False|
|C04|C|FullDirect|"最终答案："|"20"|20 / single_integer_optional_terminal_period|True|
|C04|C|FullOneLine|""|"x = 11 + 6 = 17  \ny = 2 * x - 5 = 2 * 17 - 5 = 34 - 5 = 29  \nz = y - 9 = 29 - 9 = 20  \n\n最终答案"|None / unresolved|False|
|C04|C|WholeEarlyDirect|"最终答案："|"17"|17 / single_integer_optional_terminal_period|False|
|C04|C|WholeEarlyOneLine|""|"x = 11 + 6 = 17  \ny = 2 * 17 - 5 = 34 - 5 = 29  \nz = 29 - 9 = 20  \n\n最终答案：20"|20 / explicit_final_marker_terminal_integer|True|
|C04|C|WholeLateOneLine|""|"x = 11 + 6 = 17  \ny = 2 * x - 5 = 2 * 17 - 5 = 34 - 5 = 29  \nz = y - 9 = 29 - 9 = 20  \n\n最终答案"|None / unresolved|False|
|W04|W|FullDirect|"最终答案："|"79"|79 / single_integer_optional_terminal_period|True|
|W04|W|FullOneLine|""|"x = (8 + 5) * 2 = 13 * 2 = 26  \ny = x - 6 = 26 - 6 = 20  \nz = 4 * y - 1 = 4 * 20 - 1 = 80"|80 / last_line_complete_equation_chain_terminal_integer|False|
|W04|W|WholeEarlyDirect|"最终答案："|"48"|48 / single_integer_optional_terminal_period|False|
|W04|W|WholeEarlyOneLine|""|"x = (8 + 5) * 2 = 13 * 2 = 26  \ny = x - 6 = 26 - 6 = 20  \nz = 4 * y - 1 = 4 * 20 - 1 = 80"|80 / last_line_complete_equation_chain_terminal_integer|False|
|W04|W|WholeLateOneLine|""|"x = (8 + 5) * 2 = 13 * 2 = 26  \ny = x - 6 = 26 - 6 = 20  \nz = 4 * y - 1 = 4 * 20 - 1 = 80"|80 / last_line_complete_equation_chain_terminal_integer|False|
|E08|E|FullDirect|"最终答案："|"65"|65 / single_integer_optional_terminal_period|False|
|E08|E|FullOneLine|""|"x = 64 // 8 + 5 = 8 + 5 = 13  \ny = x - 4 = 13 - 4 = 9  \nz = y * y + 1 = 9 * 9 + 1 = 81 + 1 ="|None / unresolved|False|
|E08|E|WholeEarlyDirect|"最终答案："|"170"|170 / single_integer_optional_terminal_period|False|
|E08|E|WholeEarlyOneLine|""|"x = 64 // 8 + 5 = 8 + 5 = 13  \ny = x - 4 = 13 - 4 = 9  \nz = y * y + 1 = 9 * 9 + 1 = 81 + 1 ="|None / unresolved|False|
|E08|E|WholeLateOneLine|""|"x = 64 // 8 + 5 = 8 + 5 = 13  \ny = x - 4 = 13 - 4 = 9  \nz = y * y + 1 = 9 * 9 + 1 = 81 + 1 ="|None / unresolved|False|

## 5. 格式未解析、部分/未运行

未解析：[('E01', 'FullOneLine'), ('E01', 'WholeEarlyOneLine'), ('E01', 'WholeLateOneLine'), ('E04', 'WholeLateOneLine'), ('E07', 'FullOneLine'), ('E07', 'WholeLateOneLine'), ('C04', 'FullOneLine'), ('C04', 'WholeLateOneLine'), ('E08', 'FullOneLine'), ('E08', 'WholeEarlyOneLine'), ('E08', 'WholeLateOneLine')]

仅诊断未完整：['E05', 'C03', 'W03', 'E06', 'E07', 'C04', 'W04', 'E08']

未开始：[]

各臂可用自由输出：{'FullDirect': 16, 'FullOneLine': 16, 'WholeEarlyDirect': 16, 'WholeEarlyOneLine': 16, 'WholeLateOneLine': 16}

| 臂 | 新生成token合计（记录值） | 64-token cap ID | cap且未解析 | cap已解析且不正确 |
|---|---:|---|---|---|
|FullDirect|50|无|无|无|
|FullOneLine|833|E01,E07,C04,W04,E08|E01,E07,C04,E08|W04|
|WholeEarlyDirect|48|无|无|无|
|WholeEarlyOneLine|835|E01,E06,W04,E08|E01,E08|W04|
|WholeLateOneLine|852|E01,E04,E06,E07,C04,W04,E08|E01,E04,E07,C04,E08|W04|

cap不一律等于未解析：E06式完整末行可以被冻结语法抽取；在部分算式处截断也可能返回一个不正确数字。不能补写后缀、事后增加token或换parser救分。

## 6. 条件 probe：全部可用 continuation logP

这些 probe 在自由生成前状态上使用独立强制前缀，实际成本另计；不是生成 OneLine 后读出的信念。Z 使用冻结最终答案前缀；Y 使用 `y =`。每个完整 continuation 包含末尾换行，logP 为未作长度归一化的自回归条件和。首 token 列仅是首 token 边际，不能当作完整候选概率。角色别名共用同一候选，不归一化为四类置信度。W 的 revision-consistent 不是 trusted。

每个上下文的完整 user 指令、scaffold、prefix token hash/IDs 与绝对位置保存在 JSON 的 all_available_probes.context。

| case | 臂 | family / scaffold | context ID前12位 | 角色别名 | continuation JSON | token IDs | 完整 logP | 首token logP |
|---|---|---|---|---|---|---|---:|---:|
|E01|FullDirect|z / "最终答案："|4a0a80d9cd45|trusted_final,revision_consistent_final|"30\n"|[18, 15, 198]|-41.28910827636719|0.0|
|E01|FullDirect|z / "最终答案："|4a0a80d9cd45|old_final|"33\n"|[18, 18, 198]|-17.914079666137695|0.0|
|E01|FullDirect|z / "最终答案："|4a0a80d9cd45|skip_signature|"6\n"|[21, 198]|-41.0722017288208|-25.578125|
|E01|FullDirect|y / "y ="|20f48e47e91e|trusted_y,revision_consistent_y|"35\n"|[18, 20, 198]|-59.4510383605957|-24.75|
|E01|FullDirect|y / "y ="|20f48e47e91e|old_y|"38\n"|[18, 23, 198]|-55.99648380279541|-24.75|
|E01|FullDirect|y / "y ="|20f48e47e91e|root_misbind|"11\n"|[16, 16, 198]|-44.874510169029236|-34.1796875|
|E01|FullOneLine|z / "最终答案："|826c765b7993|trusted_final,revision_consistent_final|"30\n"|[18, 15, 198]|-33.85956846244517|-0.00016866691294126213|
|E01|FullOneLine|z / "最终答案："|826c765b7993|old_final|"33\n"|[18, 18, 198]|-15.843921766354441|-0.00016866691294126213|
|E01|FullOneLine|z / "最终答案："|826c765b7993|skip_signature|"6\n"|[21, 198]|-36.1768856048584|-21.937667846679688|
|E01|FullOneLine|y / "y ="|486ea504b326|trusted_y,revision_consistent_y|"35\n"|[18, 20, 198]|-70.42479991912842|-33.765625|
|E01|FullOneLine|y / "y ="|486ea504b326|old_y|"38\n"|[18, 23, 198]|-67.33646488189697|-33.765625|
|E01|FullOneLine|y / "y ="|486ea504b326|root_misbind|"11\n"|[16, 16, 198]|-55.9595832824707|-45.328125|
|E01|WholeEarlyDirect|z / "最终答案："|4a0a80d9cd45|trusted_final,revision_consistent_final|"30\n"|[18, 15, 198]|-42.795937061309814|-21.09375|
|E01|WholeEarlyDirect|z / "最终答案："|4a0a80d9cd45|old_final|"33\n"|[18, 18, 198]|-40.38185381889343|-21.09375|
|E01|WholeEarlyDirect|z / "最终答案："|4a0a80d9cd45|skip_signature|"6\n"|[21, 198]|-39.33811283111572|-23.34375|
|E01|WholeEarlyDirect|y / "y ="|20f48e47e91e|trusted_y,revision_consistent_y|"35\n"|[18, 20, 198]|-77.08978748321533|-33.359375|
|E01|WholeEarlyDirect|y / "y ="|20f48e47e91e|old_y|"38\n"|[18, 23, 198]|-78.84950923919678|-33.359375|
|E01|WholeEarlyDirect|y / "y ="|20f48e47e91e|root_misbind|"11\n"|[16, 16, 198]|-63.3209691811353|-46.4453125|
|E01|WholeEarlyOneLine|z / "最终答案："|826c765b7993|trusted_final,revision_consistent_final|"30\n"|[18, 15, 198]|-30.697147369384766|-10.9124174118042|
|E01|WholeEarlyOneLine|z / "最终答案："|826c765b7993|old_final|"33\n"|[18, 18, 198]|-28.868998527526855|-10.9124174118042|
|E01|WholeEarlyOneLine|z / "最终答案："|826c765b7993|skip_signature|"6\n"|[21, 198]|-25.72544288635254|-10.7249174118042|
|E01|WholeEarlyOneLine|y / "y ="|486ea504b326|trusted_y,revision_consistent_y|"35\n"|[18, 20, 198]|-76.63922119140625|-39.25|
|E01|WholeEarlyOneLine|y / "y ="|486ea504b326|old_y|"38\n"|[18, 23, 198]|-78.08804321289062|-39.25|
|E01|WholeEarlyOneLine|y / "y ="|486ea504b326|root_misbind|"11\n"|[16, 16, 198]|-69.13280937075615|-52.37109375|
|E01|WholeLateOneLine|z / "最终答案："|826c765b7993|trusted_final,revision_consistent_final|"30\n"|[18, 15, 198]|-33.63417291641235|-14.06311321258545|
|E01|WholeLateOneLine|z / "最终答案："|826c765b7993|old_final|"33\n"|[18, 18, 198]|-32.07162642478943|-14.06311321258545|
|E01|WholeLateOneLine|z / "最终答案："|826c765b7993|skip_signature|"6\n"|[21, 198]|-29.407492637634277|-14.28186321258545|
|E01|WholeLateOneLine|y / "y ="|486ea504b326|trusted_y,revision_consistent_y|"35\n"|[18, 20, 198]|-70.68725109100342|-38.9375|
|E01|WholeLateOneLine|y / "y ="|486ea504b326|old_y|"38\n"|[18, 23, 198]|-72.87597560882568|-38.9375|
|E01|WholeLateOneLine|y / "y ="|486ea504b326|root_misbind|"11\n"|[16, 16, 198]|-59.12490749359131|-51.6171875|
|C01|FullDirect|z / "最终答案："|98d12d3ae781|trusted_final,old_final,revision_consistent_final|"31\n"|[18, 16, 198]|-18.4531307220459|0.0|
|C01|FullDirect|z / "最终答案："|98d12d3ae781|skip_signature|"10\n"|[16, 15, 198]|-45.024728775024414|-22.9375|
|C01|FullDirect|y / "y ="|d748369ee147|trusted_y,old_y,revision_consistent_y|"28\n"|[17, 23, 198]|-59.85026633739437|-46.421875|
|C01|FullDirect|y / "y ="|d748369ee147|root_misbind|"7\n"|[22, 198]|-67.17770767211914|-50.70703125|
|C01|FullOneLine|z / "最终答案："|968768a826f1|trusted_final,old_final,revision_consistent_final|"31\n"|[18, 16, 198]|-15.671954151985119|-7.724463648628443e-05|
|C01|FullOneLine|z / "最终答案："|968768a826f1|skip_signature|"10\n"|[16, 15, 198]|-41.26576375961304|-21.765701293945312|
|C01|FullOneLine|y / "y ="|b962e1311b97|trusted_y,old_y,revision_consistent_y|"28\n"|[17, 23, 198]|-60.68283748626709|-53.125|
|C01|FullOneLine|y / "y ="|b962e1311b97|root_misbind|"7\n"|[22, 198]|-77.34505844116211|-58.160888671875|
|C01|WholeEarlyDirect|z / "最终答案："|98d12d3ae781|trusted_final,old_final,revision_consistent_final|"31\n"|[18, 16, 198]|-40.543864727020264|-17.53125|
|C01|WholeEarlyDirect|z / "最终答案："|98d12d3ae781|skip_signature|"10\n"|[16, 15, 198]|-40.02413368225098|-19.03125|
|C01|WholeEarlyDirect|y / "y ="|d748369ee147|trusted_y,old_y,revision_consistent_y|"28\n"|[17, 23, 198]|-62.77698028087457|-50.9765625|
|C01|WholeEarlyDirect|y / "y ="|d748369ee147|root_misbind|"7\n"|[22, 198]|-71.05526351928711|-55.9775390625|
|C01|WholeEarlyOneLine|z / "最终答案："|968768a826f1|trusted_final,old_final,revision_consistent_final|"31\n"|[18, 16, 198]|-30.235260009765625|-8.259740829467773|
|C01|WholeEarlyOneLine|z / "最终答案："|968768a826f1|skip_signature|"10\n"|[16, 15, 198]|-29.913389682769775|-12.040990829467773|
|C01|WholeEarlyOneLine|y / "y ="|b962e1311b97|trusted_y,old_y,revision_consistent_y|"28\n"|[17, 23, 198]|-66.58598446827273|-54.6171875|
|C01|WholeEarlyOneLine|y / "y ="|b962e1311b97|root_misbind|"7\n"|[22, 198]|-77.46283912658691|-60.099609375|
|C01|WholeLateOneLine|z / "最终答案："|968768a826f1|trusted_final,old_final,revision_consistent_final|"31\n"|[18, 16, 198]|-26.780001938343048|-0.607593834400177|
|C01|WholeLateOneLine|z / "最终答案："|968768a826f1|skip_signature|"10\n"|[16, 15, 198]|-36.50993204116821|-7.795094013214111|
|C01|WholeLateOneLine|y / "y ="|b962e1311b97|trusted_y,old_y,revision_consistent_y|"28\n"|[17, 23, 198]|-66.9632366503065|-55.244140625|
|C01|WholeLateOneLine|y / "y ="|b962e1311b97|root_misbind|"7\n"|[22, 198]|-74.61167049407959|-60.986328125|
|W01|FullDirect|z / "最终答案："|ccbfcbcd823c|trusted_final,old_final|"28\n"|[17, 23, 198]|-17.562570571899414|0.0|
|W01|FullDirect|z / "最终答案："|ccbfcbcd823c|revision_consistent_final|"31\n"|[18, 16, 198]|-37.84249956160784|-20.21875|
|W01|FullDirect|z / "最终答案："|ccbfcbcd823c|skip_signature|"11\n"|[16, 16, 198]|-46.73755931854248|-20.4375|
|W01|FullDirect|y / "y ="|e8b50e115856|trusted_y,old_y|"27\n"|[17, 22, 198]|-51.6951141981408|-39.703125|
|W01|FullDirect|y / "y ="|e8b50e115856|revision_consistent_y|"30\n"|[18, 15, 198]|-64.13445663452148|-28.265625|
|W01|FullDirect|y / "y ="|e8b50e115856|root_misbind|"10\n"|[16, 15, 198]|-56.085074096918106|-38.7421875|
|W01|FullOneLine|z / "最终答案："|7b1504b08e33|trusted_final,old_final|"28\n"|[17, 23, 198]|-15.562889503706629|-0.0003800861886702478|
|W01|FullOneLine|z / "最终答案："|7b1504b08e33|revision_consistent_final|"31\n"|[18, 16, 198]|-32.23840617761016|-17.53162956237793|
|W01|FullOneLine|z / "最终答案："|7b1504b08e33|skip_signature|"11\n"|[16, 16, 198]|-42.557148933410645|-18.78162956237793|
|W01|FullOneLine|y / "y ="|c35584b6874b|trusted_y,old_y|"27\n"|[17, 22, 198]|-57.52050878293812|-49.8828125|
|W01|FullOneLine|y / "y ="|c35584b6874b|revision_consistent_y|"30\n"|[18, 15, 198]|-65.37006616592407|-37.046875|
|W01|FullOneLine|y / "y ="|c35584b6874b|root_misbind|"10\n"|[16, 15, 198]|-67.16177201271057|-49.140625|
|W01|WholeEarlyDirect|z / "最终答案："|ccbfcbcd823c|trusted_final,old_final|"28\n"|[17, 23, 198]|-37.92724418640137|-12.437518119812012|
|W01|WholeEarlyDirect|z / "最终答案："|ccbfcbcd823c|revision_consistent_final|"31\n"|[18, 16, 198]|-28.546908974574762|-11.250018119812012|
|W01|WholeEarlyDirect|z / "最终答案："|ccbfcbcd823c|skip_signature|"11\n"|[16, 16, 198]|-17.70008587821394|-1.7762025890988298e-05|
|W01|WholeEarlyDirect|y / "y ="|e8b50e115856|trusted_y,old_y|"27\n"|[17, 22, 198]|-58.235958099365234|-44.8046875|
|W01|WholeEarlyDirect|y / "y ="|e8b50e115856|revision_consistent_y|"30\n"|[18, 15, 198]|-64.8419189453125|-31.65625|
|W01|WholeEarlyDirect|y / "y ="|e8b50e115856|root_misbind|"10\n"|[16, 15, 198]|-62.49511591717601|-43.546875|
|W01|WholeEarlyOneLine|z / "最终答案："|7b1504b08e33|trusted_final,old_final|"28\n"|[17, 23, 198]|-30.82068920135498|-8.599173545837402|
|W01|WholeEarlyOneLine|z / "最终答案："|7b1504b08e33|revision_consistent_final|"31\n"|[18, 16, 198]|-21.9336138474755|-7.599173545837402|
|W01|WholeEarlyOneLine|z / "最终答案："|7b1504b08e33|skip_signature|"11\n"|[16, 16, 198]|-15.66417670249939|-0.5366733074188232|
|W01|WholeEarlyOneLine|y / "y ="|c35584b6874b|trusted_y,old_y|"27\n"|[17, 22, 198]|-62.385908365249634|-53.28125|
|W01|WholeEarlyOneLine|y / "y ="|c35584b6874b|revision_consistent_y|"30\n"|[18, 15, 198]|-70.10267496109009|-39.890625|
|W01|WholeEarlyOneLine|y / "y ="|c35584b6874b|root_misbind|"10\n"|[16, 15, 198]|-71.32359057664871|-52.4921875|
|W01|WholeLateOneLine|z / "最终答案："|7b1504b08e33|trusted_final,old_final|"28\n"|[17, 23, 198]|-24.972620964050293|-3.6067214012145996|
|W01|WholeLateOneLine|z / "最终答案："|7b1504b08e33|revision_consistent_final|"31\n"|[18, 16, 198]|-19.889899695059285|-5.3879714012146|
|W01|WholeLateOneLine|z / "最终答案："|7b1504b08e33|skip_signature|"11\n"|[16, 16, 198]|-20.35305353999138|-0.4192213714122772|
|W01|WholeLateOneLine|y / "y ="|c35584b6874b|trusted_y,old_y|"27\n"|[17, 22, 198]|-65.37411522865295|-55.6796875|
|W01|WholeLateOneLine|y / "y ="|c35584b6874b|revision_consistent_y|"30\n"|[18, 15, 198]|-70.82629585266113|-41.875|
|W01|WholeLateOneLine|y / "y ="|c35584b6874b|root_misbind|"10\n"|[16, 15, 198]|-71.11513316631317|-54.4921875|
|E02|FullDirect|z / "最终答案："|4f0b478abdf7|trusted_final,revision_consistent_final|"38\n"|[18, 23, 198]|-36.7720712423324|-3.576278118089249e-07|
|E02|FullDirect|z / "最终答案："|4f0b478abdf7|old_final|"30\n"|[18, 15, 198]|-17.63287198543543|-3.576278118089249e-07|
|E02|FullDirect|z / "最终答案："|4f0b478abdf7|skip_signature|"56\n"|[20, 21, 198]|-41.26564097402388|-23.515625|
|E02|FullDirect|y / "y ="|b82955050d68|trusted_y,revision_consistent_y|"19\n"|[16, 24, 198]|-52.33292725076899|-35.093650817871094|
|E02|FullDirect|y / "y ="|b82955050d68|old_y|"15\n"|[16, 20, 198]|-54.45202970504761|-35.093650817871094|
|E02|FullDirect|y / "y ="|b82955050d68|root_misbind|"28\n"|[17, 23, 198]|-59.976882338518635|-26.999900817871094|
|E02|FullOneLine|z / "最终答案："|538d8895a4aa|trusted_final,revision_consistent_final|"38\n"|[18, 23, 198]|-32.300129742361605|-0.004786343313753605|
|E02|FullOneLine|z / "最终答案："|538d8895a4aa|old_final|"30\n"|[18, 15, 198]|-15.53604158852238|-0.004786343313753605|
|E02|FullOneLine|z / "最终答案："|538d8895a4aa|skip_signature|"56\n"|[20, 21, 198]|-34.145445227552955|-19.848535537719727|
|E02|FullOneLine|y / "y ="|d71441077624|trusted_y,revision_consistent_y|"19\n"|[16, 24, 198]|-57.93082046508789|-38.141998291015625|
|E02|FullOneLine|y / "y ="|d71441077624|old_y|"15\n"|[16, 20, 198]|-46.25094986066688|-38.141998291015625|
|E02|FullOneLine|y / "y ="|d71441077624|root_misbind|"28\n"|[17, 23, 198]|-63.870112530421466|-31.345123291015625|
|E02|WholeEarlyDirect|z / "最终答案："|4f0b478abdf7|trusted_final,revision_consistent_final|"38\n"|[18, 23, 198]|-41.61592149734497|-16.574371337890625|
|E02|WholeEarlyDirect|z / "最终答案："|4f0b478abdf7|old_final|"30\n"|[18, 15, 198]|-42.64476430416107|-16.574371337890625|
|E02|WholeEarlyDirect|z / "最终答案："|4f0b478abdf7|skip_signature|"56\n"|[20, 21, 198]|-34.957188129424935|-17.152496337890625|
|E02|WholeEarlyDirect|y / "y ="|b82955050d68|trusted_y,revision_consistent_y|"19\n"|[16, 24, 198]|-56.933406591218954|-44.123287200927734|
|E02|WholeEarlyDirect|y / "y ="|b82955050d68|old_y|"15\n"|[16, 20, 198]|-67.23657417297363|-44.123287200927734|
|E02|WholeEarlyDirect|y / "y ="|b82955050d68|root_misbind|"28\n"|[17, 23, 198]|-66.98027610778809|-31.779539108276367|
|E02|WholeEarlyOneLine|z / "最终答案："|538d8895a4aa|trusted_final,revision_consistent_final|"38\n"|[18, 23, 198]|-37.60044050216675|-16.112756729125977|
|E02|WholeEarlyOneLine|z / "最终答案："|538d8895a4aa|old_final|"30\n"|[18, 15, 198]|-41.12147653102875|-16.112756729125977|
|E02|WholeEarlyOneLine|z / "最终答案："|538d8895a4aa|skip_signature|"56\n"|[20, 21, 198]|-26.09715175628662|-11.581506729125977|
|E02|WholeEarlyOneLine|y / "y ="|d71441077624|trusted_y,revision_consistent_y|"19\n"|[16, 24, 198]|-50.373257279384234|-44.75878143310547|
|E02|WholeEarlyOneLine|y / "y ="|d71441077624|old_y|"15\n"|[16, 20, 198]|-64.95672130584717|-44.75878143310547|
|E02|WholeEarlyOneLine|y / "y ="|d71441077624|root_misbind|"28\n"|[17, 23, 198]|-66.93834686279297|-33.28221893310547|
|E02|WholeLateOneLine|z / "最终答案："|538d8895a4aa|trusted_final,revision_consistent_final|"38\n"|[18, 23, 198]|-35.81178951263428|-12.803441047668457|
|E02|WholeLateOneLine|z / "最终答案："|538d8895a4aa|old_final|"30\n"|[18, 15, 198]|-38.45896828174591|-12.803441047668457|
|E02|WholeLateOneLine|z / "最终答案："|538d8895a4aa|skip_signature|"56\n"|[20, 21, 198]|-24.397210001945155|-10.053441047668457|
|E02|WholeLateOneLine|y / "y ="|d71441077624|trusted_y,revision_consistent_y|"19\n"|[16, 24, 198]|-46.60887556616217|-42.47762680053711|
|E02|WholeLateOneLine|y / "y ="|d71441077624|old_y|"15\n"|[16, 20, 198]|-52.77358531951904|-42.47762680053711|
|E02|WholeLateOneLine|y / "y ="|d71441077624|root_misbind|"28\n"|[17, 23, 198]|-69.42976379394531|-37.25106430053711|
|E03|FullDirect|z / "最终答案："|b1283a1f8f2c|trusted_final,revision_consistent_final|"87\n"|[23, 22, 198]|-48.35208320617676|-18.65625|
|E03|FullDirect|z / "最终答案："|b1283a1f8f2c|old_final|"70\n"|[22, 15, 198]|-17.578241467475884|0.0|
|E03|FullDirect|z / "最终答案："|b1283a1f8f2c|skip_signature|"15\n"|[16, 20, 198]|-50.62314987182617|-23.46875|
|E03|FullDirect|y / "y ="|621b46af1a3d|trusted_y,revision_consistent_y|"81\n"|[23, 16, 198]|-47.28428101529062|-31.674081802368164|
|E03|FullDirect|y / "y ="|621b46af1a3d|old_y|"64\n"|[21, 19, 198]|-45.61471987143159|-35.8850212097168|
|E03|FullDirect|y / "y ="|621b46af1a3d|root_misbind|"9\n"|[24, 198]|-45.93157196044922|-26.205331802368164|
|E03|FullOneLine|z / "最终答案："|880fc8c429b7|trusted_final,revision_consistent_final|"87\n"|[23, 22, 198]|-43.3292875289917|-16.03128433227539|
|E03|FullOneLine|z / "最终答案："|880fc8c429b7|old_final|"70\n"|[22, 15, 198]|-14.843788504036631|-3.361645576660521e-05|
|E03|FullOneLine|z / "最终答案："|880fc8c429b7|skip_signature|"15\n"|[16, 20, 198]|-44.22409534454346|-20.56253433227539|
|E03|FullOneLine|y / "y ="|f82aadda5d7c|trusted_y,revision_consistent_y|"81\n"|[23, 16, 198]|-44.146409988396044|-35.14468765258789|
|E03|FullOneLine|y / "y ="|f82aadda5d7c|old_y|"64\n"|[21, 19, 198]|-42.20219981856644|-38.58218765258789|
|E03|FullOneLine|y / "y ="|f82aadda5d7c|root_misbind|"9\n"|[24, 198]|-48.94787788391113|-32.72281265258789|
|E03|WholeEarlyDirect|z / "最终答案："|b1283a1f8f2c|trusted_final,revision_consistent_final|"87\n"|[23, 22, 198]|-33.98615961521864|-0.07207804173231125|
|E03|WholeEarlyDirect|z / "最终答案："|b1283a1f8f2c|old_final|"70\n"|[22, 15, 198]|-53.34591865539551|-22.509578704833984|
|E03|WholeEarlyDirect|z / "最终答案："|b1283a1f8f2c|skip_signature|"15\n"|[16, 20, 198]|-54.88786315917969|-20.540828704833984|
|E03|WholeEarlyDirect|y / "y ="|621b46af1a3d|trusted_y,revision_consistent_y|"81\n"|[23, 16, 198]|-58.6962194442749|-46.87931442260742|
|E03|WholeEarlyDirect|y / "y ="|621b46af1a3d|old_y|"64\n"|[21, 19, 198]|-61.95787167549133|-48.64689254760742|
|E03|WholeEarlyDirect|y / "y ="|621b46af1a3d|root_misbind|"9\n"|[24, 198]|-55.602420806884766|-32.17228317260742|
|E03|WholeEarlyOneLine|z / "最终答案："|880fc8c429b7|trusted_final,revision_consistent_final|"87\n"|[23, 22, 198]|-29.76747587742284|-0.0013559204526245594|
|E03|WholeEarlyOneLine|z / "最终答案："|880fc8c429b7|old_final|"70\n"|[22, 15, 198]|-46.36582946777344|-18.84510612487793|
|E03|WholeEarlyOneLine|z / "最终答案："|880fc8c429b7|skip_signature|"15\n"|[16, 20, 198]|-46.01493787765503|-15.73573112487793|
|E03|WholeEarlyOneLine|y / "y ="|f82aadda5d7c|trusted_y,revision_consistent_y|"81\n"|[23, 16, 198]|-53.610321044921875|-46.109375|
|E03|WholeEarlyOneLine|y / "y ="|f82aadda5d7c|old_y|"64\n"|[21, 19, 198]|-57.45751452445984|-48.40625|
|E03|WholeEarlyOneLine|y / "y ="|f82aadda5d7c|root_misbind|"9\n"|[24, 198]|-60.37506294250488|-35.109375|
|E03|WholeLateOneLine|z / "最终答案："|880fc8c429b7|trusted_final,revision_consistent_final|"87\n"|[23, 22, 198]|-28.247351080179214|-0.06512680649757385|
|E03|WholeLateOneLine|z / "最终答案："|880fc8c429b7|old_final|"70\n"|[22, 15, 198]|-39.389883041381836|-15.768251419067383|
|E03|WholeLateOneLine|z / "最终答案："|880fc8c429b7|skip_signature|"15\n"|[16, 20, 198]|-41.972556591033936|-10.330751419067383|
|E03|WholeLateOneLine|y / "y ="|f82aadda5d7c|trusted_y,revision_consistent_y|"81\n"|[23, 16, 198]|-44.2118923664093|-42.05717849731445|
|E03|WholeLateOneLine|y / "y ="|f82aadda5d7c|old_y|"64\n"|[21, 19, 198]|-46.94223898649216|-42.62749099731445|
|E03|WholeLateOneLine|y / "y ="|f82aadda5d7c|root_misbind|"9\n"|[24, 198]|-48.68723773956299|-33.43217849731445|
|C02|FullDirect|z / "最终答案："|7f0f4a88b92e|trusted_final,old_final,revision_consistent_final|"16\n"|[16, 21, 198]|-18.523444890974588|-1.6689286894688848e-06|
|C02|FullDirect|z / "最终答案："|7f0f4a88b92e|skip_signature|"70\n"|[22, 15, 198]|-45.91369652748108|-26.265626907348633|
|C02|FullDirect|y / "y ="|28e92b061224|trusted_y,old_y,revision_consistent_y|"6\n"|[21, 198]|-56.988131523132324|-45.70819091796875|
|C02|FullDirect|y / "y ="|28e92b061224|root_misbind|"24\n"|[17, 19, 198]|-60.48155975341797|-30.915224075317383|
|C02|FullOneLine|z / "最终答案："|f0e00e213875|trusted_final,old_final,revision_consistent_final|"16\n"|[16, 21, 198]|-15.578138828206647|-1.1920858014491387e-05|
|C02|FullOneLine|z / "最终答案："|f0e00e213875|skip_signature|"70\n"|[22, 15, 198]|-49.19870471954346|-25.953136444091797|
|C02|FullOneLine|y / "y ="|4a94087d1e24|trusted_y,old_y,revision_consistent_y|"6\n"|[21, 198]|-50.990949630737305|-44.85979080200195|
|C02|FullOneLine|y / "y ="|4a94087d1e24|root_misbind|"24\n"|[17, 19, 198]|-64.13328552246094|-33.67229080200195|
|C02|WholeEarlyDirect|z / "最终答案："|7f0f4a88b92e|trusted_final,old_final,revision_consistent_final|"16\n"|[16, 21, 198]|-44.671693086624146|-23.84375|
|C02|WholeEarlyDirect|z / "最终答案："|7f0f4a88b92e|skip_signature|"70\n"|[22, 15, 198]|-55.91304111480713|-28.4375|
|C02|WholeEarlyDirect|y / "y ="|28e92b061224|trusted_y,old_y,revision_consistent_y|"6\n"|[21, 198]|-63.411314964294434|-50.94865036010742|
|C02|WholeEarlyDirect|y / "y ="|28e92b061224|root_misbind|"24\n"|[17, 19, 198]|-62.3469181060791|-32.48087692260742|
|C02|WholeEarlyOneLine|z / "最终答案："|f0e00e213875|trusted_final,old_final,revision_consistent_final|"16\n"|[16, 21, 198]|-37.08645009994507|-18.28125|
|C02|WholeEarlyOneLine|z / "最终答案："|f0e00e213875|skip_signature|"70\n"|[22, 15, 198]|-48.766632080078125|-23.65625|
|C02|WholeEarlyOneLine|y / "y ="|4a94087d1e24|trusted_y,old_y,revision_consistent_y|"6\n"|[21, 198]|-62.289472579956055|-54.2109375|
|C02|WholeEarlyOneLine|y / "y ="|4a94087d1e24|root_misbind|"24\n"|[17, 19, 198]|-67.21415328979492|-35.84375|
|C02|WholeLateOneLine|z / "最终答案："|f0e00e213875|trusted_final,old_final,revision_consistent_final|"16\n"|[16, 21, 198]|-31.311771154403687|-15.437500953674316|
|C02|WholeLateOneLine|z / "最终答案："|f0e00e213875|skip_signature|"70\n"|[22, 15, 198]|-46.37846565246582|-22.484375|
|C02|WholeLateOneLine|y / "y ="|4a94087d1e24|trusted_y,old_y,revision_consistent_y|"6\n"|[21, 198]|-58.69974136352539|-51.10546875|
|C02|WholeLateOneLine|y / "y ="|4a94087d1e24|root_misbind|"24\n"|[17, 19, 198]|-69.30411720275879|-37.890625|
|W02|FullDirect|z / "最终答案："|e6a21d81e0de|trusted_final,old_final|"21\n"|[17, 16, 198]|-17.46098220347443|-3.576278118089249e-07|
|W02|FullDirect|z / "最终答案："|e6a21d81e0de|revision_consistent_final|"19\n"|[16, 24, 198]|-36.41010756790638|-19.5625|
|W02|FullDirect|z / "最终答案："|e6a21d81e0de|skip_signature|"67\n"|[21, 22, 198]|-44.3132905960083|-25.03125|
|W02|FullDirect|y / "y ="|2a7ef5271ba2|trusted_y,old_y|"9\n"|[24, 198]|-52.125776290893555|-34.95362854003906|
|W02|FullDirect|y / "y ="|2a7ef5271ba2|revision_consistent_y|"8\n"|[23, 198]|-59.965651512145996|-47.36769104003906|
|W02|FullDirect|y / "y ="|2a7ef5271ba2|root_misbind|"32\n"|[18, 17, 198]|-62.79665975086391|-34.18800354003906|
|W02|FullOneLine|z / "最终答案："|c0a6f9307f75|trusted_final,old_final|"21\n"|[17, 16, 198]|-15.078767230790618|-0.0006129055400379002|
|W02|FullOneLine|z / "最终答案："|c0a6f9307f75|revision_consistent_final|"19\n"|[16, 24, 198]|-30.241138637065887|-16.781862258911133|
|W02|FullOneLine|z / "最终答案："|c0a6f9307f75|skip_signature|"67\n"|[21, 22, 198]|-39.999314308166504|-21.563112258911133|
|W02|FullOneLine|y / "y ="|a0b14b04987d|trusted_y,old_y|"9\n"|[24, 198]|-58.890625|-36.296875|
|W02|FullOneLine|y / "y ="|a0b14b04987d|revision_consistent_y|"8\n"|[23, 198]|-55.84539031982422|-51.80078125|
|W02|FullOneLine|y / "y ="|a0b14b04987d|root_misbind|"32\n"|[18, 17, 198]|-77.97896575927734|-41.8984375|
|W02|WholeEarlyDirect|z / "最终答案："|e6a21d81e0de|trusted_final,old_final|"21\n"|[17, 16, 198]|-42.04214906692505|-20.40625|
|W02|WholeEarlyDirect|z / "最终答案："|e6a21d81e0de|revision_consistent_final|"19\n"|[16, 24, 198]|-39.066639453172684|-22.5|
|W02|WholeEarlyDirect|z / "最终答案："|e6a21d81e0de|skip_signature|"67\n"|[21, 22, 198]|-43.74503564834595|-24.96875|
|W02|WholeEarlyDirect|y / "y ="|2a7ef5271ba2|trusted_y,old_y|"9\n"|[24, 198]|-74.30581665039062|-44.71135330200195|
|W02|WholeEarlyDirect|y / "y ="|2a7ef5271ba2|revision_consistent_y|"8\n"|[23, 198]|-59.7645845413208|-50.55900955200195|
|W02|WholeEarlyDirect|y / "y ="|2a7ef5271ba2|root_misbind|"32\n"|[18, 17, 198]|-61.69978361495305|-32.67229080200195|
|W02|WholeEarlyOneLine|z / "最终答案："|c0a6f9307f75|trusted_final,old_final|"21\n"|[17, 16, 198]|-35.17549753189087|-15.843770980834961|
|W02|WholeEarlyOneLine|z / "最终答案："|c0a6f9307f75|revision_consistent_final|"19\n"|[16, 24, 198]|-32.214471220970154|-17.84377098083496|
|W02|WholeEarlyOneLine|z / "最终答案："|c0a6f9307f75|skip_signature|"67\n"|[21, 22, 198]|-45.77749061584473|-19.78127098083496|
|W02|WholeEarlyOneLine|y / "y ="|a0b14b04987d|trusted_y,old_y|"9\n"|[24, 198]|-76.5546875|-45.6328125|
|W02|WholeEarlyOneLine|y / "y ="|a0b14b04987d|revision_consistent_y|"8\n"|[23, 198]|-55.91661071777344|-51.92578125|
|W02|WholeEarlyOneLine|y / "y ="|a0b14b04987d|root_misbind|"32\n"|[18, 17, 198]|-64.1979276239872|-35.140625|
|W02|WholeLateOneLine|z / "最终答案："|c0a6f9307f75|trusted_final,old_final|"21\n"|[17, 16, 198]|-34.38468074798584|-14.781267166137695|
|W02|WholeLateOneLine|z / "最终答案："|c0a6f9307f75|revision_consistent_final|"19\n"|[16, 24, 198]|-31.89013135433197|-17.500017166137695|
|W02|WholeLateOneLine|z / "最终答案："|c0a6f9307f75|skip_signature|"67\n"|[21, 22, 198]|-45.28273391723633|-19.640642166137695|
|W02|WholeLateOneLine|y / "y ="|a0b14b04987d|trusted_y,old_y|"9\n"|[24, 198]|-76.296875|-40.828125|
|W02|WholeLateOneLine|y / "y ="|a0b14b04987d|revision_consistent_y|"8\n"|[23, 198]|-57.934975147247314|-54.4921875|
|W02|WholeLateOneLine|y / "y ="|a0b14b04987d|root_misbind|"32\n"|[18, 17, 198]|-70.88688623898997|-41.375|
|E04|FullDirect|z / "最终答案："|e45fd4a23794|trusted_final,revision_consistent_final|"43\n"|[19, 18, 198]|-38.60940742492676|0.0|
|E04|FullDirect|z / "最终答案："|e45fd4a23794|old_final|"41\n"|[19, 16, 198]|-17.742206573486328|0.0|
|E04|FullDirect|z / "最终答案："|e45fd4a23794|skip_signature|"25\n"|[17, 20, 198]|-48.22673797607422|-19.78125|
|E04|FullDirect|y / "y ="|ad5a81b0b533|trusted_y,revision_consistent_y|"39\n"|[18, 24, 198]|-53.276012897491455|-39.671875|
|E04|FullDirect|y / "y ="|ad5a81b0b533|old_y|"37\n"|[18, 22, 198]|-50.584375858306885|-39.671875|
|E04|FullDirect|y / "y ="|ad5a81b0b533|root_misbind|"21\n"|[17, 16, 198]|-61.43693923950195|-29.40625|
|E04|FullOneLine|z / "最终答案："|81199f3835b4|trusted_final,revision_consistent_final|"43\n"|[19, 18, 198]|-29.562654723253218|-0.00014423283573705703|
|E04|FullOneLine|z / "最终答案："|81199f3835b4|old_final|"41\n"|[19, 16, 198]|-15.687648166741724|-0.00014423283573705703|
|E04|FullOneLine|z / "最终答案："|81199f3835b4|skip_signature|"25\n"|[17, 20, 198]|-43.851938247680664|-18.703269958496094|
|E04|FullOneLine|y / "y ="|801439f1e7f6|trusted_y,revision_consistent_y|"39\n"|[18, 24, 198]|-62.84924793243408|-48.28125|
|E04|FullOneLine|y / "y ="|801439f1e7f6|old_y|"37\n"|[18, 22, 198]|-56.20927185192704|-48.28125|
|E04|FullOneLine|y / "y ="|801439f1e7f6|root_misbind|"21\n"|[17, 16, 198]|-67.4369945526123|-36.3125|
|E04|WholeEarlyDirect|z / "最终答案："|e45fd4a23794|trusted_final,revision_consistent_final|"43\n"|[19, 18, 198]|-34.78240489959717|-13.625001907348633|
|E04|WholeEarlyDirect|z / "最终答案："|e45fd4a23794|old_final|"41\n"|[19, 16, 198]|-34.938639640808105|-13.625001907348633|
|E04|WholeEarlyDirect|z / "最终答案："|e45fd4a23794|skip_signature|"25\n"|[17, 20, 198]|-20.565664887426237|-2.0265558760002023e-06|
|E04|WholeEarlyDirect|y / "y ="|ad5a81b0b533|trusted_y,revision_consistent_y|"39\n"|[18, 24, 198]|-67.08076949045062|-54.861328125|
|E04|WholeEarlyDirect|y / "y ="|ad5a81b0b533|old_y|"37\n"|[18, 22, 198]|-73.72737884521484|-54.861328125|
|E04|WholeEarlyDirect|y / "y ="|ad5a81b0b533|root_misbind|"21\n"|[17, 16, 198]|-79.74296379089355|-39.09375|
|E04|WholeEarlyOneLine|z / "最终答案："|81199f3835b4|trusted_final,revision_consistent_final|"43\n"|[19, 18, 198]|-19.011714935302734|-1.4886598587036133|
|E04|WholeEarlyOneLine|z / "最终答案："|81199f3835b4|old_final|"41\n"|[19, 16, 198]|-18.558591842651367|-1.4886598587036133|
|E04|WholeEarlyOneLine|z / "最终答案："|81199f3835b4|skip_signature|"25\n"|[17, 20, 198]|-17.03229171037674|-0.6136599183082581|
|E04|WholeEarlyOneLine|y / "y ="|801439f1e7f6|trusted_y,revision_consistent_y|"39\n"|[18, 24, 198]|-63.63831424713135|-56.361328125|
|E04|WholeEarlyOneLine|y / "y ="|801439f1e7f6|old_y|"37\n"|[18, 22, 198]|-70.54223680496216|-56.361328125|
|E04|WholeEarlyOneLine|y / "y ="|801439f1e7f6|root_misbind|"21\n"|[17, 16, 198]|-81.47228622436523|-41.71875|
|E04|WholeLateOneLine|z / "最终答案："|81199f3835b4|trusted_final,revision_consistent_final|"43\n"|[19, 18, 198]|-21.449039936065674|-4.78965950012207|
|E04|WholeLateOneLine|z / "最终答案："|81199f3835b4|old_final|"41\n"|[19, 16, 198]|-21.21467638015747|-4.78965950012207|
|E04|WholeLateOneLine|z / "最终答案："|81199f3835b4|skip_signature|"25\n"|[17, 20, 198]|-17.969451516866684|-0.039659589529037476|
|E04|WholeLateOneLine|y / "y ="|801439f1e7f6|trusted_y,revision_consistent_y|"39\n"|[18, 24, 198]|-64.45427370071411|-56.14453125|
|E04|WholeLateOneLine|y / "y ="|801439f1e7f6|old_y|"37\n"|[18, 22, 198]|-65.22830128669739|-56.14453125|
|E04|WholeLateOneLine|y / "y ="|801439f1e7f6|root_misbind|"21\n"|[17, 16, 198]|-69.79583644866943|-41.4375|

完整/首token role margin、同值别名 NA 与 matched-prefix ΔlogP 全部保存在 JSON；完整 logP 的 CPU 核验为对已保存逐 token conditional 的求和，没有重新生成后续 token logits。

## 7. 实际成本与诊断完成边界

诊断各臂 Y/Z 可用上下文数：{'FullDirect': {'z': 8, 'y': 8}, 'FullOneLine': {'z': 8, 'y': 8}, 'WholeEarlyDirect': {'z': 8, 'y': 8}, 'WholeEarlyOneLine': {'z': 8, 'y': 8}, 'WholeLateOneLine': {'z': 8, 'y': 8}}

完整诊断 ID：['E01', 'C01', 'W01', 'E02', 'E03', 'C02', 'W02', 'E04']

primary分母仍为全部五臂完整病例，不因后半批诊断超时而减半。

实际成本（计时相互包含，不相加）：

```json
{
  "runner_elapsed_seconds_recorded": 264.35894379206,
  "hash_and_load_seconds_included_recorded": 29.977774594910443,
  "forward_calls_recounted": 2961,
  "forward_input_tokens_recounted": 16336,
  "synchronized_forward_seconds_recounted": 189.76396771147847,
  "free_new_tokens_recorded_total": 2618,
  "observed_postload_peak_allocated_bytes_recorded": 9738934272,
  "note": "Launcher/runner/load/forward timings are nested; do not add. Shared prefixes, held checkpoints, controls and probes are experimental costs, not production speedup.",
  "launcher_record_path": "D:\\ACL\\research\\p05_design_review_20261105\\launcher_01.json",
  "launcher_record_sha256": "b575569dd70b53918f55e87fbc4aa808aa8dc56e5e433518f30b6518c4648f99",
  "launcher_elapsed_seconds_including_hash_import_load": 267.54681873321533,
  "launcher_conservative_single_gpu_minutes": 4.459113645553589,
  "launcher_exit_code": 0,
  "ending_compute_processes_recorded": ""
}
```

完整控制bundle仅在记录含checks的病例执行，其余不能宣称完整控制PASS：['E01', 'C01', 'W01']

## 8. 身份与完整性

冻结 parser SHA256：c2bc053b66778288f524d46f4353e825b1ee654d829027bd02b1cb3173255eed

完整性问题：[]

原 run 保持只读；分析未执行模型/GPU。

完整机器数据：[PRIMARY_P05_ANALYSIS.json](D:/ACL/research/p05_design_review_20261105/PRIMARY_P05_ANALYSIS.json)
