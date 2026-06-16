output "app_name" {
  value = juju_application.katib_ui.name
}

output "provides" {
  value = {}
}

output "requires" {
  value = {
    ingress          = "ingress",
    dashboard_links  = "dashboard-links",
    k8s_service_info = "k8s-service-info",
    logging          = "logging",
  }
}
