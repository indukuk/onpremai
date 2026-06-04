# Vendor Management Policy

| Field | Value |
|-------|-------|
| **Document ID** | POL-SEC-005 |
| **Version** | 2.3 |
| **Classification** | Internal |
| **Owner** | Chief Information Security Officer (CISO) |
| **Approved By** | CFO, General Counsel, CISO |
| **Effective Date** | 2025-05-01 |
| **Last Reviewed** | 2025-11-01 |
| **Next Review** | 2026-05-01 |
| **Applies To** | All employees involved in vendor selection, management, or oversight |

---

## 1. Purpose

This policy establishes the framework for assessing, selecting, onboarding, monitoring, and offboarding third-party vendors (including subprocessors, SaaS providers, and service providers) that access, process, store, or transmit Acme Corporation or customer data. It ensures that vendor relationships do not introduce unacceptable risk to the organization's security posture, compliance obligations, or customer commitments.

## 2. Scope

This policy applies to:

- All third-party vendors, suppliers, and service providers engaged by Acme Corporation
- All subprocessors that handle customer data on behalf of Acme Corporation
- Cloud service providers (IaaS, PaaS, SaaS)
- Managed service providers and outsourcing partners
- Consultants and contractors who access corporate systems
- Open-source software with commercial support arrangements
- Any entity with access to Acme Corporation networks, systems, or data

Exclusions:
- One-time purchases of software licenses without data access
- Vendors providing purely physical goods with no data or system access
- Individual contractors managed under the Access Control Policy

## 3. Policy Statements

### 3.1 Vendor Risk Classification

All vendors must be classified based on the risk they pose to Acme Corporation:

| Tier | Classification | Criteria | Review Frequency |
|------|---------------|----------|-----------------|
| **Tier 1 - Critical** | High Risk | Processes/stores Restricted data, has production system access, OR single-point-of-failure for business operations | Quarterly |
| **Tier 2 - Important** | Medium Risk | Processes/stores Confidential data, has non-production system access, OR provides significant business capability | Semi-annually |
| **Tier 3 - Standard** | Low Risk | Accesses Internal data only, no system access, limited business impact if unavailable | Annually |

### 3.2 Due Diligence Requirements

#### 3.2.1 Pre-Engagement Assessment

Before engaging any vendor, the following assessments must be completed:

| Requirement | Tier 1 | Tier 2 | Tier 3 |
|-------------|--------|--------|--------|
| Security questionnaire (SIG or equivalent) | Required | Required | Simplified |
| SOC 2 Type II report review | Required | Required | Preferred |
| ISO 27001 certification review | Required | Preferred | Optional |
| Penetration test results (< 12 months) | Required | Preferred | Not required |
| Business continuity/DR documentation | Required | Required | Not required |
| Financial stability assessment | Required | Preferred | Not required |
| Reference checks | Required | Required | Optional |
| On-site assessment | Risk-based | Not required | Not required |
| Data flow mapping | Required | Required | Simplified |

#### 3.2.2 Security Assessment Criteria

Vendors processing Restricted or Confidential data must demonstrate:

1. **Encryption**: Data encrypted at rest (AES-256) and in transit (TLS 1.2+)
2. **Access Control**: Role-based access with MFA for administrative access
3. **Logging and Monitoring**: Security event logging with defined retention (minimum 12 months)
4. **Incident Response**: Documented IR plan with defined notification timelines
5. **Data Segregation**: Logical or physical separation of customer data
6. **Personnel Security**: Background checks for personnel with data access
7. **Vulnerability Management**: Regular scanning and patching with defined SLAs
8. **Business Continuity**: Tested BC/DR plans with defined RTO/RPO
9. **Subprocessor Management**: Controls over their own third parties
10. **Data Residency**: Data stored in approved jurisdictions

### 3.3 Contractual Requirements

All vendor agreements must include (requirements vary by tier):

#### 3.3.1 Mandatory for All Tiers

- Confidentiality/NDA provisions
- Data ownership clause (Acme retains ownership of its data)
- Termination provisions with data return/deletion obligations
- Compliance with applicable laws and regulations
- Notification of material changes to services or security posture

#### 3.3.2 Required for Tier 1 and Tier 2

