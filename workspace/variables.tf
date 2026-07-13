variable "resource_group_name" {
  description = "Name of the resource group"
  type        = string
  default     = "demo-rg-dev-sdc"
}

variable "resource_group_location" {
  description = "Azure region for resource group"
  type        = string
  default     = "swedencentral"
}

variable "resource_group_tags" {
  description = "Tags to apply to the resource group"
  type        = map(string)
  default = {
    environment = "dev"
    owner       = "imran"
    managed-by  = "terraform-coder-agent"
    cost-center = "tag-01"
  }
}
