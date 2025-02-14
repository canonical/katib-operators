resource "juju_application" "katib_db_manager" {
  charm {
    name     = "katib-db-manager"
    channel  = var.channel
    revision = var.revision
  }
  config    = var.config
  model     = var.model_name
  name      = var.app_name
  resources = var.resources
  trust     = true
  units     = 1
}
