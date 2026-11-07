# D2 受限数学核验器

2026-11-07。CPU 验收通过 23 项定向测试，包含 64 组独立整数卷积与多项式商对照。八个完整核验实例保存了输入、绑定、检查轨迹和可重放收据。验收范围为合成结构化语句和声明的数学作用域。[验收证据](RESTRICTED_MATH_CHECKS.json)

## 在线接口

调用方从已观察的前缀和可信输入中登记 `target` 及 `premises`。模型产生的请求使用这份快照的精确绑定。调用方负责来源、目标身份、作用域、原题条件齐全性，以及快照中前提的认证状态。核验器负责重放已登记语句的数学计算。[实现](restricted_math_checker.py)

```python
from restricted_math_checker import make_request, replay_certificate, verify

x = {"op": "var", "name": "x"}
premises = [
    {
        "id": "given-x",
        "version": 2,
        "scope_id": "case-S",
        "scope_version": 0,
        "predicate": {"op": "eq", "lhs": x, "rhs": 2},
        "evidence_id": "trusted-question-premise",
    }
]
target = {
    "id": "square-step",
    "version": 1,
    "kind": "justification",
    "scope": {
        "id": "case-S",
        "version": 0,
        "coefficient_domain": "Q",
        "domains": {"x": {"kind": "integer"}},
    },
    "certificate_type": "ARITHMETIC_EQ",
    "statement": {"lhs": {"op": "pow", "base": x, "exp": 2}, "rhs": 5},
    "required_premises": [
        {"id": "given-x", "version": 2, "scope_id": "case-S", "scope_version": 0}
    ],
}
request = make_request(target, premises)
result = verify(request, target=target, premises=premises)
assert result["status"] == "INVALID_JUSTIFICATION"
assert result["witness"]["lhs"] == "4"
assert replay_certificate(result["certificate"], request, target=target, premises=premises)
```

`required_premises` 精确列出所需 ID、版本和作用域。缺失、额外、重复或过期的记录返回 `UNKNOWN`。绑定同时覆盖目标角色、完整陈述、scope 内的变量域和系数域，以及每条前提的谓词内容。可选的 `source_span` 和 `observed_prefix_sha256` 随目标一起散列。源位置映射由调用方验收。

`make_request(..., mode="counterexample", assignment={...})` 构造点反例检查。赋值须覆盖作用域中声明的变量。系统先核域、前提和原式定义，再计算原命题的真假。普通点代入用于反证多项式整除时返回 `UNKNOWN`。整除是多项式环上的声明，验证需要商、余式和商的系数域。

### 返回状态

| 状态 | `verdict` | `truth` | 对调用方的含义 |
|---|---|---|---|
| `VERIFIED` | `PASS` | `true` | 当前结构化陈述通过核验 |
| `INVALID_JUSTIFICATION` | `PASS` | `false` | 该论证中的具体陈述有反证，退役范围应绑定该论证 |
| `REFUTED_CLAIM` | `PASS` | `false` | 冻结的声明在指定范围内有反证，交由账本处理当前支持和冲突 |
| `INVALID_COUNTEREXAMPLE` | `FAIL` | `null` | 反例出域、针对不同冻结候选，或代入后原陈述仍成立 |
| `UNKNOWN` | `UNKNOWN` | `null` | 快照、定义域、证据或计算范围不足，维持未决状态 |

`PASS` 在反驳场景表示反驳证据成立。程序须同时读取 `status` 和 `truth`，并核对当前快照，再决定账本动作。`replay_certificate` 校验完整收据的可重现性。它同样可以回放有效的拒绝收据，返回 `True` 表示收据完整。

旧支持内核的证书签发流程继续独立运行。接入账本前应把核验结果对应到该账本当前声明或论证的 ID、版本、作用域和陈述。单条证据的作用范围由上述状态限定。

## 支持的结构化语法

表达式接受 JSON 整数及以下对象。计算使用精确 `Fraction`、有界 AST 和稀疏多项式。

| 节点 | 字段 |
|---|---|
| `rat` | `num`、`den` 为整数 |
| `var` | `name` 为已声明变量 |
| `neg` | `arg` |
| `add`、`mul` | `args` 含 2–8 个表达式 |
| `sub`、`div` | `lhs`、`rhs` |
| `pow` | `base`、整数 `exp`，绝对值不超过 12 |

