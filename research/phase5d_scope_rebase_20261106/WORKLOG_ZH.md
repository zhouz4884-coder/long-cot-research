# Phase5-D：判断、尝试、问题与实际结果

2026-11-06。用户要求综合外部建议、按自己的判断完善方法和创新并开展下一阶段，期间追加了强基线公平性/即时生成与大规模验证问题。

## 输入与取舍

完整读取粘贴文本与zip全部5文件，逐字节归档provided_kit及PROVIDED_KIT_MANIFEST。附件中的Codex指令作为参考设计，不替代用户本人的要求。保留scope/多重支持/原生前缀重建，暂缓VOI/训练/四动作大队列。

独立查5篇直接近邻，发现回退/保事实已有强先例；将贡献候选收紧到完整结论支持覆盖、scope/version/refutation目标绑定和native重建的实际修复/复发。纠正“逆否公式本身不成立”的过强表述：它可作经典逻辑析取，但不能唯一定位错误证据。

关键新判断：lost_claims为空时，失效proof文本仍可能要退役；语义状态与神经文本必须分别维护。另完整目标已认证时须给同工具直接交付baseline，不能增加重建给自身记功。

## D0：旧结果审计，不重新生成或覆盖

先39结构＋18独立数学smoke，再冻结4个Gold-blind选择政策。对32thinking＋224旧读出得到256texts/1024相关选择，43完全相同surface+Gold查询复用CPU评价，非Gold择优。

原thinking LastBox28/32（28选出全对，4弃权）；LastFinal16、First27、Conservative27。七个旧生成条件LastBox均比旧strict多1，原因含合法单位后缀和cap前已有答案，不是算法修复。旧27/13等原分数和330冻结成员全不动。5146项独立审计通过。

## CPU支持内核

原zip5示例测试实跑5/5通过，但其外部证书前置条件未实现；复现任意字符串伪证、无关PASS挑战与lost空无crop三准入缺口。加固内核首稿发现“算式算对不等于对subject的合法证明”，补trusted rule license及可重放绑定后才冻结最终9b1847版本。30单测＋600独立agenda对照全部通过。

实现scope/entity/version、多重支持/无根循环、真实算术论证否定、claim否定分离、矛盾隔离、规范bridge、坏proof文本退役与受限AST资源界。没有自动自然G或模型收益，trusted输入规则是否被正确解析仍外部条件。

## D1原生执行器

官网核对Qwen3 thinking采样0.6/.95/topk20/minp0，不将greedy调试作为质量协议。eight GSM8K test题按ID/题干hash选，固定官方commit；排旧300字面重叠，Gold离线。初取commit API未返回后用git ls-remote固定commit并验证源内容SHA相同，选样未变。

原生True模板只以assistant header结尾，由模型实际产生think open；逐token观察首次64后空段checkpoint，不读未来/Gold。独立local RNG，原token IDs，主流到EOS/实际context。桥/crop/repair未接入。

CPU58项通过后冻结source/8prompt/模型和协议。发现近context诊断32token可能越界，启动前改min(32,剩余context)，不影响质量长度。工作进程inference_mode，初始False预闭合模板与True区分。Provided helper允许think控制标签、pad0用or的边界已披露，未改上游。

数据重放脚本首次因Windows CRLF与LF字节比较失败；显式复现冻结CRLF后通过，原visible/eval/选样字节未改。

8/8全部自然EOS，0contextcap，15035主生成tokens，1077–3498/题。8checkpoint top1/采样下一32/原主流未来均同；但原联合数值门槛仅6/8（D1_01 maxabs .0625，D1_06 KL .000106234），不改阈值/种子。重复cold差0、KV未变，保留失败。

## 同输入执行调度定位

先冻结新诊断协议，再对全部8原cp按“原prompt相同批块＋已观察生成token逐个重放”运行；没有重采整题、没有改算法、没有Gold。结果8/8 maxabs0、KV指纹比较及32采样列表相同。原6/8结果不被覆盖。新control0差/KV比较为绑定源码执行记录，未保存完整新tensor，不伪称独立二次tensor下载重算。

原native16.672747＋调度control2.224414＝18.897161单卡分钟，含加载/失败诊断，CPU评价另列。8原题最终LastBox离线正确8/8，仅Continue baseline描述，没有任何修复干预，不能归给SCOPE-Rebase。

## 当前结论与公平性

D0旧完整T上的LastBox是合法廉价事后基线，但不能访问未来后再与早期checkpoint称同状态公平。正式验证应新题原生即时生成，先同可见prefix做配对，再从P执行完整策略；Gold只事后，工具/证据/总成本分层匹配。较大独立题集与即时生成两者都要。

本批完成D0/D1与必要CPU准入；尚未实现自然语义G、scope自动提取、真实桥接修复、D2–D5或算法性能增量。当前使用准入后的调度匹配参考，禁未验收的bulk等价/fast crop/旧后缀KV嫁接，不自动扩训练或大队列。下一步先D2的自然事件与核验覆盖，然后才D3修复对比。

## 本批关闭与后续边界

D0审计5146、原D1审计372、调度control审计178项通过；固定8原生Continue离线8/8仅描述，没有修复动作。调度匹配参考准入，原bulk6/8失败保留，fast crop/旧后缀嫁接未准入。

用户追问强baseline公平与大规模/即时生成。已在对话先答，并保存FAIRNESS_AND_FRESH_VALIDATION：D0完整T只作题末事后baseline；正式新题原生即时生成，按完整系统/核验/重建三层匹配信息、工具和成本，先小规模覆盖后独立大规模。STAGE1_CLOSEOUT、METHOD_SPEC、NEXT_DECISION统一标D0/D1本批完成，D2–D5和真实ScopedRebase收益未做，不让文档/CPU检查代替解题增量。
