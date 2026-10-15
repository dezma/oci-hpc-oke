terraform {
  required_version = ">= 1.5.7, < 1.6.0"

  required_providers {
    oci = {
      source  = "oracle/oci"
      version = "~> 9.9.0"
    }
    random = {
      source  = "hashicorp/random"
      version = ">= 3.6.0, < 4.0.0"
    }
  }
}
