output "app_name" {
  value = juju_application.katib_controller.name
}

output "provides" {
  value = {
    metrics_endpoint  = "metrics-endpoint",
    grafana_dashboard = "grafana-dashboard",
  }
}

output "requires" {
  value = {
    k8s_service_info = "k8s-service-info"
    logging          = "logging"
  }
}
