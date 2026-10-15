# User-centered design

## Product boundary

- **Resource Manager:** what private OKE/RDMA platform should exist?
- **Control Center:** are the live nodes healthy, and how should RDMA be configured and proven?

Values that are unknown until nodes boot—PF, MTU, link consistency and VF capability—are not requested during Terraform provisioning.

## Primary personas

| Persona | Success moment | Product response |
| --- | --- | --- |
| HPC application owner | A verified RDMA environment and a clear workload launch path | guided state, measured result, no CRD knowledge required |
| Cloud/HPC engineer | Can diagnose a bad BM node before node-changing operations | managed-node query, plugin/interface correlation, downloadable report, break-glass command |
| Security/platform owner | Can explain reachability, credentials and blast radius | private topology, instance principal, typed approval, immutable artifacts, allowlisted actions |

## Design principles

1. Ask only for decisions the user owns.
2. Derive Ubuntu OKE bootstrap values from the selected version.
3. Query live nodes instead of guessing shape-specific PF names.
4. Do not highlight a different MLX5 interface merely because the intended PF is unhealthy.
5. Separate read-only diagnosis, saved configuration and node mutation.
6. Use pass/warn/block with actionable causes.
7. Lock resource-defining settings after Kubernetes resources exist.
8. Preserve expert break-glass access without making it the normal path.
9. Never call infrastructure completion RDMA success.
10. Make evidence exportable for support and change review.

## Golden path

```text
Deploy stack
  -> open private UI
  -> query managed nodes
  -> resolve node/plugin/PF blockers
  -> discover healthy RDMA PF
  -> save settings
  -> approve VF policy
  -> wait for reconciliation
  -> approve VF network
  -> run finite cross-node validation
```

## Accessibility

The UI uses semantic labels/headings, keyboard-operable native controls, visible focus, text plus color for state, responsive layouts and an `aria-live` status surface. Formal WCAG testing is still required before claiming conformance.
