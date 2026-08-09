# Synthetic golden fixtures

Golden inputs are generated from frozen specifications and seeds at test time. No binary
fixture is committed. A change in deterministic SHA-256 output, complete-byte accounting,
independent tile decoding, corruption rejection, or resume behavior is a test failure.
