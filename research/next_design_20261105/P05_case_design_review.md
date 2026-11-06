# P0.5 拓扑病例设计独立审查

2026-11-05。只读检查 builder、v1/v2 JSON，并以独立 Python AST 求值复核 12 个状态的算术、依赖图、mask 集和字段边界；没有模型调用、GPU、远程访问或源文件修改。后续只应引用 **P05_topology_cases_v2.json**。

**结论：v2 的病例/schema 层面通过，未发现剩余静态阻塞；可进入 tokenizer 映射冻结和 CPU renderer 验收。** 这不等于 token 预算已经实测相等，也不是 GPU 实验或性能结论。新方案确实形成了原 16 例没有的非空独立支持 r；late/early 与 r-before/r-after 的解释边界也明确了。

复核版本：

- Builder SHA256：`b5d073f9bab7fd8e2dd70b79441427ad8d6cdf7c2ccceaa02de6bd2a212e0b78`
- v2 JSON SHA256：`93f39936cb5d1dbdbc1eb647d1c0f228be11cf49f23d14b7b2163b52d01902d1`

JSON 内 `source_sha256` 与当前 builder 一致。12 个 case ID 唯一，每个程序包含 before/after × E/C/W 六个状态，属于 **2 个程序的配对机制控制**，不能当成 12 道独立题。

## 发现并已修正的 v1 数值别名

v1 的 T2 使用 r=17，正确 x=9、y=81、z=64；E 状态的旧 x=8、旧 y=64。因此 sham 保留的错误 `y=64` 在数值上恰好等于正确最终答案 64，模型可能仅抄数就得到“正确”评分。这会混入 closure/sham 的行为解释。

主任务在任何新模型输出前保留 v1，并将 T2 改为 `r=13+5=18`：正确 z=63，旧 y=64，旧 z=46。v2 又增加 E 组旧 x/y/z 均不得碰巧等于正确 z 的 instrument 断言。本次独立复核确认该条件在两种程序、两个位置的四个 E 状态均通过。

这是事先检查测试工具的答案别名，不是根据生成效果筛样本。v1 保留未使用，v2 应作为唯一后续冻结版本；不能混合两版 token 表或结果。

## 算术与依赖核查

| 程序 | 正确状态 (r,x,y,z) | 错误 x 对应状态 (r,x,y,z) |
|---|---|---|
| T1：r=6*4；x=27-9；y=3*x+2；z=y+r | (24,18,56,80) | (24,19,59,83) |
| T2：r=13+5；x=54//6；y=x*x；z=y-r | (18,9,81,63) | (18,8,64,46) |

12/12 的旧断言、修订推出值、最终正确值和 validity 标签均与独立 AST 运算一致。两程序的依赖都是：

`r: []；x: []；y: [x]；z: [r,y]`。

撤回旧 x 的完整依赖闭包为 `{x,y,z}`，独立支持为 `{r}`；最终 z 也是后代，已正确纳入 mask。E 为旧 x 错/修订 x 对，C 为旧 x 对/修订不变，W 为旧 x 对/修订 x 错；对应元数据和 `actual_root_value_changed` 一致。

mask 规则也一致：WholeB 屏蔽四个 clause；Closure 屏蔽 x/y/z、保留 r；Sham 屏蔽 r/x/z、保留 y。Closure/Sham 都是三个 clause，并且 E 的 y 是失效后代。C/W 的 y 原本正确，这是预设压力控制，不能按隐藏标签跳过。

## Schema 与 gold 输入边界

可见内容明确分为题目、四个断言 clause 和复核文本。正确值、group、validity、依赖图和答案都在 `evaluator_only`；`fixed_mask_rules` 是受控结构注释，作为干预地址使用，不能整个序列化进模型输入。

白名单 `visible.question / visible.old_assignment_clauses[].text / visible.revision` 合理。每条 P 都含完整原始定义，r 的定义没有因 after placement 而被隐藏。复核文本只给同一可见 x，未额外给正确 y/z；其数值在 E/C 正确、W 错误，是人为注入条件，不冒充模型自诊断。

