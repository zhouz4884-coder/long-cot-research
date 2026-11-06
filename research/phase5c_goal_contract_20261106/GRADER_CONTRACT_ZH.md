# Phase5-C 新终局评分契约

2026-11-06。独立新模块`goal_math_grader.py`，不修改旧core/旧评分或回填旧分数。未读取新32题bank正文/evaluation来设计规则；测试全部为通用题外表达式。

## 接口

- `extract_final(text)`只接收模型输出，返回`status`、原始/规范化`surface`、方法、证据span以及完整对象结构。它不接收Gold，不核验目标语义或陈述真伪。
- `grade_final(text, gold)`在生成结束后才接收Gold，返回`correct`、`status`、提取结果、比较方式、版本及后台诊断。正常判错/输出不可解析是False；后台缺失/错版本/异常/超时、Gold无法解析是None，必须单列未解决并保留分母。

支持完整终端boxed、中文/英文最终标签、完整JSON对象的`final_answer`。JSON可为有限数值、数学字符串或有序列表；bool/null/未知对象/空或一般二维嵌套列表拒绝。列表保留全部分量与顺序，不取首项。行/列向量支持pmatrix、bmatrix、matrix；元组按顺序逐分量检查，候选scalar不能与Gold多分量对象匹配。为兼容坐标表示，Gold向量可接受同序元组；反向不把向量默认当Gold元组。

拒绝未闭合boxed/对象、JSON重复键、非有限数、相邻拆开的多boxed分量、无外层对象的逗号多分量；终局含or/either/possibly/不确定/或者等备选或不确定措辞时不送backend择取子式。不会从无最终标记的叙述里任取最后一个数字。最终标签后保留的是完整payload；支持范围仍受Math-Verify解析语法限制，不把结构提取通过说成数学或目标正确。

通用规范化包括缺反斜杠的三角/对数函数，如`cot y`→`\cot y`，避免按字母乘积解释；保留matrix行分隔，对源格式双重转义TeX命令作有限修复。没有针对任一实验题或Gold添加数字规则/黑名单。概率0、1和等价小数不因未写分数形式而无效。

## 数学后台与超时

严格要求`math-verify==0.9.0`，使用`parse/verify`，不把仅字符串fallback判成数学正确。分数/表达式由同一后台比较；完整元组/向量按对应分量比较，防止丢分量或无序匹配。

每次数学grade使用当前Python的独立CPU子进程（不是fork已有CUDA进程）；单次parse/verify内部5秒，整次子进程硬限20秒。硬超时明确返回`grader_timeout`和None。这些是离线评估成本，不是方法在线核验器G，不能把它对Gold的判断反馈到生成/候选选择。

## 已执行与待执行证据

当前源SHA为`ba394c1a42f86126f5a70bd0ed6f086b92dd551996cf44c410cfa6d896fa49fe`。本地48项提取、规范化和硬超时mock通过，见`GRADER_LOCAL_CPU_TEST.json`。本机未装Math-Verify，**0项本地数学后台测试**，不能将结构测试说成数学评分已验收。

同目录上传grader与`test_goal_math_grader.py`后，可在已有0.9.0远程CPU环境运行：

```text
python -B test_goal_math_grader.py --output GRADER_REMOTE_CPU_TEST.json --require-backend
```

预定22项数学smoke包括分数/小数等价、合法0/1、全部元组分量与顺序、向量坐标、通用cot/sin记号、根式、JSON、歧义拒绝以及Gold解析异常。远程结果另存，以实际通过/失败为准；较早源版本的CPU证据不能替代本SHA验收。
