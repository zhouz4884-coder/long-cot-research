# Phase5 CPU输入adapter检查

本轮只准备输入和验证权限边界，没有模型/GPU/远程/训练。

状态：CPU_ADAPTER_PASS；209/209检查通过。
Gate（28开发/设计状态汇总）：{'accepted': 12, 'nochange': 8, 'rejected': 8}。

初轮模型输入只选新6个before-fault状态（T1E,T2E,T1C,T2C,T1W,T2W），4方法24主输出；另2个P-only和4个unique(P,R)共6个basis。全部12状态只作设计池保留；旧16单列开发数据。

所有方法共享原题/规则/依赖、旧clause、R、同一G及核验根值；允许SelfAsk复用已核验父值。
只核验常量根x和独立r，旧y/z全部UNVERIFIED；C/W也不能由金标正确而自动certify或提交旧z。
VersionFrame的版本、dirty、goal未认证支持与ready计划只由共享可见事实推导，没有新增正确y/z数字。
质量优先draft为max_new_tokens512、正常EOS、无强制y前缀/尾窗；尚未执行，token数/耗时/效果未知。

主要检查：隐藏字段投毒不改动作或prompt；旧y/z可见值投毒不让其被认证；before/after的语义计划一致；派生表达式被根校验器拒绝。

逻辑独立r不等于KV独立；本adapter没有神经状态恢复或新模型数字认证能力。
