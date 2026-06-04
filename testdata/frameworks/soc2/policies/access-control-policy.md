# Access Control Policy

| Field | Value |
|-------|-------|
| **Document ID** | POL-SEC-001 |
| **Version** | 3.2 |
| **Classification** | Internal |
| **Owner** | Chief Information Security Officer (CISO) |
| **Approved By** | VP of Engineering, General Counsel |
| **Effective Date** | 2025-03-15 |
| **Last Reviewed** | 2025-09-01 |
| **Next Review** | 2026-03-01 |
| **Applies To** | All employees, contractors, and third-party users |

---

## 1. Purpose

This policy establishes the requirements for controlling logical and physical access to Acme Corporation's information systems, applications, and data. It ensures that access is granted based on the principle of least privilege and business need, protecting the confidentiality, integrity, and availability of organizational assets.

## 2. Scope

This policy applies to:

- All employees, contractors, temporary workers, and third-party users who access Acme Corporation information systems
- All information systems, applications, databases, network devices, and cloud services owned or operated by Acme Corporation
- All environments including production, staging, development, and disaster recovery
- Both on-premises and cloud-based infrastructure (AWS, Azure, GCP)

## 3. Policy Statements

### 3.1 Access Control Principles

1. **Least Privilege**: Users shall be granted only the minimum level of access necessary to perform their job functions. Access rights shall not exceed what is required for the user's current role.

2. **Need-to-Know**: Access to sensitive information shall be restricted to individuals who require such access to fulfill their job responsibilities.

3. **Separation of Duties**: Critical functions shall be divided among different individuals to reduce the risk of fraud, error, or misuse. No single individual shall have the ability to complete a critical transaction from initiation to completion without independent oversight.

4. **Default Deny**: Access to all resources shall be denied by default. Access is only granted through explicit authorization.

### 3.2 User Account Management

#### 3.2.1 Account Provisioning

- All access requests must be submitted through the Identity Access Management (IAM) portal with documented business justification.
- Access requests require approval from the user's direct manager and the system owner.
- Privileged access requests additionally require approval from the Information Security team.
- Access shall be provisioned within 2 business days of complete approval.
- All provisioned access must be traceable to an approved access request.

#### 3.2.2 Account Types

| Account Type | Description | Approval Required | Review Frequency |
|---|---|---|---|
| Standard User | Day-to-day business access | Manager | Semi-annual |
| Privileged User | Administrative or elevated access | Manager + Security | Quarterly |
| Service Account | Application-to-application | System Owner + Security | Quarterly |
| Emergency/Break-Glass | Emergency access only | CISO (post-use) | Per-use |
| Temporary | Time-limited access for projects | Manager + System Owner | Monthly |

#### 3.2.3 Account Deprovisioning

- Access must be revoked within 4 hours of involuntary termination notification from HR.
- Access must be revoked within 24 hours of voluntary termination effective date.
- Role changes require access review within 5 business days; previous role access must be removed unless explicitly justified and reapproved.
- Dormant accounts (no login for 90 days) shall be automatically disabled.
- Disabled accounts shall be deleted after 180 days unless a documented retention requirement exists.

### 3.3 Authentication Requirements

#### 3.3.1 Password Standards

- Minimum length: 14 characters
- Complexity: Must include at least three of four character types (uppercase, lowercase, numeric, special)
- History: Cannot reuse the last 12 passwords
- Maximum age: 90 days for standard accounts, 60 days for privileged accounts
- Lockout: Account locked after 5 consecutive failed attempts for 30 minutes

#### 3.3.2 Multi-Factor Authentication (MFA)

MFA is mandatory for:

- All remote access (VPN, remote desktop)
- All privileged/administrative accounts
- Access to production environments
- Access to systems containing PII, PHI, or financial data
- Cloud management console access (AWS, Azure, GCP)
- Email access from non-corporate devices
- All single sign-on (SSO) portal access

Approved MFA methods (in order of preference):
1. Hardware security keys (FIDO2/WebAuthn)
2. Authenticator applications (TOTP)
3. Push notifications via approved mobile app
4. SMS-based OTP (permitted only as fallback, not for privileged accounts)

#### 3.3.3 Session Management

- Interactive sessions shall timeout after 15 minutes of inactivity for sensitive systems.
- Standard system sessions shall timeout after 30 minutes of inactivity.
- Maximum session duration: 12 hours, after which re-authentication is required.
- Concurrent sessions shall be limited to 3 per user for standard accounts.

### 3.4 Access Reviews

#### 3.4.1 Periodic Reviews

| Review Type | Frequency | Scope | Responsible Party |
|---|---|---|---|
| Privileged Access | Quarterly | All admin/elevated accounts | Security Team + System Owners |
| Standard Access | Semi-annually | All standard user accounts | Managers + System Owners |
| Service Accounts | Quarterly | All non-human accounts | System Owners |
| Third-Party Access | Quarterly | All vendor/partner accounts | Vendor Management + Security |
| Emergency Access | Per-use | Each break-glass usage | CISO |