- Data Processing Agreement (DPA) compliant with GDPR/applicable regulations
- Security obligations with specific control requirements
- Breach notification within 24 hours of discovery (Tier 1) or 48 hours (Tier 2)
- Right to audit (directly or via independent third party)
- Subprocessor restrictions and notification requirements
- Service Level Agreements (SLAs) with defined remedies
- Business continuity and disaster recovery commitments
- Cyber insurance requirements ($5M minimum for Tier 1, $2M for Tier 2)
- Indemnification for security breaches caused by vendor negligence
- Data deletion/return certification upon termination

#### 3.3.3 Additional for Tier 1

- Dedicated security contact and escalation path
- Annual penetration testing with results shared
- Participation in joint incident response exercises (annual)
- Defined RTO/RPO commitments with testing evidence
- Exit strategy and transition assistance provisions
- Key personnel notification requirements

### 3.4 Ongoing Monitoring

#### 3.4.1 Continuous Monitoring Activities

| Activity | Frequency | Applicable Tiers |
|----------|-----------|-----------------|
| SOC 2 report review | Annually | Tier 1, Tier 2 |
| Security questionnaire refresh | Per tier frequency | All |
| Service availability monitoring | Continuous | Tier 1 |
| Breach notification monitoring (news/dark web) | Continuous | Tier 1, Tier 2 |
| Financial health check | Annually | Tier 1 |
| SLA performance review | Monthly | Tier 1, Tier 2 |
| Subprocessor change review | Per notification | Tier 1, Tier 2 |
| Regulatory compliance verification | Semi-annually | Tier 1 |
| Contract renewal risk review | At renewal | All |

#### 3.4.2 Vendor Scorecarding

Each Tier 1 and Tier 2 vendor is scored quarterly on:

- Security posture (SOC 2 findings, vulnerability status, incident history)
- Service performance (SLA adherence, uptime, response times)
- Compliance (regulatory alignment, audit findings, remediation timeliness)
- Relationship management (communication, escalation responsiveness)
- Risk trajectory (improving, stable, declining)

Vendors scoring below acceptable thresholds trigger escalation and remediation planning.

### 3.5 Vendor Onboarding

1. Business sponsor submits Vendor Intake Form via procurement system.
2. Security team assigns risk tier based on data access and criticality.
3. Due diligence assessment completed per tier requirements.
4. Security team issues risk assessment report with recommendations.
5. Vendor Risk Committee reviews and approves/rejects (Tier 1) or CISO approves (Tier 2/3).
6. Legal finalizes agreements with required security provisions.
7. Access provisioned per Access Control Policy with documented justification.
8. Vendor added to vendor inventory with monitoring schedule established.

### 3.6 Vendor Offboarding

When a vendor relationship is terminated:

1. Revoke all system access within 24 hours of termination effective date.
2. Revoke all credentials, API keys, certificates, and VPN configurations.
3. Request written certification of data deletion/return within 30 days.
4. Verify data deletion through audit log review or attestation.
5. Update vendor inventory and CMDB.
6. Retain vendor records per retention schedule (minimum 7 years).
7. Conduct lessons-learned review for Tier 1 vendors.

### 3.7 Subprocessor Management

- Vendors must disclose all subprocessors that access Acme Corporation data.
- Tier 1 vendors must provide 30 days advance notice of subprocessor changes.
- Acme Corporation reserves the right to object to new subprocessors within 15 days.
- Vendors are responsible for ensuring subprocessors meet equivalent security standards.
- Subprocessor data residency must comply with Acme Corporation requirements.

### 3.8 Fourth-Party Risk

- Tier 1 vendors must disclose material dependencies on fourth parties.
- Concentration risk is assessed where multiple vendors share critical dependencies.
- Annual review of supply chain risk for Tier 1 vendors.

## 4. Procedures

### 4.1 Requesting a New Vendor

1. Business owner completes Vendor Intake Form in the procurement system.
2. Provide: business justification, data types involved, system access needed, estimated contract value.
3. Procurement routes to Security for risk classification.
4. Security initiates assessment per tier requirements.
5. Average processing time: 10 business days (Tier 3), 20 business days (Tier 2), 30 business days (Tier 1).

### 4.2 Reporting Vendor Security Concerns

