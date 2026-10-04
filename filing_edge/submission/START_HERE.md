# Ready-to-review package

1. **Open the shared demo:** https://srinivaspenumarthi.github.io/hack/
   It is clearly labeled as a saved-results replay. Audio, explanations, charts and the downside calculator work without keys.
2. **Read the research notes:** `Massive_Research_Note.pdf` (2 pages) and `Systematic_Trading_Note.pdf` (5 pages).
3. **Reproduce the strategy:** open `Filing_Edge_Judge.ipynb` in Jupyter/Colab and run all cells with a Massive key. Judges may change dates and use mode `sealed`. Historical NBBO access is required.
4. **Run the live product:** follow the root README. Configure Massive, Gemini, Tiger Data and ElevenLabs locally, then use `python scripts/setup_demo.py` and `python app.py`.
5. **Submit:** use `DEVPOST.md` as the project description, add all four teammates, attach the notes/notebook and include the GitHub and demo URLs. Follow the event's submission portal instructions.

Do not describe the public replay as live API generation. The complete server performs live calls; the replay distributes saved, verified outputs. Do not claim a profitable strategy: the held-out funded simulation lost $795.80 on a $1 million account and the allocation decision remains research only.

Credentials and raw licensed market-data caches are deliberately absent from this package. The private local workspace has the full collected research data. No actual brokerage orders are supported.
