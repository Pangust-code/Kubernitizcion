# NAMESPACE
![alt text](/evidencia/namespace.png)
Se creó el namespace mas-localhost para aislar los recursos de la migración a Kubernetes. Luego se configuró el contexto actual de kubectl para trabajar directamente dentro de este namespace.
# API imagen
![alt text](</evidencia/Api image.png>)
Se construyó la imagen local demo-api:1.0.0 a partir del Dockerfile del proyecto y se cargó dentro de Minikube. Esto permite que Kubernetes ejecute la API sin depender de un registry externo.
# SECRETS Redis y Grafana
![alt text](/evidencia/Secrets_RyG.png)
Se crearon Secrets para almacenar las credenciales de Redis y Grafana dentro del namespace mas-localhost. Esto permite separar la información sensible de los archivos de configuración normales y evita escribir credenciales directamente dentro de los Deployments.
# ConfigMap
![alt text](/evidencia/ConfigMap.png)
*Se creó el ConfigMap api-config para almacenar la configuración operacional de la API, como el ambiente, nivel de logs, TTL de caché y parámetros de rate limiting. Esta configuración no es sensible, por eso se administra mediante ConfigMap.*
# Desplegar REDIS
![alt text](/evidencia/Desp_Redis.png)
Se desplegó Redis en Kubernetes mediante un Deployment con una réplica y un Service interno de tipo ClusterIP. La contraseña fue inyectada desde el Secret redis-secret. Además, se configuraron readinessProbe, livenessProbe y límites de recursos para mejorar la disponibilidad y control del consumo del Pod.
# API FastAPI
![alt text](/evidencia/FastAPI.png)
Se desplegó la API FastAPI en Kubernetes mediante un Deployment con 2 réplicas. La imagen local demo-api:1.0.0 fue cargada en Minikube y usada con imagePullPolicy: Never. Además, se configuraron probes, recursos, RollingUpdate e init container para esperar la disponibilidad de Redis.
# Port-forward
![alt text](/evidencia/Port-forward.png)
![alt text](/evidencia/Port_pruebas.png)
Se probó la API FastAPI dentro de Kubernetes usando kubectl port-forward hacia el Service api-service. Los endpoints /health, /ready, /info e /items/ respondieron correctamente, confirmando que la API y su conexión con Redis funcionan dentro del clúster.
# crear Nginx
![alt text](/evidencia/nginx-config.png)
![alt text](/evidencia/nginx.png)
![alt text](</evidencia/endpoint info.png>)
Se desplegó Nginx en Kubernetes como punto de entrada externo de la aplicación. Su configuración se administró mediante un ConfigMap y el acceso externo se realizó mediante un Service de tipo NodePort. Al realizar varias peticiones al endpoint /info, se observó que las respuestas provienen de distintas réplicas de la API, demostrando el balanceo de carga dentro del clúster.
# Observabilidad
![alt text](/evidencia/Observability.png)
![alt text](/evidencia/targets.png)
Durante el despliegue de observabilidad se detectó que el puerto 30090 ya estaba ocupado por otro Service. Se corrigió el nodePort de Prometheus a 30091 y se aplicó nuevamente el manifiesto. Después de la corrección, Prometheus, Grafana y los exporters quedaron desplegados correctamente en Kubernetes.
# Prometheus
![alt text](/evidencia/up.png)
![alt text](/evidencia/cons_http_total.png)
![alt text](/evidencia/redis_up.png)
Se accedió a Prometheus desplegado dentro de Kubernetes y se verificó que los targets de la API, Redis exporter, Nginx exporter y Prometheus se encuentran en estado UP. También se consultaron métricas HTTP y de Redis para comprobar que la recolección de métricas está activa.
# Abrir Grafana
![alt text](/evidencia/GrafanaCredenciales.png)
![alt text](/evidencia/grafana_up.png)
![alt text](/evidencia/grafana_http.png)
Se accedió a Grafana y se verificó que Prometheus está configurado como fuente de datos. Desde la sección Explore se consultaron métricas activas del sistema, confirmando que Grafana puede visualizar información recolectada dentro del clúster.
# Tráfico Real Nginx
![alt text](/evidencia/traficoInfo_Items.png)
![alt text](/evidencia/prometeus_httpNew.png)
Se generó tráfico real hacia la API mediante Nginx usando la URL http://127.0.0.1:59985. Luego se verificó en Prometheus que las métricas HTTP se actualizan, demostrando observabilidad activa dentro del clúster Kubernetes.
# Crear HPA
![alt text](</evidencia/hpa conf.png>)
Se habilitó metrics-server para permitir que Kubernetes obtenga métricas de CPU y memoria. Luego se creó el HPA demo-api-hpa, asociado al Deployment demo-api, con un mínimo de 2 réplicas y un máximo de 6. El umbral de CPU se configuró en 30% para observar el escalado en el entorno local de Minikube
# HPA bajo carga
![alt text](/evidencia/cargaHPA.png)
Se generó carga sobre la API usando Pods temporales load-generator. El HPA monitoreó el consumo de CPU del Deployment demo-api y ajustó el número de réplicas según el umbral configurado. Esto demuestra una capacidad de Kubernetes que Docker Compose no ofrece de forma nativa: el escalado automático basado en métricas.
# Rolling Update
![alt text](</evidencia/version 2.png>)
Se verificó el endpoint /info a través de Nginx y la API respondió con la versión 2.0.0, confirmando que el Rolling Update fue aplicado correctamente.
# Rollback
![alt text](/evidencia/rollback.png)
![alt text](</evidencia/rollback info.png>)
Se ejecutó un rollback del Deployment demo-api, regresando desde la versión 2.0.0 a la versión anterior. Kubernetes actualizó progresivamente los Pods y la API continuó respondiendo a través de Nginx.
# 2 Mejoras
![alt text](/evidencia/2Mejoras.png)
Se implementaron dos mejoras adicionales sobre la arquitectura migrada a Kubernetes. Primero, se creó un PodDisruptionBudget para el Deployment demo-api, garantizando que al menos una réplica de la API permanezca disponible durante interrupciones voluntarias. Segundo, se creó un ResourceQuota para limitar el consumo total de CPU, memoria y cantidad de Pods dentro del namespace mas-localhost. Estas capacidades permiten mayor control operativo que Docker Compose no ofrece de forma nativa.