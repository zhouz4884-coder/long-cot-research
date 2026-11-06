# Phase5-C：单模型配对读出的32题历史探索库

2026-11-06。**准备完成、CPU审计PASS；没有生成任何新模型输出，新增GPU消耗0。** 这批用于新读出方法的探索比较，不是正式未见benchmark，不称MATH500或新的自然长链发生率测试。

## 选择规则先于质量字段

从两份已冻结历史文件的300个唯一`method=full`问题中，完整排除P1固定100个问题ID。剩余200个ID按以下函数排序，取前32，问题ID作并列次序：

```text
SHA256(UTF8("ACL-Phase5C-natural-readout-bank32-v1-20261106" + NUL + problem_id))
```

选择函数只接收ID/排除集；不接收Gold、旧correct/grade、最终答案、修订词、长度、cap或候选数。不补齐题型、不按模型效果替换样本。P1重叠0，32个问题互异。

排除的是既有P1诊断重叠，不能证明这批题从未被整个历史项目使用或观察过。它们仍属于原300题开发池；后续正式泛化需另外独立数据。

## 文件与接口

| 文件 | 内容与用途 |
|---|---|
| `prepare_natural_bank.py` | stdlib CPU准备与源哈希/选择/导出检查；重复运行只允许字节相同，拒绝覆盖不同冻结结果 |
| `NATURAL_BANK_MANIFEST.json` | 固定选择规则、排除集、输入源/行/题干/trace哈希、各条记录对应关系及生成来源 |
| `bank_visible.jsonl` | 32条`bank_id/problem_id/question/trace_text/trace_ids`和生成元数据；无外部Gold、旧grade、旧最终forced读出或旧correct字段 |
| `bank_evaluation_only.jsonl` | 32条Gold、旧grade/答案/正确性及题型元数据；只能在生成结束后离线评价，不能进入候选提取、G、投影、重试或方法选择 |
| `BANK_METADATA_SUMMARY.json` | **选完后**统计的题型、长度、cap与历史评分，不是语义事件率或新模型结果 |
| `BANK_PREPARATION_AUDIT.json` | 300→200→32计数、P1重叠0、32源行/trace重数、输入原字节未变及产物hash |

模型接口必须明确从`question`和`trace_text`或声明的原`trace_ids`构造提示；不要把整个visible记录序列化给模型，不要把eval文件join进在线数据对象。visible正文可能包含模型自己在思考中写出的候选/boxed结论，这是既有轨迹内容，不是另外注入Gold。

`trace_ids`是历史生成记录原ID；`trace_text`保留历史解码文本。没有声称对文本重编码必然恢复原ID，也没有伪造原执行环境/模型哈希。若新比较重编码文本，应让各臂使用同一固定表示并明确新协议。

## 选择后统计

- 32题；5条思考达到8192保护顶，27条思考记录为`natural_end`。
- 长度1088–8192 tokens，总121870，均值3808.4375，中位数2749。
- 六个学科子类：Algebra10、Intermediate Algebra9、Number Theory6、Prealgebra3、Precalculus3、Counting & Probability1。本批随机ID选择没有几何题，不补样；这些学科不是六个独立数据集。
- 旧forced读出/旧评分记录为26对、6错；这只是来源质量元数据，不作新读出基线，也不用于筛题。

所有轨迹都是**有8192思考保护、随后独立forced boxed答案读出**的历史FULL策略，不是native uninterrupted。27条思考自然闭合也不能把其后的forced读出当成原生整轮EOS。历史执行代码/权重不可变哈希缺失，精确复现原采样行为尚不成立。

## 复跑

```powershell
python -X utf8 research/phase5c_goal_contract_20261106/prepare_natural_bank.py
```

准备代码不调用torch、模型、远程、凭据或GPU。原P1、原题和原两份历史文件均按字节校验且未修改。准备过程只读取生成数据所需字段，没有人工精读所选32条正文，也没有按其答案决定方法或参数。

冻结主hash：manifest `c29222437a20dabd790aac4292c0fa4812929a9638219e799d6bef414df311f7`；visible `3c75c9814e7635d68ae476ab8dcc6617faa2be6d9eea68b481ecca724c04d139`；evaluation `73b90f2311f190f7be8894181fc6f7dc9d49a7269d9fc566d1ad62e87cffb1ee`。本README不进入上述数据manifest的自引用哈希。
