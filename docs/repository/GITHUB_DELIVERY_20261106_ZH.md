# GitHub交付记录

日期：2026-11-06。状态：**代码/数据首次推送与远端核验通过**。

## 已核验的代码/数据提交

- 私有仓库：[zhouz4884-coder/long-cot-research](https://github.com/zhouz4884-coder/long-cot-research)。
- 默认分支：main；本地由master对齐main，已追踪origin/main；整理前HEAD另保留在本地codex/pre-github-20261106。
- 本页核验对象（报告写入前的代码/数据提交）：[`9d2f8cd23170`](https://github.com/zhouz4884-coder/long-cot-research/commit/9d2f8cd231708a5f9d00b2530014b9b0fef1a2ea)。
- 核验对象Git tree：`560f398501b3b8f4d1990bbbbddba6236fc7a5a3`，完整文件数1522。
- 远端所有blob ID与本地完整tree一致；API完整遍历未截断。
- 远端全部51个祖先提交ID与本地一致，包括原50个提交，未重写历史。
- 六份实际返回内容逐字节相等：README、Phase索引、Phase5、真实P0.5源码、预启动冻结JSON及E02 logits NPZ。其余全树通过Git blob ID核对，未声称所有字节均独立二次下载。

## 暂存区与研究证据

[暂存核验](PRE_PUSH_VALIDATION.json)检查源/输入/实验材料：全部暂存blob与工作树字节相等，224项既有冻结manifest成员逐项匹配；新增/修改文本凭据规则无候选，新Phase/根导航无缺失链接，无超限文件或禁止路径。首次11个旧文件仅行尾差异，通过保留本地原字节并刷新索引解决，未改原实验内容或manifest。

当前/历史及独立history扫描范围与binary限制见[审查报告](../../research/repository_phase_plan_20261106/PUBLISH_SCOPE_AUDIT_ZH.md)。本次没有新增认证材料或开源许可证。

## 授权与发布范围

GitHub连接器能确认账号，但对新私有仓库返回404；建仓/推送和上述只读API核验使用同一账号已有Git Credential Manager授权。凭据未写文件、URL或命令参数，也未输出。认证API核对private=true；匿名API返回403，仅记录，未将可能的限流403当作私有性的证明。

上传范围见[发布说明](PUBLISH_SCOPE_ZH.md)。只推main及其祖先，没有mirror或推送本机Codex tree ref。模型、环境、缓存、重复ZIP和其他队列原始inventory留本地。仓库中的已有原文/用户输入维持来源属性，不新授上游许可。

## 阶段与研究意见

[Phase1–5入口](../phases/INDEX_ZH.md)把历史负结果、文献、P0、P0.5和待跑候选分开。定位可以随证据调整为预算内有效计算复用/答案交付；每轮比较前固定强baseline、信息/工具权限、评分和完整成本。90%/50%节省等仍是未测预测。

本轮没有GPU实验或新算法benchmark成绩。[建议审查](../../research/repository_phase_plan_20261106/ADVISOR_REVIEW_20261106_ZH.md)给出shared-G路由、紧凑OneLine、同权限Self-Ask和版本前沿对照。

本页和只读复核脚本随后以交付记录提交写入仓库；它验证的是上面的代码/数据提交，不声称自己的提交SHA能预先自证。最终HEAD再由同一只读脚本核对，本地回执单独保存。
