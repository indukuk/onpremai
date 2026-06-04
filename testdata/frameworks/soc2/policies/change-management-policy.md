# Change Management Policy

| Field | Value |
|-------|-------|
| **Document ID** | POL-SEC-002 |
| **Version** | 2.4 |
| **Classification** | Internal |
| **Owner** | VP of Engineering |
| **Approved By** | CTO, CISO |
| **Effective Date** | 2025-01-10 |
| **Last Reviewed** | 2025-07-15 |
| **Next Review** | 2026-01-10 |
| **Applies To** | All personnel involved in system changes |

---

## 1. Purpose

This policy establishes a structured approach for managing changes to Acme Corporation's information systems, infrastructure, and applications. It ensures that changes are evaluated, authorized, tested, implemented, and reviewed in a controlled manner to minimize disruption and maintain security and compliance posture.

## 2. Scope

This policy applies to:

- All changes to production systems, infrastructure, applications, and databases
- Configuration changes to network devices, firewalls, and security tools
- Changes to cloud infrastructure (IaC, console, CLI)
- Software deployments, patches, and updates
- Database schema changes and data migrations
- Third-party integrations and API changes
- Changes to disaster recovery and backup configurations
- Documentation and process changes that affect system operation

Excluded from this policy:
- Content-only changes (marketing copy, blog posts) unless they affect system functionality
- Personal workstation configurations that do not affect shared resources
- Development environment changes (covered under separate development standards)

## 3. Policy Statements

### 3.1 Change Classification

All changes must be classified according to risk and urgency:

| Category | Description | Approval Required | Lead Time | Examples |
|----------|-------------|-------------------|-----------|----------|
| **Standard** | Pre-approved, low-risk, routine changes | Pre-authorized (no CAB) | 24 hours | Scheduled patching, certificate renewals |
| **Normal** | Planned changes with moderate risk | CAB approval | 5 business days | Feature deployments, infrastructure upgrades |
| **Major** | High-risk changes with broad impact | CAB + Executive approval | 10 business days | Architecture changes, platform migrations |
| **Emergency** | Urgent changes to restore service or patch critical vulnerabilities | Emergency CAB (2 members) | Immediate | Critical security patches, service-down fixes |

### 3.2 Change Advisory Board (CAB)

The Change Advisory Board consists of:
- VP of Engineering (Chair)
- CISO or Security representative
- Infrastructure Lead
- Application Development Lead
- QA/Release Manager
- On-call representative for affected systems

CAB meets weekly (Tuesdays, 10:00 AM) to review pending Normal and Major changes. Emergency changes are reviewed retroactively at the next CAB meeting.

### 3.3 Change Request Requirements

Every change request must include:

1. **Description**: Clear explanation of what is being changed and why
2. **Business Justification**: The business need driving the change
3. **Risk Assessment**: Impact analysis including affected systems, users, and data
4. **Implementation Plan**: Step-by-step procedure for executing the change
5. **Testing Evidence**: Results from non-production testing
6. **Rollback Plan**: Documented procedure to reverse the change if issues arise
7. **Communication Plan**: Notification requirements for stakeholders
8. **Schedule**: Proposed implementation window with estimated duration
9. **Resource Requirements**: Personnel, systems, and tools needed
10. **Post-Implementation Verification**: Steps to confirm successful completion

### 3.4 Testing Requirements

#### 3.4.1 Pre-Production Testing

- All changes must be tested in a non-production environment that mirrors production configuration.
- Testing must validate both the change itself and its rollback procedure.
- Automated test suites must pass with no regressions before production deployment.
- Performance testing is required for changes that may affect system capacity or response times.
- Security testing (SAST/DAST) is required for application code changes.

#### 3.4.2 Production Validation

- Post-deployment smoke tests must be executed within 15 minutes of change completion.
- Monitoring dashboards must be observed for 30 minutes after deployment.
- Deployment success criteria must be explicitly defined and verified before closing the change.

### 3.5 Change Windows

| System Tier | Standard Window | Restrictions |
|-------------|----------------|--------------|
| Tier 1 (Customer-facing) | Saturday 02:00-06:00 UTC | No changes during month-end (25th-1st) |
| Tier 2 (Internal critical) | Weekdays 22:00-06:00 UTC | No changes during quarter-end |
| Tier 3 (Internal standard) | Business hours with approval | None |
| Emergency | Any time | Post-hoc CAB review required |

Exceptions to change windows require CAB Chair approval with documented justification.

### 3.6 Segregation of Duties

