---
name: aerolane-freight
description: Aerolane Freight, shipping vendor; recurring unapproved expedite fees; check before approving freight invoices
aliases: [Aerolane, Aerolane Freight Ltd, AFL]
sources: [erp, memory-writer]
updated: 2026-10-24
---
- [system-of-record | 2026-01-01] Payment terms Net 30; approved bank account on file (last 4: 7731)
- [computed: cases #41, #57 | 2026-09-14] 2 unapproved expedite fees this year, both rejected
- [controller: M. Chen, 2026-09-14 | 2026-09-14] Hold any expedite fee without signed approval
