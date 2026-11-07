# External utility fault versus data-centre power-path availability

**Context note:** 7 November 2026. Independent post-incident technical commentary, **not** a source for facility identity or geographic location.

The [20 October 2026 Google Cloud europe-west2-b incident](https://status.cloud.google.com/incidents/Xs2XTHzAVC9YnafnPyzj) illustrates why the existence of a utility voltage measurement is not proof of a usable electrical connection. During a documented single-feed maintenance state, the remaining active feeder was interrupted by an external underground cable fault. A disconnected but line-side-energised second feeder was read as available by dual PLCs, preventing an automatic generator-start command.

The independently prepared [GlobalGrid2050 technical case study](https://github.com/Ventusltd/globalgrid2050/blob/main/docs/research/2026-11-google-cloud-power-resilience.md) examines the distinction between **voltage**, **breaker state** and **load-path continuity**, together with falsifiable questions for a competent electrical-controls review.

**Strict dataset boundary:** This `data-centres-gb` repository contains open-data facility records and provenance rules. It does not claim to identify Google's facility, its DNO, cable route, switchboard, operator, PLC supplier, or electrical topology. Do not assign the event to any mapped data-centre point, infer a feeder from physical proximity, or convert news reporting into a verified facility record. The engineering note is related research only.

**Primary source:** Google Cloud's [public incident RCA](https://status.cloud.google.com/incidents/Xs2XTHzAVC9YnafnPyzj). The note is authored after the event, not a prior warning or proprietary investigation.
