"""Self-improving investigation loop layered on top of the existing pipeline.

Nothing in this package modifies Phase 1's pipeline or ranking engine. It reads
the *already produced* ranked candidates for a completed search and runs
investigation rounds over them, remembering what worked and adapting.
"""
