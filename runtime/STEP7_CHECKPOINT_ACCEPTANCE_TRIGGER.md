# Step 7 live checkpoint continuation trigger

This behavior-neutral marker exists only to exercise the existing protected
`runtime-hourly-sync` push path after the first durable canonical checkpoint
archive was merged.

It grants no authority and is not read by runtime code. Its protected merge is
the exact-main starting point for the required live proof:

checkpoint/archive -> producer event -> reducer -> canonical snapshot ->
production reader restore.