- The person who develops a change shall not be the sole approver of that change.
- The person who approves a change shall not be the person who implements it in production (where technically feasible).
- Code deployments require peer review (minimum one reviewer) before merge to production branch.
- Database changes to production require DBA review and approval.

### 3.7 Emergency Changes

Emergency changes are permitted only when:
- A critical service is down or severely degraded, OR
- A critical security vulnerability with active exploitation is identified, OR
- Regulatory compliance requires immediate action

Emergency change process:
1. Obtain verbal approval from 2 CAB members (at minimum, the on-call manager and security representative).
2. Document the change request retroactively within 24 hours.
3. Present at next CAB meeting for retroactive review.
4. Conduct post-incident review if the emergency change caused additional issues.

### 3.8 Rollback Requirements

- Every change must have a documented rollback procedure before approval.
- Rollback must be executable within the defined maintenance window.
- Rollback triggers must be explicitly defined (e.g., error rate > 5%, response time > 2x baseline).
- Automated rollback capabilities are required for all CI/CD pipeline deployments.
- Data-destructive changes require verified backup before implementation.

### 3.9 Configuration Management

- All infrastructure configurations shall be maintained as code (Infrastructure as Code).
- Configuration changes must go through the same change management process as code changes.
- A Configuration Management Database (CMDB) shall maintain the current state of all production assets.
- Configuration drift detection shall run daily with alerts on unauthorized changes.

## 4. Procedures

### 4.1 Submitting a Change Request

1. Requestor creates a Change Request (CR) in the Change Management System (ServiceNow).
2. Requestor completes all required fields including risk assessment and rollback plan.
3. System automatically routes to appropriate approval workflow based on classification.
4. Requestor attaches testing evidence and implementation documentation.

### 4.2 Change Implementation

1. Implementer confirms all approvals are in place and change window is valid.
2. Implementer notifies the operations channel (Slack: #change-notifications) at start.
3. Implementer executes the change per the documented implementation plan.
4. Implementer performs post-implementation verification steps.
5. Implementer updates the CR with results and notifies channel of completion.

### 4.3 Failed Changes

1. If rollback triggers are met, execute rollback immediately.
2. Notify CAB Chair and affected stakeholders.
3. Document root cause of failure in the CR.
4. Submit revised CR with corrective actions for re-evaluation.

## 5. Roles and Responsibilities

| Role | Responsibilities |
|------|-----------------|
| **Change Requestor** | Submitting complete CRs, providing testing evidence, executing changes |
| **CAB Chair** | Scheduling reviews, approving/denying changes, managing escalations |
| **CAB Members** | Reviewing changes, assessing risk, providing technical input |
| **Change Implementer** | Executing approved changes per plan, performing validation |
| **Release Manager** | Coordinating deployment schedules, managing release calendar |
| **Security Representative** | Assessing security impact, reviewing security-relevant changes |
| **System Owners** | Approving changes to their systems, defining success criteria |

## 6. Metrics and Reporting

The following metrics are tracked and reported monthly:

- Change success rate (target: > 95%)
- Emergency change percentage (target: < 10%)
- Change-related incidents (target: < 5% of changes)
- Mean time from request to implementation
- Rollback frequency and success rate
- CAB review backlog

## 7. Exceptions

Exceptions to this policy require written approval from the CTO with:
- Documented business justification
- Compensating controls to mitigate additional risk
- Time-limited duration (maximum 6 months)
- Documented in the exception register

## 8. Enforcement

Non-compliance with this policy may result in:
- Change reverted without notice
- Access to deployment tools revoked pending retraining
- Disciplinary action for repeated violations
- Post-incident review and corrective action plans

## 9. Related Documents

- POL-SEC-001: Access Control Policy
- POL-SEC-003: Incident Response Policy
- STD-ENG-001: CI/CD Pipeline Standards
- STD-ENG-002: Code Review Standards
- PRO-OPS-001: Deployment Procedure
- PRO-OPS-002: Emergency Change Procedure

## 10. Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2022-06-01 | R. Thompson, VP Eng | Initial release |
| 2.0 | 2023-06-15 | R. Thompson, VP Eng | Added IaC requirements, cloud change controls |
| 2.1 | 2023-12-01 | R. Thompson, VP Eng | Updated change windows, added tier classification |
| 2.2 | 2024-06-01 | M. Chen, Release Mgr | Added automated rollback requirements |
| 2.3 | 2024-09-15 | M. Chen, Release Mgr | Added configuration drift detection |
| 2.4 | 2025-01-10 | R. Thompson, VP Eng | Annual review; updated CAB membership, added metrics |

---

*This document is the property of Acme Corporation and is intended for internal use only. Unauthorized distribution is prohibited.*
