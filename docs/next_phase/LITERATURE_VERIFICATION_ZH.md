# 文献与实现核查记录

核查日期：2026-10-13。使用 nature-academic-search 的引文核查流程；学术检索 MCP 未挂载，使用正式论文页面、arXiv 原文和作者仓库。下列 13 项均找到对应原始记录；摘要/相关方法已核查不等于完整精读，更不等于已复现。

| 记录 | 书目信息核查 | 来源与当前核查范围 |
|---|---|---|
| Conformal Thinking | verified，ICML2026 | [PMLR](https://proceedings.mlr.press/v306/wang26hd.html)；正式摘要、作者 preliminary 代码。原始 PDF 接口失败、OpenReview 验证页阻断；不能声称完整原版复现。 |
| Statistical Early Stopping | verified，ICML2026 | [PMLR](https://proceedings.mlr.press/v306/xie26z.html)；正式摘要/方法范围，未复现。 |
| When to Trust the Cheap Check | verified，ICML2026 | [PMLR](https://proceedings.mlr.press/v306/kiyani26a.html)；风险对象与两阈值结构；未复现。 |
| Reasoning Theater | verified，ICML2026 | [PMLR](https://proceedings.mlr.press/v306/boppana26a.html)；探针/早期读出与推理过程区别；未复现。 |
| Dynamic Early Exit | verified，ICLR2026 | [正式页面](https://proceedings.iclr.cc/paper_files/paper/2026/hash/8df90a1440ce782d1f5607b7a38f2531-Abstract-Conference.html)；PDF 第3.2/3.3节、PRo 和缓存章节；固定作者源码快照52文件。 |
| DTSR / When Is Thinking Enough | verified，ACL2026 | [ACL](https://aclanthology.org/2026.acl-long.1080/)；正式摘要；未复现。 |
| REFRAIN / Stop When Enough | verified，ACL2026 | [ACL](https://aclanthology.org/2026.acl-long.1256/)；正式摘要；未复现。 |
| ASAG | verified，ICML2026 | [PMLR](https://proceedings.mlr.press/v306/li26ev.html)；正式摘要；未复现全部生成策略。 |
| SEVRA / Think Again or Think Longer | verified，2026预印本 | [arXiv](https://arxiv.org/abs/2606.19808)；HTML 中动作/标签/阈值/成本/局限；固定作者源码快照27文件。 |
| AERA | verified，2026预印本 | [arXiv全文](https://arxiv.org/html/2608.27964v1)；残余效用定义、二元奖励下可修复性等价、顺序控制范围；未复现。 |
| ReASC | verified，2026，arXiv注明ACL | [arXiv](https://arxiv.org/abs/2601.02970)；摘要与版本记录；这里未单独核对正式ACL卷页，不能把arXiv评论视为已核对正式条目。 |
| ASC-D | verified，2026预印本 | [arXiv](https://arxiv.org/abs/2609.38931)；分布值观测与众数识别范围；未复现。 |
| Semantic-Preserving Early Exit | verified，2026预印本 | [arXiv](https://arxiv.org/abs/2605.17672)；答案就绪/推理收敛范围；页面注明under review，未复现。 |

**实现接口证据**另见 `experiments/radar20261013/provenance/baseline_implementation_audit.json`。Conformal 下阈值 utility 的 NameError 是固定快照接口检查的结果；没有证明论文方法失效。DEER PRo/MAD 字符串未找到也不证明没有等价实现，仍需人工方法核对。

**数据与模型**另核查官方 [Omni-MATH](https://github.com/KbsdJames/Omni-MATH)、[LiveCodeBench](https://github.com/LiveCodeBench/LiveCodeBench)、[DeepSeek模型页](https://huggingface.co/deepseek-ai/DeepSeek-R1-Distill-Llama-8B)。实际取得文件通过固定 revision / 内容哈希核验；这些证据只证明身份，不证明评分准确性、模型性能或新方法收益。

文献名称、会议状态、源码可执行范围与方法新颖性分别处理。尚无证据将本候选方法称为首创或达到高水平论文的性能门槛。
