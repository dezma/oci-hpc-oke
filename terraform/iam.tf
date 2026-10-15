resource "oci_identity_dynamic_group" "operator" {
  compartment_id = var.tenancy_ocid
  name           = "${var.name_prefix}-operator"
  description    = "Instance-principal identity for the private OKE RDMA operator VM."
  matching_rule  = "ALL {instance.id = '${oci_core_instance.operator.id}'}"
}

resource "oci_identity_policy" "operator" {
  compartment_id = var.compartment_ocid
  name           = "${var.name_prefix}-operator"
  description    = "Scoped access for the private OKE RDMA operator VM."
  freeform_tags  = local.tags

  statements = [
    "Allow dynamic-group ${oci_identity_dynamic_group.operator.name} to ${local.operator_cluster_verb} clusters in compartment id ${var.compartment_ocid} where target.cluster.id = '${oci_containerengine_cluster.this.id}'",
    "Allow dynamic-group ${oci_identity_dynamic_group.operator.name} to read instances in compartment id ${var.compartment_ocid}",
    "Allow dynamic-group ${oci_identity_dynamic_group.operator.name} to read instance-agent-family in compartment id ${var.compartment_ocid}",
    "Allow dynamic-group ${oci_identity_dynamic_group.operator.name} to read objects in compartment id ${var.compartment_ocid} where all {target.bucket.name = '${oci_objectstorage_bucket.artifacts.name}', target.object.name = '${oci_objectstorage_object.operator_payload.object}'}",
  ]
}
