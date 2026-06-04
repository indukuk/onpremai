# Data Classification Policy

| Field | Value |
|-------|-------|
| **Document ID** | POL-SEC-004 |
| **Version** | 2.1 |
| **Classification** | Internal |
| **Owner** | Chief Information Security Officer (CISO) |
| **Approved By** | CTO, General Counsel, Chief Privacy Officer |
| **Effective Date** | 2025-02-01 |
| **Last Reviewed** | 2025-08-01 |
| **Next Review** | 2026-02-01 |
| **Applies To** | All employees, contractors, and third parties handling Acme Corporation data |

---

## 1. Purpose

This policy establishes the requirements for classifying, labeling, handling, and protecting Acme Corporation's information assets based on their sensitivity and criticality. Proper data classification enables the organization to apply appropriate security controls proportionate to the value and sensitivity of the data, ensuring compliance with regulatory requirements and contractual obligations.

## 2. Scope

This policy applies to:

- All data created, collected, processed, stored, transmitted, or disposed of by Acme Corporation
- All formats: electronic, paper, verbal, and visual
- All storage locations: on-premises systems, cloud services, endpoints, removable media, and third-party systems
- All personnel who access, process, or handle Acme Corporation data
- Customer data processed under service agreements

## 3. Classification Levels

### 3.1 Classification Tiers

| Level | Label | Description | Examples |
|-------|-------|-------------|----------|
| **Restricted** | RED | Highly sensitive data whose unauthorized disclosure would cause severe harm to the organization, its customers, or individuals | PII/PHI, payment card data, encryption keys, authentication secrets, unreleased financial results, M&A materials |
| **Confidential** | AMBER | Sensitive business data whose unauthorized disclosure would cause significant harm | Source code, architecture diagrams, internal audit reports, employee records, customer contracts, vulnerability reports |
| **Internal** | GREEN | Data intended for internal use that would cause limited harm if disclosed | Internal communications, project plans, meeting notes, organizational charts, policy documents, training materials |
| **Public** | WHITE | Data approved for public distribution with no restrictions | Marketing materials, published blog posts, public documentation, press releases, job postings |

### 3.2 Classification Decision Tree

1. Does disclosure violate a law, regulation, or contractual obligation? --> **Restricted**
2. Does it contain personal data (PII, PHI, financial) of customers or employees? --> **Restricted**
3. Does it contain credentials, keys, or security-sensitive configurations? --> **Restricted**
4. Would disclosure provide competitive advantage to competitors? --> **Confidential**
5. Is it explicitly approved for external distribution? --> **Public**
6. Default: --> **Internal**

## 4. Policy Statements

### 4.1 Data Ownership and Classification

- All data must have a designated Data Owner responsible for its classification.
- Data Owners are typically the department head or project lead who originated or is accountable for the data.
- Classification must be assigned at creation and reviewed when data is shared, repurposed, or undergoes significant change.
- When data from multiple classification levels is combined, the resulting dataset inherits the highest classification level of its components.
- Classification may be upgraded at any time but may only be downgraded with Data Owner and Security Team approval.

### 4.2 Handling Requirements by Classification

#### 4.2.1 Restricted Data (RED)

| Control | Requirement |
|---------|-------------|
| **Access** | Need-to-know basis only; individual access approval required |
| **Storage** | Encrypted at rest (AES-256 minimum); dedicated secure systems |
| **Transmission** | Encrypted in transit (TLS 1.2+); no email without encryption |
| **Endpoints** | Full disk encryption required; no removable media without DLP |
| **Printing** | Prohibited unless business-critical with secure print release |
| **Sharing** | Only via approved secure channels with Data Owner approval |
| **Cloud Storage** | Approved encrypted services only (AWS S3 with SSE-KMS, encrypted RDS) |
| **Retention** | Per regulatory requirement; secure deletion upon expiration |
| **Disposal** | Cryptographic erasure or physical destruction with certificate |
| **Logging** | All access logged and monitored; anomaly detection enabled |

