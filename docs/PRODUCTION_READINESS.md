# Production-readiness roadmap

The quickstart is designed as a secure single-operator private control plane.

## Implemented

- Resource Manager infrastructure state ownership.
- Private enhanced OKE, Compute Cluster, workers and operator.
- Native NFD, Certificate Manager and NVIDIA Network Operator add-ons.
- SR-IOV/VF-only pod networking workflow.
- Instance-principal authentication.
- Bastion-only access plus source-restricted operator `firewalld`.
- Durable worker and explicit approval for node-changing actions.
- Managed-node read-only diagnostics and evidence export.
- Immutable validation image requirement.
- No arbitrary shell/manifest endpoint.
- Conservative PF/MTU/VF gate informed by live node state.

## P0 before broad multi-user use

1. Enterprise OIDC/SSO.
2. Viewer/operator/approver/admin roles.
3. Actor-aware immutable audit export.
4. Enforced least-privilege Kubernetes RBAC mode.
5. OCI Logging/SIEM integration.
6. Signed-image/admission policy.
7. Quota, budget and maximum-node controls.
8. Reviewed node replacement and VF-policy migration runbooks.

## P1 operational hardening

- Managed database/queue for HA.
- OKE/Compute work-request correlation.
- Capacity reservation selection.
- Automated custom-image release qualification.
- Controlled node recycle from the UI through a separate approval workflow.
- Formal accessibility and penetration testing.

## P2 workload profiles

Add reviewed, immutable workload profiles—not arbitrary commands:

- OSU MPI latency/bandwidth;
- OpenFOAM motorBike;
- customer MPI profiles with resource ceilings and cleanup behavior.
