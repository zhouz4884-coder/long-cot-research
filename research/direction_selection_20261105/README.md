# 本轮交付入口

- [研究问题、三方向取舍与论文核对](RESEARCH_DECISION_ZH.md)
- [最终实际状态与结论](RUN_STATUS_ZH.md)
- [硬件原话逐项审查](hardware_quote_review.md)
- [问题、尝试、分析与可证伪猜想](WORKLOG_ZH.md)
- [P0独立协议审查](p0_minimal_protocol_review.md)、[源码审查](p0_source_review.md)
- [原文核验与近邻工作](agent_reference_audit.md)

本轮不会恢复旧18周队列，不训练、不量化、不创建定时任务。调研主目标是有效长程推理；当前短试验只是决定“证伪后状态恢复”是否值得继续。

## 证据层级

1. `inputs/manifest.json`绑定两份用户PDF与讨论文本，`renders/`用于逐页检查。
2. `cpu_cache_consistency_control.py/.json`：随机模型、float64、30组缓存机制控制，无预训练模型任务成绩。
3. `tiny_cpu_p0_interface_v2/`：随机tiny Qwen3与字符分词器，只验真实脚本接口，不能作为Qwen3任务表现。
4. `p0_qwen3_4b_fp16_01/`：真实Qwen3-4B、单3090、FP16/eager，16个人工注入短状态×5臂；全部原始JSON、全词表logits NPZ、manifest和冻结严格评分均保留。
5. 真实结果的补充解析/独立复算属于事后分析，必须与冻结严格评分分开。不从其中选择较有利的指标宣称成功。
6. V100平台/环境与ModelScope下载是基础设施记录；没有GPU分配就没有V100模型结果。

`v100_platform_inventory_02.json`包含其他队列的原始只读状态，属于本地诊断材料，不应作为对外分享附件；交付清单只列与当前研究相关的必要证据。

## 可重复方式

CPU控制需要Python和Torch；请给新输出路径，保留原始记录：

```powershell
python -X utf8 D:\ACL\research\direction_selection_20261105\cpu_cache_consistency_control.py --output D:\ACL\research\direction_selection_20261105\cpu_control_recheck_new.json
```

`real_model_p0.py --help`提供真实模型参数。真实首轮使用Transformers4.55.2、Torch2.8.0+cu128、safetensors0.8.0；只读复用已重验全部文件的Qwen3-4B，并未重新下载该4B模型。V100的单独ModelScope下载是Qwen3-1.7B，不是同一模型的跨设备复现。

GPU脚本不会下载模型、自动选卡或提交PBS。V100默认要求PBS分配；standalone模式要求显式授权的GPU标识，检查compute进程并转成UUID绑定。运行时必须使用新的输出目录，不能覆盖旧manifest。所有分支沿用原position_ids和缓存槽位；mask没有释放显存。

远程启动器有1200秒外层超时，真实脚本设1180秒看门狗；实际运行结束即写launcher状态并检查释放。下载和隔离环境脚本不包含登录凭据；凭据仅由现有授权本地路由/会话输入提供，不进入研究源码或产物。
