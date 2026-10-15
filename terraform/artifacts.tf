resource "random_id" "artifact_bucket_suffix" {
  byte_length = 4
}

resource "oci_objectstorage_bucket" "artifacts" {
  compartment_id = var.compartment_ocid
  namespace      = data.oci_objectstorage_namespace.this.namespace
  name           = "${var.name_prefix}-artifacts-${random_id.artifact_bucket_suffix.hex}"
  access_type    = "NoPublicAccess"
  storage_tier   = "Standard"
  freeform_tags  = local.tags
}

resource "oci_objectstorage_object" "operator_payload" {
  namespace = data.oci_objectstorage_namespace.this.namespace
  bucket    = oci_objectstorage_bucket.artifacts.name
  object    = local.operator_payload_name
  source    = local.operator_payload_path

  metadata = {
    sha256 = local.operator_payload_sha256
  }
}
