# 真实quality轮：输入与取回完整性独立核对

2026-11-06。只读核对`results/quality_round_01`及prelaunch文件；未运行模型/GPU、连接远程、修改parser或原始结果。

**完整性核对通过。两条VersionFrame的unparsed是输出格式契约未满足，不是这两条输出中观察到的算术错误；冻结主评分保持不变。**

## 完整性证据

- `RESULT_RETRIEVAL_MANIFEST.json`的**33/33文件**，本地bytes及SHA256逐项相符，包含30个results文件及3个launcher/log文件。
- prelaunch列出的8个源/输入/协议/render文件与本地对应字节及SHA相符；独立源码审查、CPU验收文件hash也与冻结记录相符。
- 取回prepared dataset、prelaunch snapshot及运行manifest均绑定dataset digest `5260ad988fd9dfe97c186ad9fb7970c7a8cc91540de86f6be59c3de26c6b723b`。
- 全部**30个预定请求**的messages、完整prompt文本、token IDs和连续position IDs，与`rendered_inputs_01.json`逐项一致。19条完成请求的`rendering`又与其对应运行row完全一致；未发现请求错配或隐藏evaluation字段进入prompt。
- runner为`0eab8a3a62381db7f56c9cf9101647703cb8e1208d9f3c38e25eec59fafcd2f9`，adapter为`3556baa0920b344e87f22037c584f7d2bde77bbdede9808c4e360fc00200890f`，原输入为`93f39936cb5d1dbdbc1eb647d1c0f228be11cf49f23d14b7b2163b52d01902d1`，均与prelaunch及请求记录相符。
- 取回manifest的模型文件清单按原算法重算aggregate为`37ff9857bb53edf35d5c80bfa0c078b1cdb8d5e5aa864115d153e237cb854511`；记录环境为Torch2.8.0+cu128、Transformers4.55.2、FP16/eager。此处是manifest一致性核对，没有重新读取远端权重。

旧224项冻结由主任务统一核；本报告**未全量重算旧224项**，不代替该检查。输出token只核数量、记录关联及末端EOS，未另加载tokenizer重解码。

## 完成分母

19条完成输出为6个basis＋13个单方法主请求。完整四臂case为T1E、T2E、T1C共3个；T2C只有Direct完成，不能补入其余方法配对分母。W主臂未执行，不能宣称已经检验W伤害或全6状态效果。

19条均为EOS结束，无512-token cap；输出token数与实际forward数均为2,994（真实轮没有CPU replay）。状态是`QUALITY_PARTIAL_TIME_BUDGET`，不是30条全部完成。basis的P/PR类型应依ID或`rendering.provenance.kind`区分，summary中的通用`kind=basis`不是P/PR分类。

## 两条Frame未解析的来源

| 请求 | 原始结构与数值 | 冻结接口结果 |
|---|---|---|
| `T1_support_before_fault_E__VersionFrame` | 完整JSON；`3*18+2=56`、`56+24=80`，`final_answer=80` | EOS，102 token；parser为unresolved |
| `T1_support_before_fault_C__VersionFrame` | 同样的完整JSON、候选y/z及`final_answer=80` | EOS，102 token；parser为unresolved |

已独立核算上述两条算式与T1原题一致。输出仍将节点标为CANDIDATE，没有提供运行时外部认证。

冻结parser只接受单整数、终端明确答案标记/boxed整数，或末行完整等式链；它不支持JSON的`"final_answer"`字段。两条输出没有要求的终端`最终答案：80`，最后非空行是`}`，故按预声明规则未解析。应记为**格式交付/接口失败**，而不是把已核算正确的候选数值记述为算术错误。

主表VersionFrame仍为冻结parser下1/3正确、2条unparsed；不能事后改parser、回填3/3或把JSON诊断当作算法提升。本轮材料也不支持“19条全部推导均正确”或6状态完整成功等更强说法。两条JSON的正确候选与交付失败可同时保留，后续输出契约调整须另行预先冻结。
