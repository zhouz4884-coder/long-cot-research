# 2026-10-14 显存与长前缀准入准备

native两个进程与监督器现场确认存活，当前数据未完整，未重启或开始争用GPU的验证。上一轮DTSR入口/协议工作是实质进展；本轮资源分析与验收入口修改亦未替代模型结果。

实际读取模型config与已保存native资源字段：Qwen3-4B/Thinking2507为36层、8KV头、head_dim128，FP16单KV16k为2.25GiB；DeepSeek8B为32层/8头/128，单KV16k为2GiB。已保存16576-token主模型请求peak allocated9.8846GiB，运行中SMI约21GiB占用不能当作相同指标。公式/部分遥测不是新模型或克隆的GPU准入。

新增candidate validator的saved_pilot模式：依据已完成同模型pilot长度选前缀，不依据Gold或正确性，要求达到真实请求长度且不含已结束thinking/EOS。完整prefill恢复cache后验证候选/reader一致、父KV和实际peak allocation；生成模式仍记录实际终止长度。跨模型不允许借用主模型保存的token IDs。

源码已部署并编译，当前native所绑定源文件未改；没有执行新的GPU检查。native完整后再做128/8192/16384长度验收，随后科学审查与formal冻结。所需判断、问题、尝试/限制及下一检查记录到D11。
