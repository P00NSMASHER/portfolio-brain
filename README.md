# Portfolio Brain current acceptance

Current protected main: `8a47ce9f04f77c2c4ab4c972106ccd31bb1c97e9` ([PR648](https://github.com/P00NSMASHER/portfolio-brain/pull/648)).

Scheduler fallback is integrated; automatic delivery and soak are NOT TESTED. The real one-time manual clock dispatcher succeeded and delivered a core workflow request. A manual probe cannot establish automatic delivery or pass a soak. Current acceptance: [finish-soak.json](acceptance/finish-soak.json).

Previous native-only attempt remains [BLOCKED with preserved exact-source evidence](acceptance/history/e2d825d-native-clock-blocked.json). No soak started on that source. GitHub native cron delivery remains BLOCKED pending actual event=schedule evidence. Old issue640 provider run is not renamed terminal/deleted.

Replacement contract preserves mandatory preflight, doctor, provenance, state publication, deterministic replay and zero backlog. Require three genuine automatically delivered cycles on one unchanged main over at least two hours, gaps no more than90minutes and complete postvalidation. External clock runs must link actual scheduled Reliability execution, immutable scheduled pulse, successful clock job and matching successful core artifact; manual probes excluded. [Operations/recovery](https://github.com/P00NSMASHER/portfolio-brain/blob/main/docs/rebuild/OPERATIONS.md).

Local tests:1414 PASS49.070sec; targeted45 PASS0.224sec; exact candidate preflight PASS. Accepted candidate2070aac0e1a457061bb1b8fbb229b430962351b6 passed both App-bound protected gates. Superseded candidate inventory failure remains recorded at [run37711065270](https://github.com/P00NSMASHER/portfolio-brain/actions/runs/37711065270).

General unrestricted self-repair, uninterrupted availability and real business/revenue improvement are not demonstrated. Live protected knowledge-upgrade merge NOT TESTED.
