# Proactive compressed-state reserve, November 5, 2026

Current source: protected Portfolio Brain main after PRs #870 and #871. In
four consecutive completed Brain core cycles, compressed state increased
45,248–46,512 bytes per half-hour. At latest actual state
`d9e92fcb8315d02736776ed33d27b2f12b4503b8`, compressed usage was
15,172,109 of the independently verified 20,602,941 bytes (73.64%).
The existing 75% trigger would delay compaction until little buffer remained.

This change pulls the **soft compressed trigger** forward to 72% and, when
the compressed reserve is below 30%, keeps the latest 64 rather than 128
*redundant PASS derived-report copies*. It preserves byte-for-byte all
non-PASS reports, the latest report for every source, all events, attempts,
ledgers, schema, and existing historical Git state commits.

The raw hard bound remains 180,000,000 bytes, compressed hard bound stays
20,602,941 bytes. The compaction path continues testing SQLite integrity,
foreign keys, full canonical table hashes and retained report hashes before
atomic replacement. The receipt now reports observed raw and compressed
bytes reclaimed; negative or zero gains remain visible, never relabeled as
savings.

**Release acceptance:** genuine two-App exact-head checks; protected merge;
a completed original post-merge core; original state branch exact publication;
and a measured capacity receipt demonstrating whether compaction improved
headroom. Source-level code and tests alone are insufficient.
