# Anomaly detection

TokenScope detects daily application token spikes using a trailing baseline of up to 28 observations. A finding requires both a baseline ratio of at least 1.35 and a z-score of at least 2.5. Severity increases with statistical magnitude; it does not claim business impact.

Every finding includes the observed value, baseline, ratio, z-score, timestamp, and plain-language evidence. The detector runs locally and does not inspect prompt content.
