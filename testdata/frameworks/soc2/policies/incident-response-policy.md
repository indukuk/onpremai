# Incident Response Policy

| Field | Value |
|-------|-------|
| **Document ID** | POL-SEC-003 |
| **Version** | 4.1 |
| **Classification** | Internal |
| **Owner** | Chief Information Security Officer (CISO) |
| **Approved By** | CEO, General Counsel |
| **Effective Date** | 2025-04-01 |
| **Last Reviewed** | 2025-10-01 |
| **Next Review** | 2026-04-01 |
| **Applies To** | All employees, contractors, and incident response personnel |

---

## 1. Purpose

This policy establishes the framework for detecting, responding to, containing, eradicating, and recovering from information security incidents at Acme Corporation. It defines roles, responsibilities, communication protocols, and procedures to minimize the impact of security incidents on business operations, data integrity, and customer trust.

## 2. Scope

This policy applies to:

- All security events and incidents affecting Acme Corporation systems, data, or personnel
- All environments including production, staging, development, and corporate networks
- All third-party systems that process, store, or transmit Acme Corporation data
- Physical security incidents that may impact information security
- All employees, contractors, and third-party personnel who may detect or respond to incidents

## 3. Definitions

| Term | Definition |
|------|-----------|
| **Security Event** | An observable occurrence relevant to information security (e.g., failed login) |
| **Security Incident** | A security event that has been confirmed to violate policy or threaten confidentiality, integrity, or availability |
| **Data Breach** | An incident resulting in unauthorized access to or disclosure of personal or sensitive data |
| **Indicator of Compromise (IOC)** | Forensic artifacts that identify potentially malicious activity |
| **Mean Time to Detect (MTTD)** | Average time from incident occurrence to detection |
| **Mean Time to Respond (MTTR)** | Average time from detection to initial containment |

## 4. Policy Statements

### 4.1 Incident Severity Classification

| Severity | Description | Response Time | Examples |
|----------|-------------|---------------|----------|
| **Critical (P1)** | Active data breach, service-wide outage, ransomware | 15 minutes | Active exfiltration, production encryption, mass credential compromise |
| **High (P2)** | Confirmed compromise with limited scope, significant service degradation | 1 hour | Single system compromise, targeted phishing with credential harvest, DDoS |
| **Medium (P3)** | Suspicious activity requiring investigation, minor service impact | 4 hours | Anomalous network traffic, policy violation, failed intrusion attempt |
| **Low (P4)** | Security event requiring awareness but no immediate action | 24 hours | Phishing attempts (blocked), vulnerability disclosure, policy questions |

### 4.2 Incident Response Team (IRT)

#### 4.2.1 Core Team

| Role | Primary | Backup | Responsibilities |
|------|---------|--------|-----------------|
| **Incident Commander (IC)** | CISO | Security Director | Overall coordination, decision authority, executive communication |
| **Technical Lead** | Sr. Security Engineer | Security Engineer | Technical investigation, containment, eradication |
| **Communications Lead** | VP of Communications | Legal Counsel | External/internal communications, regulatory notifications |
| **Operations Lead** | Infrastructure Manager | Sr. SRE | System recovery, service restoration |
| **Scribe** | Security Analyst | Jr. Security Engineer | Documentation, timeline maintenance, evidence logging |

#### 4.2.2 Extended Team (Engaged as Needed)

- Legal Counsel (mandatory for data breaches and P1 incidents)
- Human Resources (insider threat incidents)
- Customer Support (customer-facing incidents)
- External forensics firm (Mandiant/CrowdStrike, under retainer)
- Law enforcement liaison (CISO discretion)

### 4.3 Incident Response Phases

#### Phase 1: Preparation

- Maintain and test incident response tools, playbooks, and communication channels.
- Conduct tabletop exercises quarterly and full simulation exercises annually.
- Maintain pre-authorized forensic tools on isolated systems.
- Ensure on-call rotation covers 24/7/365 with 15-minute response SLA for P1.
- Maintain current contact lists for all IRT members, executives, legal counsel, and external partners.
- Pre-establish relationships with law enforcement (FBI IC3, local field office).

