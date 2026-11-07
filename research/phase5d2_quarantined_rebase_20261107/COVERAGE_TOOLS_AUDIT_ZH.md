# D2覆盖工具与配对执行静态审查

## 工具和CPU证据

`fetch_coverage.py`仅通过已有SSH凭据helper取回原子完成结果及进度，不存储凭据。结果、模型manifest和已下载资产的字节漂移会被拒绝。每次取回生成SHA收据，并读取实际进程表。

`audit_coverage.py`首先核对冻结配对协议，再绑定提取器、checker与审计器源码。它保留24题、48种子轨迹和全部排除项。只有全部48轨迹完成后才生成FROZEN选择。没有真实tokenizer时解码标为NOT_RUN，配对前还需真实解码复核。

7项CPU测试全部通过，覆盖排序优先级、全部字典序字段、每题一事件、输入不变、只绑定已观察前缀、在线段落与首次checkpoint、目的路径逃逸拒绝。

## 首次部分取回

UTC 2026-11-07 04:12:12已取回17/48轨迹，涉及9/24题。launcher 1190044和workers 1190045、1190046当时均在进程表中。17条自然EOS，0条context cap，生成63789 tokens。

4039项完整性检查通过。真实tokenizer资产已与model37的worker资产manifest逐项核验。原生thinking模板、prompt IDs、全文解码、Observer段落、events和checkpoints重放通过。

1423个完整步骤、748个事件步骤，抽出118条关系。54条字面成立，6条字面不成立，58条UNKNOWN。其中42条缺乏显式符号scope，16条表面式不受支持。60条可判字面关系来自4题、6种子轨迹和54个live段落。6条无效字面关系只来自1题、2种子轨迹和6个live段落。

角色认证与READY修复机会均为0。上述6条只具有词法角色候选标记，尚未接受完整已观察前缀的双人角色审查。显式scope符号关系覆盖为0。当前PAIR_SELECTION为PARTIAL_NO_FINAL_SELECTION，选择为空。

## 配对worker的静态边界

此次源码快审覆盖同调度重建、逐token源前缀再生与RNG相等检查、分支独立复制、原snapshot不变、UNKNOWN全程到EOS一致性、桥的角色/think标记拒绝和实际forward/copy计费。没有观察到身份恢复或后缀嫁接方面的阻断问题。

`proposal_check.parse_counterexample`要求非空变量集。closed-literal目标必然得到UNKNOWN，因此三条相同cue的检查臂在这些目标上没有依赖验证器的状态干预。它们可检验提示与UNKNOWN身份传递，scope收益需要实际scope目标，修复收益需要另行完成角色认证和READY计划。

如果桥返回INSUFFICIENT_CONTEXT，worker可继续生成，但没有真正收到审计cue。该技术结果需要单列暴露分母。

本审查没有读取Gold、计算答案正确率或改变GPU任务。源码SHA、原始收据和CPU命令见COVERAGE_TOOLS_AUDIT.json。后续部分和最终审计应继续使用已冻结源码。
