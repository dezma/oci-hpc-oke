# Threat model

## Assets

- OKE cluster administration capability.
- Managed RDMA worker availability and network configuration.
- OCI Compute Cluster capacity and spend.
- Workload images and validation results.
- Resource Manager state.
- Private operator workspace token and kubeconfig.

## Trust boundaries

```text
administrator workstation
  | OCI IAM + time-limited Bastion
  v
private operator VM
  | instance principal
  +----> read-only Compute / Instance Agent APIs
  +----> one private Object Storage payload
  |
  | private OKE API
  v
OKE
  | privileged infrastructure operators manage SR-IOV
  v
unprivileged RDMA validation/workload pods
```

## Threats and controls

| Threat | Control |
| --- | --- |
| Public exposure of operator or OKE API | private endpoints, no public operator IP, Bastion-only access |
| Bypassing NSG with host firewall misconfiguration | source-restricted NSG **and** matching `firewalld` rich rule for TCP/8000 |
| User OCI credential theft | instance principal; no user API key/private key in browser or payload |
| Arbitrary command execution through UI | allowlisted operations; no generic shell/manifest/SSH endpoint; subprocess argv arrays |
| Wrong PF selected on multi-MLX5 BM host | conservative common-PF checks, MTU range, highest common VF capacity, explicit operator review |
| VF creation on unhealthy node | Kubernetes/OCI plugin/interface preflight and server-side gate immediately before Apply |
| Accidental node disruption | typed confirmation, staged policy/network actions, no routine policy-delete button |
| Duplicate mutations after browser retry | durable SQLite queue and worker lease |
| Supply-chain drift | checksummed payload, pinned/vendored wheels, immutable validation image digest |
| Workload privilege escalation | no host namespaces/network, non-privileged container, no service-account token, minimal capabilities |
| Abuse of node-diagnostics feature | API is read-only; it does not SSH or run host commands; break-glass command is display-only |
| Worker private-key exposure | worker SSH disabled by default; only public key stored by OKE; private key remains on workstation |
| Overclaiming success | infrastructure, API readiness, node health, VF reconciliation and RDMA traffic are separate states |
| Resource Manager state disclosure | stack/state access is privileged; workspace token is sensitive state and root-owned on operator |

## Production review gates

- enterprise OIDC/SSO and per-user RBAC;
- mandatory least-privilege Kubernetes role rather than quickstart `iam_admin`;
- actor-aware audit to OCI Logging/SIEM;
- signed-image admission and registry scanning;
- quotas/budgets and node-count ceilings;
- HA database/queue for multi-replica operation;
- reviewed automated node-recycle and VF-policy migration workflows;
- formal accessibility and penetration testing.
