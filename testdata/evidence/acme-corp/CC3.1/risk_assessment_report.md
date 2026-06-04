# Risk Assessment Report - Acme Corp

**Assessment Period:** January 2025 - December 2025
**Prepared by:** Lisa Nguyen, Chief Information Security Officer
**Approved by:** Mark Wilson, Chief Technology Officer
**Date:** November 15, 2025
**Classification:** Internal - Confidential

---

## Executive Summary

This annual risk assessment evaluates the information security and operational risks facing Acme Corp's technology infrastructure and services. The assessment covers 20 identified risks across five categories: Technical (6), Security (5), Operational (4), Compliance (3), and Financial (2).

**Key Metrics:**
- Total risks identified: 20
- Critical risks (score 15+): 3
- High risks (score 10-14): 8
- Medium risks (score 6-9): 9
- Mitigated: 12 (60%)
- In progress: 7 (35%)
- Accepted: 1 (5%)

The overall risk posture has improved compared to the previous assessment period, with the number of critical risks decreasing from 5 to 3. The security team has successfully implemented multi-factor authentication across all systems and completed the encryption-at-rest program ahead of schedule.

## Key Findings

### Critical Risks Requiring Immediate Attention

1. **Credential Compromise via Phishing (RISK-002, Score: 16)** - Despite deploying phishing-resistant MFA, social engineering attacks remain our highest-likelihood threat. Two successful phishing attempts were detected and contained in Q2 2025. The mitigation has reduced impact but the threat remains elevated due to industry-wide targeting of technology companies.

2. **Supply Chain Attack Risk (RISK-006, Score: 15)** - The December 2024 industry-wide npm package compromise highlighted our exposure. Software composition analysis is now integrated into CI/CD, but full dependency pinning and SBOM generation is still in progress. Target completion: Q1 2026.

3. **Insider Threat from Over-Privileged Accounts (RISK-009, Score: 15)** - Audit findings revealed 15% of service accounts have broader permissions than required. Just-in-time access provisioning is being rolled out incrementally, with full coverage expected by March 2026.

### Positive Developments

- Disaster recovery testing cadence improved from annual to quarterly
- Zero data breaches or unauthorized data exposures in the assessment period
- Mean time to recovery (MTTR) improved by 40% year-over-year
- All P1 incidents resolved within SLA (target: 15 minutes for detection, 60 minutes for resolution)
- Successful completion of SOC 2 Type II audit with zero critical findings

### Areas for Improvement

- Change management process gaps identified in 5 deployments lacking proper change IDs
- Two administrator accounts found without MFA enabled (remediation in progress)
- Monitoring coverage gaps in inter-service communication need to be addressed
- Key person dependency on infrastructure team needs cross-training completion

## Risk Treatment Plan

| Priority | Risk ID | Action | Owner | Target Date |
|----------|---------|--------|-------|-------------|
| 1 | RISK-009 | Complete JIT access rollout | Lisa Nguyen | March 2026 |
| 2 | RISK-006 | Full SBOM generation and dependency pinning | Michelle Jackson | Q1 2026 |
| 3 | RISK-003 | Complete cross-training for critical systems | Mark Wilson | February 2026 |
| 4 | RISK-012 | Deploy distributed tracing for all services | Anna Kowalski | January 2026 |
| 5 | RISK-014 | Complete legacy system migration phase 2 | Peter Garcia | April 2026 |

## Methodology

This assessment follows the ISO 31000:2018 risk management framework and aligns with NIST SP 800-30 Rev. 1 guidelines. Risks are scored using a 5x5 likelihood-impact matrix with the following scale:

- **Likelihood:** 1 (Rare) to 5 (Almost Certain)
- **Impact:** 1 (Negligible) to 5 (Catastrophic)
- **Risk Score:** Likelihood x Impact (range 1-25)

Risk appetite thresholds:
- Score 1-5: Accept (monitor only)
- Score 6-9: Medium priority (address within 6 months)
- Score 10-14: High priority (address within 3 months)
- Score 15-25: Critical (immediate action required)

## Next Review

The next comprehensive risk assessment is scheduled for November 2026. Quarterly reviews of critical and high-priority risks will be conducted in February, May, and August 2026.

---

*This document is subject to annual review and update. Contact the CISO office for questions or to report new risks.*
