# P02 余数根集遗漏见证

在 P02 已有原生思考的第 138 步，使用实际 tokenizer 重建 8,353 token 前缀。检测器从先前的 `there are two solutions mod 17²: 155 and 134.` 得到 `COMPLETE_SOLUTIONS` 声明，模数为 289，已列值为 `[155,134]`。

核验先复算最小素数证明，再要求声明模数与该素数的平方一致。反例必须是同一模数下未被列出且满足原同余式的标准代表元。这里代表元范围为 $0$ 至 $288$，与原题要求的正整数最小化分开。发现遗漏仅授权撤回根集完备性声明。

| 路径 | 实际结果 | 已支付检查数 |
|---|---|---:|
| 4,096 或 20,000 的搜索预算 | 找到被遗漏的 110，最小素数证书独立得到 17 | 635 |
| `WitnessGate` 内的搜索回放 | 重算相同范围、见证和账本 | 635 |
| `WitnessGate` 内的见证复核 | `UNIVERSAL_REFUTATION`，动作 `RETRACT_CLAIM_ONLY` | 525 |

搜索与门控的合计为 1,795 次检查。搜索结果的 `certified_value` 和门控的 `released_value` 都为空。只有 634 次预算时弃权。给定完整已知根集且搜索未找到遗漏时也弃权。20 项 CPU 测试通过，覆盖缺少先决证明、错误模数、重复或非法代表元、缺少见证素数、预算耗尽及零代表元。

| 文件 | 变更前 SHA-256 | 变更后 SHA-256 |
|---|---|---|
| `witness_contract.py` | `a4825e539797dc4df8cac5dcad469a2c108a9fb44c9df47180f261bb901ae200` | `9b3cbcbf75127667f0b96c5f6652170458eba58d72abc74eee1aef5c8dcb29e4` |
| `bounded_witness_search.py` | `1c573523ac147c9f0011b68726ecbc53bb4b709af22b2157b10b0a34a5015926` | `5384ab6d33899032e2152ce9f180f3d6c88f72f960e34fd2149b1e267b465cc7` |
| `test_bounded_witness_search.py` | `4820a50488768656037679ccca23a6e6e5d6f3666ee456b313fcbf006c9e216f` | `3c7978bd7b90ac890f532016ec38dcbb056d002608f336ec5cc23958ae0d6732` |