#### 4.2.2 Confidential Data (AMBER)

| Control | Requirement |
|---------|-------------|
| **Access** | Role-based access; manager approval for new access |
| **Storage** | Encrypted at rest on corporate systems |
| **Transmission** | Encrypted in transit (TLS 1.2+) |
| **Endpoints** | Full disk encryption required |
| **Printing** | Minimize; secure disposal of printed copies |
| **Sharing** | Internal only; external sharing requires NDA and Data Owner approval |
| **Cloud Storage** | Approved corporate cloud services with encryption |
| **Retention** | Per retention schedule; 7 years default for business records |
| **Disposal** | Secure deletion (overwrite or cryptographic erasure) |
| **Logging** | Access logged; periodic review |

#### 4.2.3 Internal Data (GREEN)

| Control | Requirement |
|---------|-------------|
| **Access** | All authenticated employees and approved contractors |
| **Storage** | Corporate systems (no personal devices without MDM) |
| **Transmission** | Corporate email or approved collaboration tools |
| **Endpoints** | Standard corporate device security |
| **Printing** | Standard procedures |
| **Sharing** | Internal only; no external sharing without review |
| **Cloud Storage** | Approved corporate cloud services |
| **Retention** | Per retention schedule; 3 years default |
| **Disposal** | Standard deletion procedures |
| **Logging** | Standard system logging |

#### 4.2.4 Public Data (WHITE)

| Control | Requirement |
|---------|-------------|
| **Access** | No restrictions |
| **Storage** | Any system; no security requirements beyond availability |
| **Transmission** | No restrictions |
| **Sharing** | Unrestricted after approval for publication |
| **Retention** | Per business need |
| **Disposal** | Standard deletion |

### 4.3 Labeling Requirements

- Electronic documents: Classification label in header/footer and document properties/metadata.
- Emails containing Restricted or Confidential data: Subject line prefix [RESTRICTED] or [CONFIDENTIAL].
- Database records: Classification metadata field where technically feasible.
- Physical documents: Visible classification stamp on every page (header or footer).
- Storage media: External label indicating highest classification of contents.
- Cloud resources: Resource tags with `data-classification` key.

### 4.4 Data in Motion

- Restricted data must not be transmitted over unencrypted channels under any circumstances.
- Confidential data must use encrypted channels for all transmission.
- Email containing Restricted data must use S/MIME or equivalent end-to-end encryption, OR be transmitted as an encrypted attachment with key sent via separate channel.
- File transfers of Restricted data must use SFTP, SCP, or approved managed file transfer (MFT) solutions.
- API transmissions of classified data must use mutual TLS (mTLS) for Restricted data.

### 4.5 Data at Rest

- Encryption at rest is mandatory for all Restricted and Confidential data.
- Encryption keys must be managed through a formal key management process with separation of duties.
- Key rotation: annually for Confidential data, semi-annually for Restricted data.
- Backup media containing Restricted data must be encrypted with keys stored separately from backups.

### 4.6 Data Loss Prevention (DLP)

- DLP tools must be deployed on email gateways, web proxies, and endpoints.
- DLP rules must detect and prevent unauthorized transmission of Restricted data.
- DLP alerts for Restricted data: immediate notification to Security team.
- DLP alerts for Confidential data: logged and reviewed within 24 hours.
- False positive tuning conducted monthly to maintain effectiveness.

### 4.7 Third-Party Data Handling

- Third parties must be assessed for adequate security controls before receiving classified data.
- Restricted data sharing with third parties requires: Data Processing Agreement, Security assessment (SOC 2 or equivalent), Data Owner approval, Legal review.
- Confidential data sharing requires: NDA, documented business justification, Data Owner approval.
- Third-party access to classified data must be logged and auditable.
- Right to audit clause required in all agreements involving Restricted data.

