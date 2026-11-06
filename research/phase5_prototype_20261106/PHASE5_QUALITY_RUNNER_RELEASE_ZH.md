# Phase5 质量优先 runner：CPU release

2026-11-06。已实现 `phase5_quality_runner.py`；本轮仅做 CPU 随机 tiny 验收，未运行真实模型/GPU/远程，也未 Git commit/push。

以上是CPU release阶段范围；后续由主任务执行的真实模型partial轮另见[RUN_STATUS_ZH.md](RUN_STATUS_ZH.md)，不将随机CPU成绩当作模型质量。

## 冻结绑定

- runner：`0eab8a3a62381db7f56c9cf9101647703cb8e1208d9f3c38e25eec59fafcd2f9`
- adapter：`3556baa0920b344e87f22037c584f7d2bde77bbdede9808c4e360fc00200890f`
- prepared dataset digest：`5260ad988fd9dfe97c186ad9fb7970c7a8cc91540de86f6be59c3de26c6b723b`
- topology v2：`93f39936cb5d1dbdbc1eb647d1c0f228be11cf49f23d14b7b2163b52d01902d1`
- base：`246219aee9774fae0966c7663c765daf3dba2f1df68bc054b539a4dd5d64331b`
- parser：`c2bc053b66778288f524d46f4353e825b1ee654d829027bd02b1cb3173255eed`
- real Qwen3-4B assets manifest：`37ff9857bb53edf35d5c80bfa0c078b1cdb8d5e5aa864115d153e237cb854511`

数据/adapter/base/parser 任一不匹配即停止；真实模型只能使用既定 4B 资产、TF4.55.2 与 Torch2.8.0/2.4.1、FP16 eager。GPU 必须由 `CUDA_VISIBLE_DEVICES` 和 `--standalone-gpu` 指定同一个完整 UUID，继承 base 的启动前空 compute-process 检查；这不是持续排他锁。

## 本轮安排

先 6 个能力控制（2 个 P-only + 4 个精确去重 P+R），再按以下六状态顺序逐例完成四臂：

`T1E → T2E → T1C → T2C → T1W → T2W`，均为 support_before_fault。

每例顺序是 SharedGDirect、SharedGCompact、SharedGStepwise、VersionFrame，共 24+6=30 个真实计划输出。所有主方法共享根 G、规则/graph、旧 B/R，y/z 不认证；basis 不提供 G 或 B。模型只看到 adapter 的 messages 投影，不序列化隐藏字段或 case/group ID。

这些都是 one-shot 提示原型；没有逐节点数值 checker、运行时证书升级、按 E/C/W 标签旁路、KV mask/crop、teacher-forced scoring、候选 probe、尾窗注入或训练。

真实轮贪婪直到模型配置 EOS 或 512 个新 token 保护顶；原 base 的“单整数+换行”提前停止被明确去掉。解析器只在生成结束后评分，不影响停止。保存 numeric_correct 和 eos_and_correct 两个口径，cap/未解析保留在完整四臂分母；E/C/W 单列。预算不足只保存完整配对及进行中的原文，不补题/重试。

G/图 bookkeeping 对每个主请求从 visible 重新执行并计 CPU 时间；prompt 编译/tokenize、prefill、decode 分项记录。准备数据/模型哈希/加载以及全部 IO 仍在全局 270 秒中。请求总时间已含其分项，不能再次相加；forward ledger 只统计模型前向，不冒充含工具/加载的整个实验成本。

## CPU 验收

实际使用 `runtime4552` 的 TF4.55.2 / Torch2.11.0+cpu，3 层随机 tiny Qwen3、确定性的八字符 chunk fixture tokenizer、8-token CPU 测试顶。后者只为便宜覆盖长工作帧接口，不能与真实 Qwen tokenizer 或质量分数比较。

`tiny_quality_cpu_4552_final` 完成 3 个 T1 E/C/W 状态 ×4 +6 basis=18 输出，约 5.47 秒；`CPU_QUALITY_RUNNER_ACCEPTANCE.json` 共 19/19 检查通过。实际模型账本 145 次前向、4287 个输入 token（含一次 no-op）；同 prompt 最后 logits 最大差 0、生成后的原分支 KV 最大差 0。

随机 tiny 的18输出均在8-token顶结束，未得到有效答案；它不动态覆盖 EOS。为此另设 `strict_EOS_mock_control.json`：明确序列 `123\n` 后继续到 EOS、EOS 后不再 forward、无 EOS 则 cap、原 checkpoint 不变四项全部通过。该 mock 不是 Qwen 实验，未混入模型 ledger。

## CPU CLI（已用相同参数验收，输出目录需新建名）

```powershell
python -X utf8 D:\ACL\research\phase5_prototype_20261106\phase5_quality_runner.py --model tiny-random --device cpu --cpu-interface-check --runtime-dir D:\ACL\research\p05_design_review_20261105\runtime4552 --output D:\ACL\research\phase5_prototype_20261106\tiny_quality_cpu_new --max-seconds 270
```

## Real worker CLI 模板（交主任务填入已授权路径/UUID）

```bash
CUDA_VISIBLE_DEVICES="$QUALITY_GPU_UUID" python source/phase5_quality_runner.py \
  --model /path/to/read-only/Qwen3-4B \
  --data data/P05_topology_cases_v2.json \
  --adapter-path source/prepare_cpu_input_adapter.py \
  --base-path source/p0_base_frozen.py \
  --parser-path source/frozen_answer_extractor.py \
  --output output/quality_01 --device cuda:0 \
  --standalone-gpu "$QUALITY_GPU_UUID" --max-seconds 270
```

外层总限由主任务执行：worker270 / outer285 / kill-after5，累计单卡≤300秒。worker 自身没有延长或重新入场逻辑。不要把退出0当全部完成：读 summary 的完整 main/basis 数、cap/EOS、deadline/error，以及每个 job 的 complete。

每32个生成 token保存一次进行中片段；中断的 in-flight forward 不伪造为已完成成本，deadline墙钟和当前stage保留。初始 `rendered_jobs.json` 在任何模型 forward 前写入全部本轮消息/token/位置，manifest 绑定其 SHA；逐 job和逐case JSON保留raw、controller证据、grader和成本。
