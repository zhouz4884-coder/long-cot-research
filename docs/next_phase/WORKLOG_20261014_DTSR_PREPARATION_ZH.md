# 2026-10-14 DTSR独立适配准备

上一轮属于实质进展；本轮开始现场确认native两个进程1804357/1804358和接续监督器1780322存活，未重启。数据完整前不冻结正式参考或主策略。

独立核对正式DTSR论文第4页实现和算法、附录信号/提示定义，发现原默认阈值100、间隔64，与现有主Engine的128-token段落hook不同。实现独立token级decoder，避免用容易接入的近似接口替代指定基线。

新增 `dtsr_adapter.py`、`evaluate_dtsr_online.py`、`validate_dtsr_gpu.py`、`freeze_dtsr_protocol.py`。评分只看题目/已生成thought；auxiliary生成与prefill全计费，未知rating继续；数据/源代码/协议/模型与固定ID分片绑定，final-test入口要求独立冻结与零测试记录。具体与作者vLLM、模型尺寸及原提示的差异均明示。

四个CPU协议控制本地/远端通过：合法有限rating、拒绝解释/多数字/越界、64处触发、低/未知rating保留完整给定token轨迹。测试输入词边界错误保留在决策日志。源码逐文件部署SHA核对并编译。没有GPU验收或DTSR实际成绩，代码/CPU控制不计为研究性能。

实际下一动作：native完整后科学审查和新formal准入；GPU空闲时检验DTSR父KV及同种子续写，随后选择集真实对照。研究范围仍为完整18周适用阶段。判断、问题、尝试与不良效果的可检验猜想见D10。