W 的文本目前使用统一的“复核记录”，**没有字面 Wait**。它测试错误复核/错误修订压力，不能单独代表一个由 Wait 词触发的在线策略。这是命名/解释边界，不阻止该机制控制。

## Token/位置冻结的验收条件

每个 clause 独立 encode，然后用全局相同 slot 宽度填充，并屏蔽整个 slot（含 padding），可以使 Closure/Sham 都恰为 `3×slot_width` 个 key 槽位。当前 JSON 是渲染合同，尚无真实 tokenizer 的冻结 ID 映射，因此“预算一致”现在只是可验收设计，不能写成已测事实。

执行前至少冻结并核查：

1. 实际模型 tokenizer 和模板 hash；四个 clause 的独立 token ID；全 12 状态的全局宽度；所有 segment/slot 起止；最终完整 ID 序列和原 position IDs。
2. 换行 padding 必须在 **token ID 层**追加一个已验证的固定普通 token。若 encode("\n") 不止一个 token，需明示选用的 padding 单位；不能在补字符串后把整槽或全前缀重新 tokenize，否则连续换行可能合并，预算合同失效。
3. 对每个状态直接断言 Closure/Sham 屏蔽数完全相等，mask 不碰 P/R/readout，保留的 r/y 槽位与 schema 对应，late/early 的 ID、位置、可见摘要完全相同。
4. 新 renderer 只取白名单文本；`evaluator_only`、case ID/group/placement 标签不进入 prompt。旧 real_model_p0.py 不接受本 schema，不能把新 JSON 直接交给旧脚本后假定含义相同。

换行是格式填充，不能先验认定它对模型完全中性；但在冻结的配对设计中显式计入位置、mask 和成本即可。WholeB 的四槽预算与 Closure 的三槽预算不同属于设计本意；不能把它们的差直接宣称为相同缓存预算下的语义选择优势。

## r-before / r-after 能回答什么

before 顺序为 r,x,y,z；after 为 x,y,z,r。对同一个状态，Closure-Late 和 Closure-Early 应始终保持相同 position、token 和可见 key。

- r-before：r 的旧 KV 因果上不能读取后面的错误断言。这应通过逐层 r-slot 的 late/fresh KV 不变控制验证，而不是只凭输出答对。**后面的 U/R/readout 仍可能读过错误段**，所以 before 并不代表整个 late 状态干净。
- r-after：r 的数值在算术上独立，但它的旧 KV 可以读过 x/y/z。需要比较同状态 Late/Early，并测 r-slot 的逐层差异；不能把语义独立直接当缓存独立。
- before/after 的 clause 顺序、位置与注意力历史本身不同，因此只看最终答案的拓扑差，不能唯一归因 r 承载的旧信息。最小机制指标应包括 r-slot 的层级 KV 差及 no-op 噪声，最终读出作为补充。

若 r-after 的 KV 没有明显变化，这是该模型/输入的负结果，应保留；不能先定它必有污染。若 KV 变化而答案不变，也只支持状态效应而非纠错增益。

## Sham 和输出格式的解释范围

三槽 sham 的预算合理，且已明确不匹配位置、年龄、连续性或语义内容。它是“保留一个依赖值”的受控反例，不是语义等价，也不是成熟随机 KV 算法复现。Closure 优于 sham 最多说明这几个固定状态中，保留 r 的组合更好；仍不能排除变量角色、位置和复制线索。

原 16 例的 Full/Whole-Early × Direct/OneLine 应保持为单独四臂选项。不要与本 12 状态再笛卡尔相乘，也不要将“更长的显式输出”和“保留独立工作”的组合收益归为一个机制。

当前只通过了 **设计和精确算术验收**；没有生成分数，不做成功率或省时判断。下一步如获执行，应先完成冻结 token 和接口控制，再做一次预定短跑；本审查没有自动触发任何模型实验。
