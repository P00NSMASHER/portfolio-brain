# October 28 reliability repair evidence

Prior protected source: `7aef80798022fbd3492ef3e00f6249f6d1384dea`.

The original observer run [40750833758](https://github.com/P00NSMASHER/portfolio-brain/actions/runs/40750833758) emitted PASS: 87,655 completed seconds, 52 automatic cores, maximum gap 2,126 seconds. This is a bounded historical receipt, not unrestricted autonomy or proof that subsequent runs cannot fail.

Later core [40754892091](https://github.com/P00NSMASHER/portfolio-brain/actions/runs/40754892091) failed monitoring at 2026-10-28T19:31:51Z with CHECK_COVERAGE_CHANGED for P00NSMASHER/github-value-hunt-ledger, then MONITOR_INCOMPLETE. It started outside the fixed 88,200-second window. The observer nevertheless evaluated its failed verdict before checking the cutoff, incorrectly invalidating the historical window. Both the original PASS and the later operational failure remain evidence; neither is reset, deleted, or relabeled.

Observer [40700438781](https://github.com/P00NSMASHER/portfolio-brain/actions/runs/40700438781) separately failed downloading original evidence with GITHUB_API_UNAVAILABLE. Subsequent replays succeeded. This was observer read availability, not a successful observation at the time of failure.

This repair consolidates proposals #778, #779, #780 and #781:

- Enforce the checked-in project authority before minting a downstream repair token. Denied projects produce a sanitized receipt and do not mint credentials or execute writes.
- Bound observer provider retries to three attempts, all counted against the existing request budget; exhaustion still fails.
- Bind Truth projection identities to registered canonical project IDs, rejecting every malformed or duplicate registry row.
- Check the fixed observation-window cutoff before evaluating later run verdicts, preserving rejection of all failed/retried in-window runs.
- Retry a changing monitoring census once from page one using the same client and original request budget, discarding all partial pages. Malformed, ambiguous and cross-source evidence remains a hard failure. A repeated change or insufficient remaining capacity remains a hard failure.

Independent review is code review, not PB-role impersonation or live reliability acceptance. Any new merged source must collect its own deployment and automatic reliability evidence. Historical source receipts do not transfer to it.
