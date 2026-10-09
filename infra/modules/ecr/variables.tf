variable "name_prefix" {
  description = "Prefix for resource names, e.g. asc-dev."
  type        = string
}

variable "kms_key_arn" {
  description = "KMS key used to encrypt images."
  type        = string
}

variable "keep_images" {
  description = "Number of images to keep."
  type        = number
  default     = 10
}

variable "force_delete" {
  description = "Allow deleting the repository with images in it (dev only)."
  type        = bool
  default     = false
}

variable "tags" {
  description = "Tags applied to every resource."
  type        = map(string)
  default     = {}
}
