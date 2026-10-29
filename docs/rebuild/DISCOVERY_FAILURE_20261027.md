# Preserved failed reliability window

Source: 7eb3d8fe064989a80eb514c0ec2d45ec908771ce.
Original core: https://github.com/P00NSMASHER/portfolio-brain/actions/runs/40501681055
Failed observation: https://github.com/P00NSMASHER/portfolio-brain/actions/runs/40516086817

At 2026-10-27 12:11:47 UTC, research failed with DISCOVERY_INCOMPLETE after signed scheduling provenance, restored-state verification, preflight and monitoring succeeded. Publication was skipped. The search completeness field was not explicitly false; the retained log does not establish the precise returned field value. This window remains failed. Later successful runs do not erase it.

The repair retries only an explicit boolean incomplete_results=true once after one second. Missing/malformed completeness remains a failure. Partial items are discarded. Every request, including transport retries, remains inside the shared 24-request cap and any smaller caller reserve. Persistent incompleteness fails with DISCOVERY_INCOMPLETE. No acceptance criteria or historical evidence are reset.

A protected release of the repair creates a new source identity and starts fresh automatic 24-hour evidence collection through the existing observer. Completion still requires actual elapsed time and matching repair receipts.
