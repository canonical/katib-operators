output "app_name" {
  value = juju_application.katib_db_manager.name
}

output "provides" {
  value = {
    k8s_service_info = "k8s-service-info"
  }
}

output "requires" {
  value = {
    relational_db = "relational-db"
    logging       = "logging"
  }
}
