# 强基线完整结果审查

入口 `scripts/analyze_controlled_baseline.py`，只在实际完整模型输出之后执行。它检查完整markers/冻结题目全集、模型/协议/GPU/seed、实际共享prefix和重新评分；拒绝部分或重复/错版本记录。不是作者报告数字比较器，也不生成模型回答。

ASAG/REFRAIN的参考来自同题新执行的matched FULL及预声明pair order。DTSR当前输出没有内嵌FULL，另要求真实M1式FULL输出与其policy plan；确认kind=full、budget等于正式上限、policy SHA/协议/model/GPU/seed匹配。DTSR的schedule/thermal差异保留说明，不能当交错同请求因果计时。

REFRAIN会按前序问题更新阈值，只有固定顺序完整流的描述量；不套普通IID Bootstrap/McNemar或主策略风险证书。DTSR/ASAG的这些统计也标为条件IID/exchangeable-pair诊断，不替代本研究分层有限池风险界。

完整结果后示例命令（必须使用对应实际输出tag）：

```powershell
python scripts/analyze_controlled_baseline.py --baseline asag --split selection --out-tag asag_selection --output results/asag_selection_analysis.json
python scripts/analyze_controlled_baseline.py --baseline refrain --split selection --out-tag refrain_selection --output results/refrain_selection_analysis.json
python scripts/analyze_controlled_baseline.py --baseline dtsr --split selection --out-tag dtsr_selection --full-tag m1_selection --full-policy-file provenance/m1_selection_online.json --output results/dtsr_selection_analysis.json
```

ASAG分析核对paid-candidate identity和token计费，列动作/实际动作/停止原因；拆解H的query数量、log(key数量)、每query未归一化Shannon贡献。不把“normalizer单独足够越过阈值”写成实际有害动作的因果原因。总耗时与FULL正确子集分别给出，保留错误/触顶/解析失败。

当前只有程序控制证据：4项CPU控制通过，真实native统计复算一致，缺ASAG完整输出时在Gold读取/结果写入前拒绝。远端历史输出存在性检查一度timeout，恢复连接后实际确认文件不存在。尚无ASAG/REFRAIN/DTSR的完整selection、校准或盲测成绩。冻结生成脚本/参数/证据不变。
