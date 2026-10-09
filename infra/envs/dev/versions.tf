terraform {
  required_version = ">= 1.9.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.68"
    }
  }

  # Partial configuration: supply bucket/key/region at init time, e.g.
  #   terraform init -backend-config=backend.hcl
  # CI only runs `terraform init -backend=false` + validate; nothing is ever applied from CI.
  backend "s3" {
    use_lockfile = true
    encrypt      = true
  }
}

provider "aws" {
  region = var.region

  # Every resource carries these tags; `project` is also the budget's cost-allocation tag.
  default_tags {
    tags = local.tags
  }
}
