# ACL新私有仓库：凭据、历史与上传范围审查

日期：2026-11-06。只读对象：`D:\ACL`当前跟踪/未忽略未跟踪文件、索引blob、全部本地refs可达blob/commit；未读取凭据helper返回值或外部credential store，未commit/push、改原证据/源码、改索引/ref或运行GPU。匹配值、私钥、token、密码、commit正文和个人信息原文均未输出或落入审计文件；仅记录路径、规则、计数及不透明文件ID。

**结论：两轮文本扫描均未检出具体凭据签名/字面凭据候选，不存在已发现的凭据理由要求放弃原50个提交。但这不是“仓库全文无秘密”的证明，也不等于所有内容已获公开再分发许可。** 原文、用户输入、binary和运行元数据须保留各自来源/扫描边界。

## 1. 本次已选范围

主任务已决定将ACL研究工作上传到新的[私有研究仓库](https://github.com/zhouz4884-coder/long-cot-research)：

- 保留原HEAD的**50个commit祖先**及既有研究材料。原论文、用户提供输入按原来源属性保留；不为这些材料新授开源许可，不声称已对PDF/所有全文完成secret-free认证。
- 只推送拟定分支及其祖先；**不mirror、不推直接tree-valued的本地ref**。
- 新当前文件排除运行环境/缓存、重复交付ZIP、`research/**/renders/`、`official_sources`原始依赖副本（保留JSON manifest）、其他队列的V100 inventory02。
- 真实case JSON、固定输入、模型/源码manifest及readout logits NPZ属于研究证据；不因其含“cache/token”字样就删去，也不当作安装缓存。
- private不允许上传secret。root随后对最终stage做增量凭据扫描、逐blob字节/SHA验证与发布ref/可见性核验。

上述选定范围已写入`publication_inventory_20261106.json`的`selected_publication_scope`及各当前文件的`selected_scope_action`。原`recommended_action`保留为更保守的通用发布分类，两者目的不同。按**本次被审计的2,015文件快照**映射：保留研究范围1,506项、另保留source manifest 1项，排除508项；不是最终Git index或已上传文件数。

## 2. 实际覆盖与复核

| 范围 | 本次计数/覆盖 |
|---|---|
| 当前索引跟踪路径 | 1,154 |
| 扫描启动时未忽略未跟踪路径 | 861；早期预查为852，期间其他代理新增了审计/阶段文档 |
| 当前内容清单 | 2,015文件；1,371文本扫描、17空文件、477运行环境内容跳过、150 binary/archive内容未解码 |
| 文件系统元数据 | 7,119文件，约1.36GB；`.git`内部目录与reparse目标不遍历，忽略目录内容仅计元数据 |
| 全refs+索引可达内容对象 | 1,152 blob + 50 commit = 1,202；其余399 tree只解析路径/元数据 |
| 历史文本覆盖 | 1,121文本对象完整流式检查、1空对象、80 binary/archive未解码；50个commit正文/metadata纳入 |
| 凭据候选 | 当前0文件；全部可达历史0对象；具体凭据规则匹配计数均0 |
| 独立history复核 | 同一1,202对象，独立扫描亦0；50个commit另行credential-only检查亦0 |

扫描规则覆盖已知PAT/API-key特征、Bearer字面量、含密码URL、明确credential字段的字面赋值和PEM/OpenSSH私钥材料；过滤常见placeholder。**没有“出现token就判secret”的规则**。规则不能识别任意自定义格式、编码/加密/压缩后的秘密；没有对候选作联网有效性验证。

隐私提示只计数，不输出值：当前出现13次私网IP、6次Windows个人路径、37次Linux home路径、24次email模式；全可达内容对象相应11/6/17/124次。email包含论文作者/Git作者等可能公开信息，不能自动视为secret或个人泄露。运行端点、绝对路径和队列信息按来源与本次private范围处理，不把这些计数改成凭据阳性。

审计前后HEAD均为`e4dad602a93d0ea9125a947297fc01e3641f0bdf`。当前工作树存在并行编辑，故最后的stage仍需root增量检查。审计自身新增报告/脚本也不冒充已经包含在最初2,015个文件的冻结清单中。

## 3. 必须区分HEAD历史与额外tree ref

本地refs含1个commit-valued ref及1个直接tree-valued ref。只枚举commit树会漏掉额外tree的文件路径；已用`rev-list --objects --all`代表路径补齐全部blob的映射，并保存metadata-only refinement来源hash，未重新解释或隐藏凭据结果。

| 可达范围 | 唯一blob/未压缩对象大小 | 需理解的内容 |
|---|---:|---|
| HEAD的50commit祖先 | 907 / 474,192,881 bytes | 7份原论文PDF、12份自生成figure PDF、8项用户来源文档，以及历史数据/日志/来源记录 |
| 非HEAD祖先的额外ref对象 | 245 / 66,551,273 bytes | 4交付ZIP、2用户输入PDF、输入摘录/render、`v100_platform_inventory_02.json`及其他快照对象 |

普通指定分支push不自动发布一个不在该分支祖先内的tree ref；mirror或额外refspec会扩大范围。额外tree内的**当前文件**仍可能通过新的`git add`进入分支，因此必须另按当前排除规则处理，不能只依赖“不推tree ref”。

旧HEAD中已有原论文：

- `experiments/radar20261013/provenance/literature_20261014/PDFs/`下ASAG、REFRAIN、ConformalThinking、DTSR、DEER五份PDF。
- `research/long_cot_landscape_20261105/sources/2026.acl-long.1298.pdf`。
- `research/long_cot_landscape_20261105/sources/2026.findings-emnlp.672.pdf`。

旧HEAD中的用户来源包括`docs/next_phase/USER_DIAGNOSIS_20261013.txt`、`USER_ROADMAP_20261013.md`及`goal_sources/`。本轮已选保留private研究历史，不能再写成“已全部从仓库排除”。今后若改为公开/不含原文的发布标准，须另建经过许可/隐私处理的快照或在独立副本处理历史；单加ignore不改变旧对象。GitHub文档也区分工作树删除与历史移除。[GitHub历史敏感数据说明](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)

自生成`figures/*.pdf`不能仅凭扩展名与下载的论文全文混为一类，本次清单已修正这一区别；图的来源仍由研究产出链确认。

## 4. 新当前文件应排除的具体对象

| 对象 | 证据与本次处理 |
|---|---|
| `research/p05_design_review_20261105/runtime4552/` | 实际4,560文件、113,469,873 bytes；普通untracked候选内486项。环境用版本/requirements/源码hash复现，排除package副本。 |
| cache/vendor/model安装物 | 原`.gitignore`已有`.tools/`、`vendor/`、`models/`、`.venv/`、`__pycache__/`、`*.pyc`等；保持，不将安装物force-add。 |
| 交付ZIP | 元数据共6个ZIP，当前5个未忽略；是现有源码/证据的打包交付副本。ZIP之间无字节相同对，不把“语义上重复打包”写成hash重复。成员内容未解压扫描。 |
| `research/**/renders/` | 12个当前候选render排除，避免复制用户/来源文档整页；原本用户PDF/输入按主任务选定范围保留。 |
| `research/**/official_sources/` | 排除4项raw依赖副本；保留1项JSON source manifest，记录原URL/版本/hash。 |
| `research/direction_selection_20261105/v100_platform_inventory_02.json` | 其他队列inventory排除；它只在额外tree快照范围，不在原HEAD祖先。禁止随新add再带入。 |

需要排除的交付ZIP路径：

- `docs/next_phase.zip`
- `research/algorithm_mechanism_20261105/长思维链_算法构想与文献数学分析_20261105.zip`
- `research/direction_selection_20261105/长思维链_方向判断与首轮证据_20261105.zip`
- `research/next_design_20261105/长思维链_下一轮设计与CPU审计_20261105.zip`
- `research/p05_design_review_20261105/长思维链_P05五臂结果与四项设计核查_20261105.zip`

`outputs/reason-transition-final-20261013.zip`已由既有ignore排除。以上只是本次当前候选的排除，不删除本地交付文件，不改历史证据。

可采用的**窄范围**ignore建议（由root在本轮处理，本审计未改）：

```gitignore
research/**/runtime4552/
research/**/__pycache__/
research/**/.venv/
docs/next_phase.zip
research/**/*.zip
research/**/renders/
research/**/official_sources/*
!research/**/official_sources/*manifest*.json
research/direction_selection_20261105/v100_platform_inventory_02.json
```

这里`research/**/*.zip`对应本次交付打包文件；若未来确有唯一原始输入ZIP，要显式列入不同来源策略，不能静默丢掉原始输入。不要排除整个`research/`、整个`inputs/`或所有NPZ，因为本次已选保留用户输入和真实诊断证据。

## 5. 大文件、重复证据和字节完整性

当前最大文件是已忽略的`experiments/radar20261013/data/lcb_v6_source.jsonl`（134,303,240 bytes）；已忽略embedding模型权重约90.9MB。最大待排除交付ZIP约58.1MB；全可达Git最大blob约27.85MB，没有>100MiB的可达blob。GitHub普通Git文件>50MiB会提示、>100MiB会阻止，安装环境和打包副本仍不应因“低于单文件限额”就进入研究库。[GitHub大文件说明](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github)

`results/`与`recovery/`存在重复或历次快照raw bank；最大同尺寸例为两处27,029,425-byte的online JSONL。本次保留研究历史，不删除或合并旧证据；报告与索引应明确canonical当前结果、恢复快照和失败记录，避免把重复文件当额外独立实验。inventory提供全部≥10MiB路径及对象信息。

原`.gitattributes`是`* text=auto eol=lf`，研究源码/JSON当前仍落入该规则。建议本轮增加：

```gitattributes
research/** -text
```

然后从**最终暂存blob**读取原始字节，与本地冻结源、case JSON、parser、manifest成员逐项比较SHA256。不能只检查工作树hash或文件名；也不应为通过检查而改写旧manifest/科学证据。本次明确的132-member frozen manifest完整性由root staging验证给结果，审计未先行声称132项已上传或已复核。

## 6. 交付与下一道门槛

- `publication_inventory_20261106.json`：当前清单、全部可达内容对象、rule/count、大小、ZIP目录元数据、HEAD/额外ref区分，以及已选private范围。
- `history_credential_audit_independent.json`：独立history复核，凭据候选0与binary覆盖限制。
- `audit_publication_inventory.py`、`refine_publication_inventory.py`：只读内容扫描与metadata修正工具；扫描原SHA和后续分类/修正SHA均记录在inventory中。修正没有重跑秘密匹配或改旧文件。

本次没有凭据候选需要贴出、验证或旋转。若最终增量扫描发现真实凭据，应先排除该内容并处理有效凭据；private不构成例外。[GitHub敏感数据处理说明](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)

root下一步按已选范围stage、验证暂存blob字节和新增内容，再只推目标分支。对外陈述应为“已完成指定文本规则的当前/历史扫描，未检出凭据候选，binary/原文及来源权限边界保留”，而非“全仓库已证明无秘密/已统一开源”。
