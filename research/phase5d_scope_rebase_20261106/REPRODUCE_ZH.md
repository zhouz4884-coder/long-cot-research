# 阅读、复算和复跑

2026-11-06。先看STAGE1_CLOSEOUT_ZH.md确认范围。复查原始记录不等于重新运行GPU，更不等于已做修复效果试验。

## 本地CPU

在仓库根目录运行：

```powershell
python -X utf8 research/phase5d_scope_rebase_20261106/prepare_native_data.py
python -X utf8 research/phase5d_scope_rebase_20261106/test_native_engine.py
```

第一条精确复现已冻结GSM8K选样/可见与Gold字节，需仓库旧data/test.jsonl作排重。第二条使用本机隔离runtime4552或等价TF4.55.2环境的随机tiny，不代表真实4B成绩。

CPU支持内核按support_engine/IMPLEMENTATION_AUDIT_ZH.md中的命令运行。D0的39结构/18数学smoke需要Math-Verify0.9.0，测试示例不读取实验Gold调规则。

已有D0选择可直接重新CPU评分，写到一个新输出目录，不能覆盖原结果：

```text
python -B score_d0_audit.py --root D_ROOT --evaluation-file OLD_PHASE5C_EVAL --output NEW_OUTPUT
```

其中OLD_PHASE5C_EVAL是原Phase5-C bank_evaluation_only.jsonl（SHA73b90f…），或review_dependencies内原字节副本。重新提取应使用prepare_d0_audit.py及其已冻结契约，原Phase5-C输入来源核对需要完整仓库，不能只靠本阶段摘要替代。

## 真实GPU

需实际TF4.55.2、Torch2.8.0+cu128和已有Qwen3-4B资产manifest37ff9857…；权重不随材料打包，若需下载遵从用户指定ModelScope路线，逐文件校验manifest而非仅看模型名称。数学评分另用0.9.0 CPU进程。

原生执行器的CLI：

```text
CUDA_VISIBLE_DEVICES=EXACT_UUID python -B native_worker.py --root D_ROOT --model MODEL_PATH --gpu EXACT_UUID --worker 0
```

worker0/1分别负责固定奇偶的4题，同一GPU也可依次运行；不要覆盖原native_results。真实启动需重新建立新输出根目录和冻结清单，保留相同模型/采样/题集可作复现，改任何科学条件须新协议。launch_native.py中的路径/两个UUID是原实际现场配置，不能无审查挪到其他机器直接用。

p0_base_frozen.py是既有项目模型资产核对helper的原字节副本，SHA246219…；不是新算法。native_prelaunch_freeze绑定实际源码/输入，旧首轮结果仍按原记录保存。不要运行provided_kit中的示例来替代加固内核或D1执行器。

## 独立审计与打包边界

原D1的NPZ可重算logits差/KL；调度control的0差/KV字段只保存执行值，详细限制见独立审计，不能补声称未保存的tensor已经二次复核。

local_tokenizer副本不重复交付，hash见LOCAL_TOKENIZER_MANIFEST.json；CPU重放触发谓词时从相同模型资产取得tokenizer文件。权重、依赖环境、缓存和凭据均不打包。复查整个历史的SHA需仓库各阶段DELIVERY_MANIFEST，而非仅本阶段文件。
