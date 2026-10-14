# REFRAIN独立适配与编码器实测准备

目标仍为18周完整研究。此记录是强基线准备，不是正式模型结果或完成交付。

按 [REFRAIN正式原文](https://aclanthology.org/2026.acl-long.1256/) 与冻结的作者源码范围实现独立适配。默认触发词用渲染后的表5排除下划线扩展词；主方法保留反思+前序临时答案+全历史最大语义相似三个门槛。每个空行步骤检查，不复用128-token主hook。

编码器采用 [官方MiniLM模型卡](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) 的masked mean/L2方式，显式256上限、FP32 CPU，直接用已有Transformers，未安装或升级冻结环境。revision及11文件源校验写入 `provenance/refrain_encoder_manifest.json`；权重置于Git忽略的models目录，不冒充已归档到远程Git。

实际证据：五个协议CPU控制本地/远端通过。真实本地编码384维、单位范数、cos相同句近1/反思改写.96135/无关句.06469、padding误差7.45e-8、长输入256 tokens，见 `refrain_encoder_cpu_admission_local.json`。本地torch2.11/Transformers5.4与远端2.8/4.55.2不同，不能把本地结果当远端验收。首次远端加载因为传输尚在运行，SHA检查拒绝；原失败保留，等传输完成后复验。

纠正已实际完成：原SFTP handle成功结束，11文件91,578,415 bytes传完，远端CPU报告passed并已取回 `refrain_encoder_cpu_admission_remote.json`。padding误差6.15e-8，256 tokens，重复/反思/无关cos=1/.96135/.06469。远端四句117.7ms为单次接口遥测，不是基线在线wall-clock。全部MiniLM内容经过实际读取SHA；部署核查表保留新源码哈希和当前5个native源码不变证据。

新入口：`refrain_adapter.py`、`prepare_refrain_encoder.py`、`validate_refrain_encoder.py`、`validate_refrain_gpu.py`、`freeze_refrain_protocol.py`、`evaluate_refrain_online.py`。两GPU保留问题ID的固定物理分配，但只有一个有序bandit流并串行执行，避免改变跨题算法。断点恢复从每个完整请求的likelihood/长度重放bandit并逐条核验状态，不从后验正确率恢复。

时延需另一个真实控制：每题旁执行相同串行调度/驻留/物理GPU的FULL，以问题ID独立哈希预定方法顺序，核验共同思考prefix，Gold在REFRAIN更新后才评分。不把M1双worker FULL时间当serial REFRAIN的无混杂对照。每个split因此需要N次REFRAIN+N次新FULL，实验计费/总工作量应包括两组。

未执行GPU对照、完整选择集或盲测。下一科学依赖：native全部58请求与正式参照审查；GPU空闲时验收三个实际前缀的父KV/共同reader token身份；正式main freeze后独立REFRAIN freeze；再实际执行选择集。所有阈值/默认参数及差异在盲测之前固定。该online-adaptive基线不满足当前per-problem固定潜在结果风险界，不获得M1证书。

判断、错误、解决尝试及失败猜想见 `RESEARCH_DECISION_LOG_ZH.md` 的D13。监督器与两个原native worker仍存活；本轮只增加独立源码/CPU依赖，不改当前native绑定文件。