1. Report to vendor-security@acmecorp.com or Slack #vendor-risk.
2. Security team triages within 24 hours.
3. For active breaches or incidents: escalate per Incident Response Policy.
4. For assessment findings: documented in vendor risk register with remediation tracking.

### 4.3 Vendor Risk Exception

1. Business owner documents the exception request with risk acceptance justification.
2. Compensating controls identified and documented.
3. CISO reviews and approves/denies (Tier 2/3) or Vendor Risk Committee decides (Tier 1).
4. Exceptions time-limited to maximum 6 months with mandatory re-review.
5. Exceptions tracked in the risk exception register.

## 5. Governance

### 5.1 Vendor Risk Committee

- **Members**: CISO (Chair), CFO, General Counsel, CTO, VP Operations
- **Meets**: Monthly
- **Responsibilities**: Approve Tier 1 vendor engagements, review vendor risk dashboard, approve exceptions, set risk appetite

### 5.2 Vendor Inventory

- Centralized vendor inventory maintained in the GRC platform.
- Updated within 5 business days of any vendor change (new, modified, terminated).
- Contains: vendor name, tier, data classification, contract dates, security assessment status, owner, monitoring schedule.

## 6. Roles and Responsibilities

| Role | Responsibilities |
|------|-----------------|
| **Business Owner** | Identify vendor need, submit intake, manage relationship, escalate issues |
| **Security Team** | Risk classify, conduct assessments, monitor vendor security posture |
| **Procurement** | Contract negotiation, financial terms, vendor intake routing |
| **Legal** | Contract review, DPA negotiation, regulatory compliance provisions |
| **CISO** | Policy ownership, Tier 2/3 approval, committee leadership |
| **Vendor Risk Committee** | Tier 1 approval, strategic vendor risk decisions |
| **IT Operations** | Access provisioning/deprovisioning, connectivity management |

## 7. Metrics

| Metric | Target | Reporting |
|--------|--------|-----------|
| Vendors with current risk assessment | 100% | Monthly |
| Tier 1 vendor review completion | 100% quarterly | Quarterly |
| Average vendor onboarding time | < 30 days (Tier 1) | Monthly |
| Vendor security incidents | 0 critical | Monthly |
| Contract compliance (required clauses) | 100% | Semi-annually |
| Vendor scorecard completion | 100% for Tier 1/2 | Quarterly |

## 8. Exceptions

Exceptions to this policy require:
- Written justification with risk assessment
- Compensating controls documented
- CISO approval (Tier 2/3) or Vendor Risk Committee approval (Tier 1)
- Maximum 6-month duration
- Tracking in risk exception register

## 9. Enforcement

- Engaging a vendor without completing required assessments: Contract suspended pending assessment
- Sharing Restricted data with an unapproved vendor: Treated as a security incident
- Failure to conduct required monitoring: Escalation to VP level; mandatory remediation
- Vendor non-compliance with contractual security obligations: Escalation per contract terms; potential termination

## 10. Related Documents

- POL-SEC-001: Access Control Policy
- POL-SEC-004: Data Classification Policy
- POL-PRI-001: Privacy Policy
- POL-PROC-001: Procurement Policy
- STD-SEC-010: Vendor Security Assessment Standard
- PRO-SEC-020: Vendor Onboarding Procedure
- PRO-SEC-021: Vendor Offboarding Procedure
- TPL-SEC-001: Security Questionnaire Template
- TPL-LEG-001: Data Processing Agreement Template

## 11. Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2022-05-01 | J. Martinez, CISO | Initial release |
| 1.1 | 2022-11-01 | J. Martinez, CISO | Added subprocessor requirements |
| 2.0 | 2023-05-01 | S. Patel, Security Dir | Major revision: added tiering, scorecarding, fourth-party risk |
| 2.1 | 2024-05-01 | S. Patel, Security Dir | Updated assessment criteria, added cyber insurance requirements |
| 2.2 | 2024-11-01 | S. Patel, Security Dir | Added concentration risk, updated notification timelines |
| 2.3 | 2025-05-01 | S. Patel, Security Dir | Annual review; updated committee membership, added supply chain section |

---

*This document is the property of Acme Corporation and is intended for internal use only. Unauthorized distribution is prohibited.*