### 4.8 Data Retention and Disposal

| Classification | Default Retention | Disposal Method | Verification |
|---------------|-------------------|-----------------|--------------|
| Restricted | Per regulatory requirement (minimum: duration of regulation + 1 year) | Cryptographic erasure or NIST 800-88 purge; physical destruction for media | Certificate of destruction required |
| Confidential | 7 years from last access | Secure deletion (cryptographic erasure or 3-pass overwrite) | Disposal log |
| Internal | 3 years from last access | Standard deletion | None required |
| Public | Per business need | Standard deletion | None required |

## 5. Procedures

### 5.1 Classifying New Data

1. Data creator identifies the Data Owner (typically their department head).
2. Data Owner applies the classification decision tree (Section 3.2).
3. Data Owner records classification in the data inventory/catalog.
4. Appropriate labels are applied per Section 4.3.
5. Handling controls are implemented per the classification level.

### 5.2 Reclassification

1. Requestor submits reclassification request to Data Owner with justification.
2. Data Owner reviews and approves (upgrades) or reviews with Security (downgrades).
3. For downgrades: Security team validates that regulatory/contractual constraints allow it.
4. Update labels, metadata, and access controls to reflect new classification.
5. Update data inventory/catalog.

### 5.3 Reporting Data Handling Violations

1. Report suspected violations to security@acmecorp.com or via Slack #report-security-issue.
2. Security team triages and investigates within 24 hours.
3. Confirmed violations are treated as security incidents per the Incident Response Policy.

## 6. Roles and Responsibilities

| Role | Responsibilities |
|------|-----------------|
| **Data Owners** | Classify data, approve access, authorize sharing, review classifications annually |
| **Data Custodians** | Implement technical controls, maintain systems per classification requirements |
| **All Users** | Handle data per classification, report violations, apply labels |
| **Security Team** | Define standards, monitor compliance, investigate violations, manage DLP |
| **Legal/Privacy** | Advise on regulatory requirements, review third-party agreements |
| **CISO** | Policy ownership, exception approval, compliance reporting |

## 7. Compliance Monitoring

- Quarterly DLP effectiveness reviews
- Semi-annual data classification audits (sampling of systems and repositories)
- Annual third-party data handling assessments
- Monthly reporting on classification violations and remediation status
- Annual review of data inventory completeness

## 8. Exceptions

Exceptions to this policy must be:
- Documented with specific data assets, requested handling deviation, and business justification
- Risk-assessed by the Security team
- Approved by the CISO and relevant Data Owner
- Time-limited (maximum 12 months)
- Compensating controls documented and implemented
- Reviewed at renewal

## 9. Enforcement

- Accidental mishandling (first occurrence): Mandatory retraining within 5 business days
- Accidental mishandling (repeated): Formal written warning and access review
- Intentional policy violation: Immediate access revocation, disciplinary action up to termination
- Violations resulting in data breach: Subject to legal action as appropriate

## 10. Related Documents

- POL-SEC-001: Access Control Policy
- POL-SEC-003: Incident Response Policy
- POL-SEC-005: Vendor Management Policy
- POL-PRI-001: Privacy Policy
- STD-SEC-005: Encryption Standards
- STD-SEC-006: Data Retention Schedule
- PRO-SEC-015: Data Disposal Procedure
- PRO-SEC-016: DLP Management Procedure

## 11. Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2022-08-01 | J. Martinez, CISO | Initial release |
| 1.1 | 2023-02-01 | J. Martinez, CISO | Added cloud-specific handling requirements |
| 2.0 | 2024-02-01 | S. Patel, Security Dir | Major update: added DLP requirements, decision tree, disposal verification |
| 2.1 | 2025-02-01 | S. Patel, Security Dir | Annual review; updated retention defaults, added mTLS for Restricted APIs |

---

*This document is the property of Acme Corporation and is intended for internal use only. Unauthorized distribution is prohibited.*
