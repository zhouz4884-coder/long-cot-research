# P0.5 P05_CPU_INTERFACE_ONLY_COMPLETE

Primary complete cases: 3; diagnostic complete cases: 3.

Primary = frozen parser on free.text; probes are separately priced pre-generation forced queries.

| Arm | Correct / complete five-arm pairs |
|---|---:|
| FullDirect | 0/3 |
| FullOneLine | 0/3 |
| WholeEarlyDirect | 0/3 |
| WholeEarlyOneLine | 0/3 |
| WholeLateOneLine | 0/3 |

## Limits

- Sixteen teacher-forced short injected states, not natural long-CoT or model self-correction.
- Ordinary OneLine instruction; free generation is not forcibly started at y=.
- Auxiliary Y/Z are pre-generation forced-prefix queries, not observed intermediate beliefs.
- Four roles are deduplicated to unique continuations; W revision-consistent is not necessarily true.
- Complete sequence likelihood requires candidate forward work; first-token margins are separate.
- Full-shaped key masks establish no memory savings; checkpoint retention is experimental overhead.
- No statistical-power, induction-head, orthogonality, safety, causal-mechanism or novelty claim.
- New user-turn/readout protocol differs from old P0; cross-run accuracy changes are not method gains.
- Standalone UUID binding is not a scheduler exclusion lock or continuous process monitoring.

Random tiny CPU fixture only; no pretrained-model evidence.
