# D1前置CPU内核：作用范围、证书、多重支持与文本退役

2026-11-06。状态：**受限CPU实现及检查完成；30/30通用单元测试、200个随机图×3状态＝600次独立agenda对照通过。没有运行GPU、自然证明提取或解题质量实验。**

## 1. 本模块回答什么问题

本轮完整阅读用户新附件与zip五个文件，保留提供代码的来源属性，在独立`support_engine/`实现加固版，不改上游/旧Phase。目标是让以下三件事在代码中分开：

1. 一个结论是否仍有至少一份当前有效、范围一致且前提齐全的认证支持；
2. 某条论证是否已被核验为无效，因而其**文本**应退出后续模型上下文；
3. 某结论本身是否有独立且适用的反驳证据。

论证无效不蕴含结论为假，失去支持也不蕴含结论为假。同一结论的另一个有效证明可以保住结论；两条都依赖同一坏根的路径则不能伪称独立。

本模块没有实现自然语言G、LLM图解析、反思选择策略、KV crop或原生续写；父任务D1负责模型接口。AND/OR最小不动点、证据撤回与依赖维护属于经典真值维护/增量推理思想，不作为新发明。

## 2. 对提供参考代码的实际核对

`UPSTREAM_GAPS_REPRODUCED.json`记录了在临时目录加载已读过的原始stdlib-only core后得到的CPU反例（未修改zip）：

| 原参考行为 | 实际观察 | 判断 |
|---|---|---|
| 任意非空certificate字符串＋`trusted_root`名字 | 可将`x=999`放进supported | 参考契约假定外部已验证；真实集成时必须补验证，不能直接接受LLM字段 |
| 任意`Challenge(PASS, scope匹配, 非空字符串)` | 可撤销有效根证明 | 没有与具体被反驳表达式、前提版本、核验器绑定 |
| 撤回一条z证明，z另有独立证明 | `lost_support`空、crop为None | 支持闭包正确，但旧文本仍可能含坏论证；逻辑损失不能代替文本退役范围 |
| 无根的两节点循环证明 | supported为空 | 原最小不动点这一点正确，不应笼统说原图算法错误 |

另有只读静态缺口：单个幂指数虽限制12，但嵌套幂没有AST/深度/位数总界；未执行会造成巨大整数的原代码示例。原bridge按canonical_text直接拼接，未验证其来源/控制标签；原cut也不是合法think边界或最小成本点的证明。

提供材料已经明确“证书由外部checker验明”，因此上述是**从示例到真实实现的准入缺口**，不是对作者已声明不存在的自然算法收益做否定。

## 3. 实际实现和可信边界

源码`scope_rebase_hardened.py`包含：

- `Scope`：显式domain、assumptions、revision；只支持整数/有理数解释。
- `Claim`：subject、值、scope、version、已观察token span；相同身份/版本/数值不能用多个claim ID重复计，多个依据指向同一claim。
- `Justification`：前提AND、结论、规则表达式、变量到claim的显式绑定、来源规则ID及证明文本span。
- `ProofCertificate`：checker identity、用途、结论/前提版本/范围/规则指纹和可重放见证；不能用一个证书替换另一条proof或跨scope使用。
- `Challenge`：区分`invalidate_justification`和`refute_claim`。用户/LLM自报verdict不构成PASS。
- `EvidenceLedger`：当前版本、OR-of-AND最小不动点、冲突隔离、原子多根版本切换、修复delta与规范bridge。

**证书并非一个自由字符串或“算对了”的标签。** 正支持的算术证书除了重算表达式，还必须有调用方已认证的原题规则/约束许可；比如`2+3=5`本身不能证明题目中的`y=5`。缺少规则许可为UNKNOWN。源/规则由`trust_given`/`trust_constraint`显式登记，不能把模型提案自动接到这两个可信入口。

`prove_arithmetic`在固定规则许可、身份/范围绑定和前提值下执行受限AST求值；证书使用时再次重放并核绑定。只支持精确整数/有理数，加减乘除和有界幂；无eval、调用、属性、浮点或任意Python。新增2048字符/128 AST节点/24深度/4096位中间值限制，超界UNKNOWN而不是断言数学错误。

调用方提供的题干规则是否被正确解析、条件是否完整仍是**外部假设**，本模块不会自动证明它。内部issued registry和私有成员不是密码学签名或Python沙箱；保证范围是防止未经本checker核验的序列化PASS/移植证书被流程接受，不是对恶意宿主Python程序的安全证明。

## 4. 两类挑战及支持状态

### 实际算术步骤否定

`check_arithmetic_invalidation`要求前提有不依赖被挑战结论的当前认证路径，检查原statement的scope/entity/版本及数值。例如：

