# Domain Glossary

| Term | Definition |
|---|---|
| Instrument | A stable economic/security identity independent of any current ticker. |
| Instrument ID | Internal UUID that does not change when a ticker or venue symbol changes. |
| Identifier | External code such as ISIN, FIGI, CUSIP, SEDOL, or provider-specific ID. |
| Symbol mapping | Effective-dated association among provider, symbol, exchange, and instrument. |
| MIC | ISO 10383 four-character Market Identifier Code. |
| Exchange | Trading venue identified by MIC, country, currency context, and IANA time zone. |
| Session label | Exchange-local date used to identify a regular trading session. |
| Trading session | Open, optional break, and close instants for a session label. |
| Market phase | Closed, pre-open, open, break, or post-close state at a given instant. |
| Event time | Time at which a real-world event occurred. |
| Publication time | Time at which the information was first made public. |
| Received time | Time at which this platform obtained the information. |
| Processed time | Time at which this platform completed processing the observation. |
| Point-in-time correctness | Guarantee that a decision uses only information available by its cutoff. |
| Universe snapshot | Immutable set of eligible instrument IDs at an explicit as-of date. |
| Prediction horizon | Future interval expressed in trading sessions, calendar days, or minutes. |
| Port | Interface owned by the core that describes required external behavior. |
| Adapter | Implementation connecting a port to an external package or service. |
| Composition root | Single bootstrap location where concrete dependencies are wired together. |