#### Phase 2: Detection and Analysis

- Security Operations Center (SOC) monitors alerts 24/7 via SIEM (Splunk).
- Automated correlation rules trigger alerts based on defined detection logic.
- Initial triage determines if event constitutes an incident and assigns severity.
- Evidence preservation begins immediately upon incident declaration.
- Chain of custody documentation initiated for all forensic evidence.

#### Phase 3: Containment

**Short-term containment** (stop the bleeding):
- Isolate affected systems from the network
- Block malicious IP addresses and domains
- Disable compromised accounts
- Redirect traffic away from affected services

**Long-term containment** (enable investigation while maintaining operations):
- Deploy clean systems to replace compromised ones
- Implement additional monitoring on related systems
- Apply emergency patches or configuration changes
- Establish secure communication channels for the IRT

#### Phase 4: Eradication

- Identify and remove root cause (malware, unauthorized access, misconfiguration)
- Remove persistence mechanisms (scheduled tasks, backdoors, rogue accounts)
- Patch exploited vulnerabilities
- Validate eradication through forensic analysis and scanning
- Rebuild compromised systems from known-good images

#### Phase 5: Recovery

- Restore systems from verified clean backups or rebuilds
- Implement enhanced monitoring on recovered systems
- Validate system functionality through testing
- Gradually restore service with careful observation
- Confirm no recurrence over 72-hour monitoring period

#### Phase 6: Post-Incident Activities

- Conduct formal post-incident review within 5 business days of closure
- Document lessons learned and distribute to relevant teams
- Update detection rules, playbooks, and procedures based on findings
- Track remediation actions to completion
- Update risk register with new threat intelligence
- Provide executive summary to leadership within 48 hours of closure

### 4.4 Communication Protocols

#### 4.4.1 Internal Communication

| Severity | Notify | Channel | Frequency |
|----------|--------|---------|-----------|
| P1 | CEO, CTO, CISO, Legal, Board (if breach) | War room (Zoom) + Slack #incident-critical | Every 30 minutes |
| P2 | CTO, CISO, VP Engineering | Slack #incident-response | Every 2 hours |
| P3 | CISO, Security Team | Slack #security-ops | Daily |
| P4 | Security Team | Jira ticket | As needed |

#### 4.4.2 External Communication

- **Customers**: Notification within 72 hours of confirmed data breach (or as required by contract/regulation, whichever is sooner).
- **Regulators**: Per applicable regulations (GDPR: 72 hours, CCPA: expeditious, HIPAA: 60 days).
- **Law Enforcement**: At CISO discretion for criminal activity; mandatory for incidents involving nation-state actors or critical infrastructure.
- **Media**: All media inquiries routed exclusively through Communications Lead. No unauthorized statements.

### 4.5 Evidence Handling

- All evidence must maintain chain of custody documentation.
- Forensic images must be created before any analysis of original media.
- Evidence must be stored on encrypted, access-controlled media.
- Hash values (SHA-256) must be calculated and recorded for all evidence.
- Evidence retention: minimum 7 years or as required by legal/regulatory obligations.
- Only trained personnel may handle forensic evidence.

### 4.6 Breach Notification

When a data breach is confirmed:

1. Legal Counsel immediately engaged to assess notification obligations.
2. Determine affected data subjects and types of data compromised.
3. Prepare notification content (approved by Legal and Communications).
4. Execute notification per regulatory timelines and contractual obligations.
5. Offer credit monitoring or identity protection services where appropriate.
6. Report to relevant supervisory authorities per jurisdictional requirements.

### 4.7 Training and Exercises

| Activity | Frequency | Participants | Owner |
|----------|-----------|--------------|-------|
| Tabletop exercise | Quarterly | IRT core team | CISO |
| Full simulation | Annually | IRT + executives | Security Director |
| Phishing simulation | Monthly | All employees | Security Awareness Team |
| Tool proficiency training | Semi-annually | SOC analysts | SOC Manager |
| New member onboarding | Upon joining | New IRT members | Technical Lead |