```text
可信x=2；模型写了x²=5
  → 精确检查4≠5，针对这条论证签发invalidation证据
  → 退役该proof文本；不撤销可信x=2，也不自动给结论真/假标签
```

“2+3=6”也可能是指向真实结论`z=6`的一条坏论证。测试保留`z=r=6`的独立有效支持，同时核验撤回坏论证文本，`lost_support`仍为空。这是论证失效与结论否定的具体分离。

### 声明反驳

`check_claim_refutation`使用已登记的原题约束和独立支持前提，检查特定scope/version的值是否被该约束反驳。没有完整约束、scope不同、前提未认证或依赖被反驳对象自身时UNKNOWN。若现有正证书与独立负证书冲突，进入`INCONSISTENT_CERTIFICATES`，隔离冲突及依赖支持，不随意宣布某个根错。

### 外部可信证据生命周期

`issue_withdrawal`单独模拟“可信来源撤回这份证据许可”的外部事件，绑定具体proof。它不是自然反例检测器，`reason`文字本身不证明自然推导错误，也不能接LLM自报。测试使用它控制图的撤回事件，真实自然集成必须提供有来源的授权/核验事件；不能把这些fixture当模型纠错成功率。

支持闭包是最小不动点。没有根的循环不能认证自己；有根循环可以获得支持，根撤回后重新归零。版本切换先暂装后核当前可认证性，不成立即原子回滚；只依赖将被归档旧版本自身的新值不会被错误激活。

## 5. 逻辑损失、文本退役和桥接是三个对象

`lost_support = before.supported − after.supported`仅回答失去当前认证支持的claim。

`invalidated_justifications/source_spans`另记录已核验失效的论证文本。即使lost为空，也会产生重建候选；不能因另一证明保住结论就继续把坏论证放在活跃上下文。

当前`proposed_cut`取失效proof/失去支持claim声明span中的最早位置，再退到**调用方提供的已验证合法步边界**。没有合法边界则明确None，不虚构cut。本模块只检查range在已观察token长度内，不解析think结构、不证明边界语义、更不证明这个位置计算代价最小。

`bridge`只序列化仍受支持的subject/value、scope/domain/assumptions、version和合法证书ID，不拷原始canonical prose/KV。scope条件用转义JSON携带，防ChatML/think标签直接执行；冲突状态与stale delta不能桥接。

桥接内容是否使LLM真实复用结论、是否更准或更省，全部仍待原生模型实验。本实现的token span属于调用方的不可变快照；多次尚未执行的修复需要调用方合并失效范围，执行rebase后须重建新token映射，不能直接沿用旧span。这不是完整的在线事件/状态重建器。

## 6. 实际检查和准备中发现的问题

最终`CPU_SUPPORT_CHECKS.json`：30个通用unittest通过；200个随机小图，每图初始/两次撤回，600次engine与独立agenda实现结果相等；约6.4秒。它们是受限、已知规则图的CPU控制，不是628个独立数学题或自然任务指标。

重点覆盖：free-PASS/伪造/移植证书拒绝、规则许可、跨scope/实体、AND缺前提、OR独立与共享坏根、循环、真假算术挑战、声明反驳、正负证书冲突、原子多根更新、过期版本、lost为空文本仍退役、边界缺失、stale delta、规范bridge、嵌套幂资源界。

准备过程的自审纠偏：初稿23测试全部通过后，进一步发现“计算相等不等于subject推导合法”的遗漏，因此增加可信规则许可与真实invalid-arithmetic挑战，再补相应反例和重跑。也发现先激活版本后失去旧父支持的循环风险，改为暂装检查再原子提交。没有因测试通过提前把这些遗漏写成保证；最终只接受当前source hash的30项＋600比较。

当前源码SHA：`9b1847f7d8d031cc7a786e82ed9da4eba44e262bcad4f5a3f0b90b9dc5ed946d`。单元测试SHA：`3e12ef86fb23e179fddced7c36c5cf25a8b60cac7f90363ea7fbfe1d23912919`。初稿cf061不作最终验收依据。

## 7. 下一阶段准入与复跑

```powershell
python -X utf8 research/phase5d_scope_rebase_20261106/support_engine/run_cpu_checks.py
python -X utf8 research/phase5d_scope_rebase_20261106/support_engine/reproduce_upstream_gaps.py --zip-path E:/Downloads/longcot_phase5d_codex_kit.zip
```

GPU执行器须另验证原生prefix token IDs、checkpoint只看已观察前缀、合法think步边界、同prefix续写/重prefill一致性及完整成本。自然G只有在原题/规则/前提作用域可靠且证书能重放时才能使用本支持内核；其他情况UNKNOWN，不创建虚构PASS。所有强baseline必须有同证据/工具权限。

本次交付只使形式层的状态含义更明确，**没有模型准确率、自然覆盖、修复率、KV节省或论文创新收益数据。**