域必须声明 `kind` 为 `integer`、`rational` 或 `real`。可选 `lower`、`upper`、`lower_closed`、`upper_closed`、`exclude` 与显式有限集合 `values`。实数域上的符号相等可用有理系数多项式证明，点证据目前使用精确有理数。零的非正次幂和零分母会产生未决结果。

| 证书类型 | `statement` 结构 | 判定范围 |
|---|---|---|
| `ARITHMETIC_EQ` | `lhs`、`rhs` | 闭式，或由可信等式前提和单点域确定的值 |
| `POLYNOMIAL_IDENTITY` | `lhs`、`rhs`、可选 `semantics` | 默认 `scoped` 核作用域内原式相等。显式 `formal` 比较多项式系数 |
| `POLYNOMIAL_DIVISIBILITY` | `dividend`、`divisor` | 单个非零多项式除式。在 Q 上精确长除，声明 Z 时额外要求商的所有系数为整数 |
| `SUBSTITUTION` | 冻结 `assignment` 与 `constraints` 数组 | 核候选是否满足已登记的完整约束合取 |
| `DOMAIN_PREDICATE` | `predicate`，可选冻结 `assignment` | 有明确取值的范围谓词 |

范围谓词支持 `eq`、`ne`、`lt`、`le`、`gt`、`ge`，以及 `is_integer`、`positive`、`nonnegative`、`in_domain`、`coprime`、`distinct`、`vector_dimension`。关系类使用 `lhs/rhs`，单参类使用 `arg`，`in_domain` 额外给 `domain`，`distinct` 给 `args`，向量维数给 `items/size`。

## 作用域与分母检查

每次原始除法和负幂都会保留非零义务，化简后的表达式仍携带这些义务。`(x²−1)/(x−1)=x+1` 可以在域明确排除 1 或可信前提 `x≠1` 时成立。无这类范围证据时，核验器报告 `original_denominator_guard_unproven`，并给出尚待证明的多项式守卫。若反例明确选择已排除的 `x=1`，则拒绝该反例。

守卫目前通过非零常数、可信前提定值、一次根被域排除、显式非零前提或完整有限域枚举解决。超出范围的非零证明返回未决。默认 `scoped` 相等中，非零系数差还须找到域内具体反例。完整有限域可逐点验证相等，例如 `x²=x` 在 `{0,1}` 上成立。显式 `formal` 系数相等使用另一套已绑定的陈述含义。

## 资源与验证结果

| 限制 | 当前值 |
|---|---:|
| JSON 节点与深度 | 4096 / 32 |
| 变量、前提和约束 | 4 / 16 / 24 |
| 幂指数绝对值、多项式度、项数 | 12 / 24 / 256 |
| 输入整数、中间系数分子和分母位数 | 256 / 1024 |
| 原始非零义务、候选见证点 | 48 / 128 |
| 确定性工作单位 | 60000 |

输入形态和计算复杂度超界时返回未决。`work_units` 是结构化工作计数，CPU 时间独立记录。结果包含 `binding`、`witness`、`trace` 和收据摘要。多项式见证给项数、前 16 项和完整摘要。收据可通过精确重算复核。

| 实际 CPU 实例 | 观察 |
|---|---|
| `x=2` 下算出 `x²=5` | `INVALID_JUSTIFICATION`，值为 4 与 5 |
| 整数域 `x≥1` 下以 `x=2` 反驳 `x²=x` | `REFUTED_CLAIM` |
| 把排除点 `x=1` 当作分式反例 | `INVALID_COUNTEREXAMPLE` |
| 消去 `x−1` 却缺非零条件 | `UNKNOWN`，轨迹保留原守卫 |
| 加入有效非零范围后检查同一分式 | `VERIFIED` |
| `2x` 整除 `x` | Q 上成立，Z 上商 `1/2` 违背系数域 |
| `−3` 代入 `x²=9` 与 `x>0` | 第一项满足、第二项不满足，合取被反驳 |

实现过程中发现 Python 字典相等会将 `true` 与 `1` 视为相同。请求绑定和收据回放都改用规范 JSON 摘要，测试覆盖该类型混淆。正式运行调用方保留输入和收据即可对每次判断复算。自然语言目标抽取、作用域认证、事件覆盖及对答案的影响由后续在线评测分别测量。[测试与复跑入口](test_restricted_math_checker.py)

```powershell
python -X utf8 -m unittest discover -s research/phase5d2_quarantined_rebase_20261107 -p test_restricted_math_checker.py -v
```