## 5. Procedures

### 5.1 Reporting a Suspected Incident

Any person who suspects a security incident must:

1. **Do not attempt to investigate or remediate independently.**
2. Report immediately via one of:
   - Email: security-incident@acmecorp.com (monitored 24/7)
   - Phone: Security Operations Center x4400 (or +1-555-SEC-OPS1 externally)
   - Slack: #report-security-issue
3. Provide: what was observed, when, affected systems, and any actions already taken.
4. Preserve evidence: do not restart systems, delete files, or alter configurations.

### 5.2 Declaring an Incident

The SOC Manager or Security Engineer on-call may declare an incident when:
- A security event is confirmed to violate policy, OR
- Unauthorized access to systems or data is confirmed, OR
- Service availability is impacted by a security cause, OR
- A credible threat with imminent impact is identified

### 5.3 Incident Closure

An incident may be closed when:
- Root cause has been identified and eradicated
- Affected systems have been recovered and validated
- Enhanced monitoring shows no recurrence for 72 hours (P1/P2) or 48 hours (P3/P4)
- All required notifications have been completed
- Post-incident review has been scheduled

## 6. Roles and Responsibilities

| Role | Responsibilities |
|------|-----------------|
| **All Employees** | Report suspected incidents promptly, preserve evidence, cooperate with investigations |
| **SOC Analysts** | Monitor alerts, perform initial triage, escalate per severity |
| **Incident Commander** | Lead response, make containment decisions, communicate to executives |
| **Technical Lead** | Direct technical investigation and remediation activities |
| **Communications Lead** | Manage internal/external communications, coordinate with legal on notifications |
| **CISO** | Policy ownership, executive accountability, law enforcement decisions |
| **Legal Counsel** | Advise on regulatory obligations, privilege, and notification requirements |

## 7. Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Mean Time to Detect (MTTD) | < 24 hours | Monthly average |
| Mean Time to Respond (MTTR) | < 4 hours (P1/P2) | Monthly average |
| Incident closure within SLA | > 90% | Monthly |
| Post-incident review completion | 100% | Per incident |
| Tabletop exercise participation | > 95% of IRT | Quarterly |

## 8. Exceptions

Given the critical nature of incident response, exceptions to this policy are limited to:
- Alternative communication channels when primary channels are compromised
- Deviation from standard procedures when authorized by the Incident Commander with documented justification
- All exceptions must be documented in the incident record

## 9. Enforcement

- Failure to report a known or suspected incident: disciplinary action up to termination
- Unauthorized disclosure of incident details: disciplinary action and potential legal consequences
- Interference with an investigation: immediate suspension pending review
- Negligent evidence handling: removal from IRT and retraining requirement

## 10. Related Documents

- POL-SEC-001: Access Control Policy
- POL-SEC-004: Data Classification Policy
- POL-BCP-001: Business Continuity Policy
- PLB-SEC-001: Ransomware Response Playbook
- PLB-SEC-002: Data Breach Response Playbook
- PLB-SEC-003: DDoS Response Playbook
- PRO-SEC-010: Forensic Evidence Handling Procedure

## 11. Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2021-04-01 | J. Martinez, CISO | Initial release |
| 2.0 | 2022-04-01 | J. Martinez, CISO | Added breach notification procedures |
| 3.0 | 2023-04-01 | S. Patel, Security Dir | Complete rewrite; added severity matrix, communication protocols |
| 3.1 | 2023-10-01 | S. Patel, Security Dir | Updated external forensics retainer, added law enforcement section |
| 4.0 | 2024-04-01 | S. Patel, Security Dir | Added metrics, updated regulatory timelines, enhanced evidence handling |
| 4.1 | 2025-04-01 | S. Patel, Security Dir | Annual review; updated contact information, added ZTNA considerations |

---

*This document is the property of Acme Corporation and is intended for internal use only. Unauthorized distribution is prohibited.*
