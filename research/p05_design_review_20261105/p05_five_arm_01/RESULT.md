# P0.5 P05_PRIMARY_RETAINED_DIAGNOSTICS_PARTIAL

Primary complete cases: 16; diagnostic complete cases: 8.

Primary = frozen parser on free.text; probes are separately priced pre-generation forced queries.

| Arm | Correct / complete five-arm pairs |
|---|---:|
| FullDirect | 8/16 |
| FullOneLine | 11/16 |
| WholeEarlyDirect | 0/16 |
| WholeEarlyOneLine | 12/16 |
| WholeLateOneLine | 8/16 |

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
