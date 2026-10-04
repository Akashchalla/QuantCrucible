"""Live / paper-trading layer for Module B (the VIX-gated opening-auction gap fade).

Research code lives in src/gqh and never imports from here. This package turns the
pre-registered rule into an operational daily cycle:

    08:45 ET  pre_open       VIX_{t-1} gate, universe, previous closes
    09:27 ET  open_auction   pre-open indicative prices -> gaps -> baskets -> MOO orders
    09:35 ET  post_open      official opens -> fills, realised gaps, implementation shortfall
    15:45 ET  close_auction  MOC orders for every open position
    16:20 ET  eod            official closes -> fills, P&L, reconciliation, flatness check

Every step is idempotent per session date and records what it did in the store.
"""