#### 3.4.2 Review Process

1. Security team generates access reports from identity management systems.
2. Reports are distributed to responsible reviewers with a 10-business-day completion deadline.
3. Reviewers must confirm or revoke each access entitlement with documented justification.
4. Revocations must be executed within 5 business days of the review decision.
5. Completion metrics are reported to the Security Steering Committee monthly.
6. Non-compliance with review deadlines is escalated to the reviewer's VP after 5 days overdue.

### 3.5 Remote Access

- All remote access must traverse the corporate VPN or approved zero-trust network access (ZTNA) solution.
- Split tunneling is prohibited on devices accessing corporate resources.
- Remote access is restricted to corporate-managed devices unless explicitly approved via the BYOD program.
- Remote access sessions are subject to enhanced logging and monitoring.

### 3.6 Network Access Control

- Network segmentation shall separate production, development, staging, and corporate environments.
- Firewall rules shall follow default-deny with explicit allow rules documented and reviewed quarterly.
- Wireless networks shall use WPA3-Enterprise with certificate-based authentication.
- Guest wireless networks shall be isolated from corporate networks with no access to internal resources.

### 3.7 Cloud Access Controls

- Cloud IAM policies shall enforce least privilege using role-based access.
- Root/owner accounts for cloud tenants shall be secured with hardware MFA and used only for break-glass scenarios.
- Cloud access keys shall be rotated every 90 days.
- Programmatic access shall use short-lived credentials (STS tokens, service account keys with expiration) where supported.
- Cloud resource access shall be logged and monitored via CloudTrail or equivalent.

## 4. Procedures

### 4.1 Requesting Access

1. Employee submits access request via IAM Portal (ServiceNow) specifying system, access level, and business justification.
2. Automated workflow routes to appropriate approvers based on access type.
3. Upon approval, IAM team provisions access and notifies the requestor.
4. Requestor verifies access and acknowledges acceptable use.

### 4.2 Reporting Access Issues

- Suspected unauthorized access: Report immediately to security@acmecorp.com or call the Security Operations Center (x4400).
- Access problems or errors: Submit a ticket via the IT Service Desk.
- Lost or stolen credentials/tokens: Report immediately to SOC; account will be locked pending investigation.

### 4.3 Emergency Access (Break-Glass)

1. Contact the on-call Security Engineer to authorize emergency access.
2. Emergency access is logged automatically with full session recording.
3. Access is time-limited (maximum 4 hours) and automatically revoked.
4. Post-incident review required within 24 hours documenting actions taken and justification.
5. CISO reviews all emergency access usage weekly.

## 5. Roles and Responsibilities

| Role | Responsibilities |
|------|-----------------|
| **CISO** | Policy ownership, exception approval, emergency access oversight |
| **Security Team** | Policy enforcement, access reviews, monitoring, incident response |
| **System Owners** | Defining access roles, approving access requests, participating in reviews |
| **Managers** | Approving team member access, certifying ongoing access needs |
| **HR** | Timely notification of terminations and role changes |
| **IT Operations** | Provisioning/deprovisioning execution, system configuration |
| **All Users** | Protecting credentials, reporting issues, completing training |

## 6. Exceptions

Exceptions to this policy must be:
- Submitted in writing with business justification and risk assessment
- Approved by the CISO (or VP of Engineering for CISO-related exceptions)
- Time-limited (maximum 12 months) with a defined remediation plan
- Documented in the policy exception register
- Reviewed at each renewal for continued necessity

## 7. Enforcement

Violations of this policy may result in:
- Immediate revocation of access privileges
- Disciplinary action up to and including termination
- Civil or criminal penalties where applicable law has been violated
- Contract termination for third-party violators

## 8. Related Documents

- POL-SEC-002: Change Management Policy
- POL-SEC-003: Incident Response Policy
- POL-SEC-004: Data Classification Policy
- POL-SEC-005: Vendor Management Policy
- STD-SEC-001: Password and Authentication Standard
- PRO-SEC-001: User Provisioning Procedure
- PRO-SEC-002: Access Review Procedure

## 9. Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2022-01-15 | J. Martinez, CISO | Initial release |
| 2.0 | 2023-03-01 | J. Martinez, CISO | Added cloud access controls, updated MFA requirements |
| 3.0 | 2024-03-15 | S. Patel, Security Director | Added zero-trust references, FIDO2 preference, session limits |
| 3.1 | 2024-09-01 | S. Patel, Security Director | Updated dormant account timeline, added ZTNA |
| 3.2 | 2025-03-15 | S. Patel, Security Director | Annual review; updated cloud key rotation, added break-glass recording |

---

*This document is the property of Acme Corporation and is intended for internal use only. Unauthorized distribution is prohibited.*
