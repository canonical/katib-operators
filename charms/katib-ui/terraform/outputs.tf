output "app_name" {
  value = juju_application.katib_ui.name
}

output "provides" {
  value = {}
}

output "requires" {
  value = {
    ingress         = "ingress",
    dashboard_links = "dashboard-links",
    logging         = "logging",
  }
}
