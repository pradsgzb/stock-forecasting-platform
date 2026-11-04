# Assumptions Register

| ID | Assumption | Consequence | Review trigger |
|---|---|---|---|
| A-001 | Initial assets are exchange-listed equities and ETFs. | Domain enums include extensibility but tests focus on equities. | Addition of derivatives or crypto. |
| A-002 | Initial forecasts are end-of-day and batch-oriented. | Regular sessions and close-based cutoffs receive priority. | Intraday data section begins. |
| A-003 | Market data is acquired under an appropriate license. | The repository contains no bundled commercial data. | Provider contracting. |
| A-004 | UTC is the canonical storage instant. | Local exchange time is derived with IANA zones. | None; foundational invariant. |
| A-005 | Symbols can change and are provider-specific. | Symbols are mappings, not primary keys. | None; foundational invariant. |
| A-006 | `exchange_calendars` is suitable as a default adapter, not an unquestioned source of truth. | Calendar output remains behind a port and is validated. | Production venue onboarding. |
| A-007 | Python 3.14 is the preferred deployment runtime; 3.13 remains a tested compatibility floor. | CI tests both minor versions where available. | Dependency compatibility changes. |
| A-008 | Human approval is required before future model promotion to champion. | Continuous training will be controlled rather than autonomous. | Formal model governance decision. |
