# D3.8 证明修复的近邻与可证伪差异

**已有工作覆盖结构化编辑、按依赖重验，以及在下游需要时修改已证明节点。** D3.8 能单独检验的是，在同一候选动作、同一源快照和同一预算下，先证明锁定范围确实阻碍修复、再释放最少绑定，能否比现有编辑或直接搜索更有效。当前没有跨论文的增量证据。[版本与哈希](prior_art_sources.json)

## 直接对照

| 原始工作 | 已实现的修复对象与证据 | 对 D3.8 的约束 |
| --- | --- | --- |
| Fix, Not Just Resample，§4、§6 | 在同一个 Lean 状态用失败 tactic 和编译诊断重新提案。每状态最多 $K(1+R)$ 次尝试。作者报告 LeanDojo 等时曲线有增益，首次修复贡献三次修复净增量的 84–96%。 | 同状态报错重试已有直接先例。适合充当 `single_failed_step` 或等时重采样对照。其状态内操作没有修改已接受前缀的权限。 |
| Certifying Failed Lean Proof-Agent Searches with Exact Replay | 冻结各状态的已提案 tactic 和深度等资源，返回 Lean 证明、有限支持闭包失败或超时记录。作者接收版从 10/100 增至最强合法组合 39/100，38/100 是前沿与控制组合的中间结果。目标文本检索对照也有收益，前沿信息的单独增量证据有限。 | 有限支持耗尽的认证已有先例。其后续动作是获取新候选，包括检索与确定性 tactic，D3.8 需要区分扩大候选支持和解除指定保护。 |
| ExVerus，§3 | 重放验证反例，按可达与伪反例选择加强或替换不变量等变异，再用反例阻断与验证进度排序候选。程序和验证目标给定。 | 证据驱动的结构修复、变异与重新验证均已有先例。反例证伪一个验证义务的作用，和证明必须释放某个已验证依赖的作用分开。 |
| BlueprintRepair，§2–4、附录 B–D | 十个类型化操作已覆盖重写非目标节点、增删依赖、拆分节点及替换证明。同源精确源代码补丁与全文件重写是现成强对照。验收要求目标不变、所需节点已证明且实际依赖属于声明依赖。DeepSeek-V4-Flash 在 142 个受控状态上分别通过 104、109、104 个。作者代码另有可选 `rewrite_subgraph`，保留已证明节点并允许同名补回它依赖的未证明节点。 | **编辑能力直接重合。** 不能用只能改失败行的基线替代类型化修补，也不能把编辑局部性或维护证明依赖作为新贡献。可选操作不计入论文主表的十操作结果。 |
| Goedel-Architect，蓝图修订提示与 `refine.py` | 官方修订提示允许在下游要求改变签名时修改 `PROVED` 节点。代码在修订后的父节点语境中试挂接旧证明，只复用仍通过的证明。 | **按需解除已证明节点的保护、再检查旧证明也已有先例。** 当前候选区别收缩为机器可检的释放必要性、最小性和实际成本。 |

[Lean 单步修复](https://arxiv.org/html/2610.26942v1#S4) · [Exact Replay 作者接收版](https://github.com/rfarell/cslib-holes/blob/5796af7ad8bbe28e663381ab67082ac62583bac4/paper/ai4math_main.tex) · [ExVerus 原文](https://arxiv.org/html/2603.25810v2#S3) · [BlueprintRepair 原文](https://arxiv.org/html/2607.28110v1#S3) · [BlueprintRepair 可选动作](https://github.com/Karifannaa/BlueprintRepair/blob/954edd366a0d1474ecfebe418d4cac14aaf8c6bf/src/blueprintrepair/blueprint_tools.py#L853-L936) · [Goedel-Architect 修订提示](https://github.com/goedelarchitect/goedel-architect/blob/300d69e97c91a2a498091c898e736af69f391960/goedel_architect/prompts/blueprint_refinement.md#L13-L24) · [Goedel-Architect 复用实现](https://github.com/goedelarchitect/goedel-architect/blob/300d69e97c91a2a498091c898e736af69f391960/goedel_architect/refine.py#L618-L706)

LeanMarathon 也在长程工作中机械限制 Worker 的编辑范围，失败时向 Refiner 提交证据。其保护、升级和全局重整流程进一步压缩了调度层的新颖性。把锁当作软约束，按最少放宽恢复可行，属于已有的最小修正集和 MaxSAT 思路。D3.8 只能评估 Lean 状态中是否存在可利用的特定证据与可测效果。[LeanMarathon §2.2–3.2](https://arxiv.org/html/2606.05400v1#S2.SS2) · [最小修正集](https://ijcai.org/proceedings/2013/98) · [基于核和修正集的 MaxSAT](https://ijcai.org/proceedings/2015/41)

## 窄假设与反证

令 $P$ 是已核验、暂时禁止修改的具名绑定，$A$ 是各方法共享的固定动作支持，$h$ 是检查边界，$R\subseteq P$ 是允许改动的绑定集。定义 $V(R)$ 为保留 $P\setminus R$ 时，在 $A,h$ 下的闭合证据。结果分别为 `CHECKED_PROOF`、`CLOSED_NO_PROOF` 或 `UNKNOWN`。释放只扩大合法动作权限，当前声明要到候选验收后才替换。此前已经证明的命题仍在其原环境中成立。

对指定的释放代价 $c$，只有当一个 $R^*$ 产出干净环境复验通过的相同目标，而且所有 $c(R)<c(R^*)$ 的合法范围都有独立闭合否证，才记最小释放。超时、编译进程错误、未穷尽候选及不完整的依赖图留下 `UNKNOWN`。若 Lean 在原始声明和域下证明锁定范围不可满足，可以报告更强的该范围不可满足结论。可重放的候选穷尽仍限于给定支持。保护快照须绑定 Lean 工具链、导入、目标表达式、受保护声明及其真实依赖。变动的依赖闭包要重验，即使下游源码字节相同。末端验收应核对目标身份和允许的公理闭包，普通编译退出零可接受含 `sorry` 的文件。[Lean 4.27 证明验证手册](https://lean-lang.org/doc/reference/4.27.0/ValidatingProofs/)

以同一源快照、诊断、编辑动作和候选支持比较零释放、任意合法类型化修补、原子源代码补丁、完整重写、直接 Lean 自动化、按释放代价排序的精确枚举，以及带证明的选择策略。共同计入闭包证书、失败搜索、依赖重验和端到端墙钟。一个成功动作可以证明该动作在这个实例上有用。方法差异还须在等成本下提高核验证明覆盖，或在同等覆盖下降低成本。没有减少检查与重验的选择器，即使返回最小释放，也与强精确枚举的输出相同。

必须保留零释放可修复、真正需一次或两次释放、无解与超时、以及过期依赖回执等对照。允许保留旧正确声明并使用另一条合法证明。若该路线能在同一支持内达到相同目标，就推翻这个实例的强制释放标签。当前 D3.8 小有限算术控制可用于验证保护范围的机制。若直接 `decide` 或现有类型化修补已覆盖且更便宜，应把结果归为机制证据，不进入新模型试验。只有找到独立真实证明开发中的多例同目标成本空间，再考虑扩测。
